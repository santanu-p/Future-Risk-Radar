"""CESI Scoring Engine — Composite Economic Stress Index computation.

This is the core intelligence product. It combines:
1. Anomaly z-scores (per-layer)
2. Model predictions (crisis probabilities from LSTM + Bayesian fusion)
3. Cross-layer amplification (correlated stress → non-linear boost)

Formula:
    CESI(r, t) = Σ_l [ w_l · â_l(r, t) ] × A(r, t)

where:
    - w_l = layer weight (research=0.2, patent=0.2, supply_chain=0.3, energy_conflict=0.3)
    - â_l = normalised anomaly score for layer l
    - A(r,t) = amplification factor when multiple layers spike simultaneously

Amplification:
    A(r, t) = 1 + γ · max(0, n_spike(r,t) - 2)

where n_spike = count of layers where â_l > threshold,
and γ is the amplification coefficient (default 15.0 → +15 points per extra spiking layer).

Severity bands:
    0–20:  Stable     | 21–40: Elevated | 41–60: Concerning
    61–80: High Risk  | 81–100: Critical
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from frr.config import get_settings
from frr.db.models import (
    AnomalyScore,
    CESIScore,
    CrisisType,
    Prediction,
    Region,
    SeverityBand,
    SignalLayer,
)
from frr.db.session import get_session_factory

logger = structlog.get_logger(__name__)

# Lazy-import propagation and websocket to avoid circular deps at module level
_propagation = None
_ws_publish = None


def _get_propagation():
    global _propagation
    if _propagation is None:
        from frr.models.propagation import propagate_scores
        _propagation = propagate_scores
    return _propagation


def _get_ws_publish():
    global _ws_publish
    if _ws_publish is None:
        from frr.api.websocket import publish_cesi_update
        _ws_publish = publish_cesi_update
    return _ws_publish

# ── Layer weights — tuned to reflect structural importance ─────────────
LAYER_WEIGHTS: dict[SignalLayer, float] = {
    SignalLayer.RESEARCH_FUNDING: 0.20,
    SignalLayer.PATENT_ACTIVITY: 0.20,
    SignalLayer.SUPPLY_CHAIN: 0.30,
    SignalLayer.ENERGY_CONFLICT: 0.30,
}


def classify_severity(score: float) -> SeverityBand:
    """Map a 0–100 CESI score to a severity band."""
    if score <= 20:
        return SeverityBand.STABLE
    elif score <= 40:
        return SeverityBand.ELEVATED
    elif score <= 60:
        return SeverityBand.CONCERNING
    elif score <= 80:
        return SeverityBand.HIGH_RISK
    else:
        return SeverityBand.CRITICAL


def compute_cesi_score(
    layer_anomalies: dict[SignalLayer, float],
    gamma: float | None = None,
    spike_threshold: float | None = None,
    min_layers: int | None = None,
) -> tuple[float, bool, dict[str, Any]]:
    """Compute a single CESI score from per-layer anomaly values.

    Parameters
    ----------
    layer_anomalies : dict
        {SignalLayer: normalised_anomaly_score} where values are in [0, 100].
    gamma : float
        Amplification coefficient.
    spike_threshold : float
        Threshold above which a layer is considered "spiking".
    min_layers : int
        Minimum spiking layers before amplification kicks in.

    Returns
    -------
    (score, amplification_applied, layer_breakdown)
    """
    settings = get_settings()
    gamma = gamma or settings.cesi_amplification_gamma
    spike_threshold = spike_threshold or settings.cesi_spike_threshold
    min_layers = min_layers or settings.cesi_min_layers_for_amplification

    # Weighted sum
    weighted_sum = 0.0
    layer_breakdown: dict[str, Any] = {}
    for layer, weight in LAYER_WEIGHTS.items():
        anomaly = layer_anomalies.get(layer, 0.0)
        contribution = weight * anomaly
        weighted_sum += contribution
        layer_breakdown[layer.value] = {
            "raw_anomaly": anomaly,
            "weight": weight,
            "contribution": contribution,
        }

    # Amplification: count spiking layers
    n_spike = sum(
        1 for layer, anomaly in layer_anomalies.items()
        if anomaly > spike_threshold * 100  # convert threshold to 0-100 scale
    )

    amplification = 1.0
    amplification_applied = False
    if n_spike >= min_layers:
        amplification = 1.0 + gamma * max(0, n_spike - 2) / 100.0
        amplification_applied = True

    raw_score = weighted_sum * amplification
    score = float(np.clip(raw_score, 0.0, 100.0))

    return score, amplification_applied, layer_breakdown


async def compute_region_cesi(
    session: AsyncSession,
    region: Region,
    model_version: str = "v0.1.0",
) -> CESIScore:
    """Compute and persist a CESI score for a single region.

    Combines the latest anomaly z-scores across all layers into a single score.
    """
    settings = get_settings()

    # Get latest anomaly scores per layer
    layer_anomalies: dict[SignalLayer, float] = {}
    for layer in SignalLayer:
        result = await session.execute(
            select(func.avg(func.abs(AnomalyScore.zscore)))
            .where(
                and_(
                    AnomalyScore.region_id == region.id,
                    AnomalyScore.layer == layer,
                    AnomalyScore.is_anomaly.is_(True),
                )
            )
        )
        avg_zscore = result.scalar()
        if avg_zscore is not None:
            # Normalise z-score to 0-100 scale: z=2→0, z=5→100 (clamped)
            normalised = float(np.clip((avg_zscore - 2.0) / 3.0 * 100, 0, 100))
            layer_anomalies[layer] = normalised
        else:
            layer_anomalies[layer] = 0.0

    # Compute CESI
    score, amplification_applied, layer_breakdown = compute_cesi_score(layer_anomalies)

    # Get latest predictions for this region (if available)
    crisis_probs: dict[str, Any] = {}
    for crisis_type in CrisisType:
        pred_result = await session.execute(
            select(Prediction)
            .where(
                and_(
                    Prediction.region_id == region.id,
                    Prediction.crisis_type == crisis_type,
                )
            )
            .order_by(Prediction.created_at.desc())
            .limit(1)
        )
        pred = pred_result.scalar_one_or_none()
        if pred:
            crisis_probs[crisis_type.value] = {
                "probability": pred.probability,
                "ci_lower": pred.confidence_lower,
                "ci_upper": pred.confidence_upper,
            }

    # Create and persist
    cesi = CESIScore(
        id=uuid.uuid4(),
        region_id=region.id,
        score=score,
        severity=classify_severity(score),
        layer_scores=layer_breakdown,
        crisis_probabilities=crisis_probs,
        amplification_applied=amplification_applied,
        model_version=model_version,
        scored_at=datetime.now(timezone.utc),
    )
    session.add(cesi)
    await session.commit()

    logger.info(
        "CESI scored",
        region=region.code,
        score=round(score, 2),
        severity=cesi.severity.value,
        amplified=amplification_applied,
    )
    return cesi


async def compute_all_cesi(model_version: str = "v0.1.0") -> list[CESIScore]:
    """Recompute CESI scores for all active regions, apply spatial propagation,
    and publish live updates via WebSocket.
    """
    factory = get_session_factory()
    scores: list[CESIScore] = []

    async with factory() as session:
        result = await session.execute(
            select(Region).where(Region.active.is_(True))
        )
        regions = result.scalars().all()

        for region in regions:
            try:
                cesi = await compute_region_cesi(session, region, model_version)
                scores.append(cesi)
            except Exception as e:
                logger.error("CESI computation failed", region=region.code, error=str(e))

    # ── Layer 4: Spatial propagation ──────────────────────────────────
    try:
        region_scores = {
            s.region_id: {"code": None, "score": s.score}
            for s in scores
        }
        # Map region_id → code
        async with factory() as session:
            result = await session.execute(
                select(Region).where(Region.active.is_(True))
            )
            for r in result.scalars().all():
                if r.id in region_scores:
                    region_scores[r.id]["code"] = r.code

        code_to_score = {
            v["code"]: v["score"]
            for v in region_scores.values()
            if v["code"] is not None
        }

        if code_to_score:
            propagate = _get_propagation()
            prop_result = propagate(code_to_score)

            # Apply propagation offsets back to scores
            async with factory() as session:
                for cesi in scores:
                    code = region_scores.get(cesi.region_id, {}).get("code")
                    if code and code in prop_result.delta:
                        delta = prop_result.delta[code]
                        if abs(delta) > 0.5:
                            new_score = float(np.clip(cesi.score + delta, 0, 100))
                            cesi.score = new_score
                            cesi.severity = classify_severity(new_score)
                            # Annotate propagation in layer_scores
                            contagion_from = [
                                d.get("spiking_regions", [])
                                for d in prop_result.contagion_details
                            ]
                            cesi.layer_scores["spatial_propagation"] = {
                                "delta": round(delta, 2),
                                "contagion_from": contagion_from,
                            }
                            session.add(cesi)
                await session.commit()

            logger.info("Spatial propagation applied", regions=len(prop_result.delta))
    except Exception as e:
        logger.warning("Spatial propagation skipped", error=str(e))

    # ── Publish WS updates ────────────────────────────────────────────
    try:
        ws_publish = _get_ws_publish()
        async with factory() as session:
            result = await session.execute(
                select(Region).where(Region.active.is_(True))
            )
            code_map = {r.id: r.code for r in result.scalars().all()}

        for cesi in scores:
            code = code_map.get(cesi.region_id, "UNKNOWN")
            await ws_publish(
                region_code=code,
                score=cesi.score,
                severity=cesi.severity.value,
                amplification_applied=cesi.amplification_applied,
                scored_at=cesi.scored_at.isoformat(),
                crisis_probabilities=cesi.crisis_probabilities,
            )
    except Exception as e:
        logger.debug("WebSocket publish skipped", error=str(e))

    logger.info("CESI scoring complete", regions_scored=len(scores))
    return scores
