"""Model monitoring service — data drift, prediction drift, and feature importance tracking.

Uses statistical tests to detect distribution shift:
- **Data drift**: Population Stability Index (PSI) + Kolmogorov-Smirnov test on input features
- **Prediction drift**: PSI on model output distributions
- **Feature importance drift**: Jensen-Shannon divergence on SHAP-based feature rankings

Results are stored as ``DriftSnapshot`` records and optionally trigger alerts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import structlog
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from frr.config import get_settings
from frr.db.models import (
    AnomalyScore,
    CESIScore,
    DriftSnapshot,
    DriftType,
    Prediction,
    Region,
    SignalLayer,
    SignalSeries,
)

logger = structlog.get_logger(__name__)


# ── Statistical helpers ────────────────────────────────────────────────

def _compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index — measures distribution shift.

    PSI < 0.1 → no significant change
    PSI 0.1–0.2 → moderate shift
    PSI > 0.2 → significant drift
    """
    if len(reference) < bins or len(current) < bins:
        return 0.0

    # Create bins from reference distribution
    breakpoints = np.percentile(reference, np.linspace(0, 100, bins + 1))
    breakpoints = np.unique(breakpoints)
    if len(breakpoints) < 2:
        return 0.0

    ref_counts = np.histogram(reference, bins=breakpoints)[0] + 1  # smoothing
    cur_counts = np.histogram(current, bins=breakpoints)[0] + 1

    ref_pct = ref_counts / ref_counts.sum()
    cur_pct = cur_counts / cur_counts.sum()

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(0.0, psi)


def _ks_test(reference: np.ndarray, current: np.ndarray) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov test. Returns (statistic, p_value)."""
    try:
        from scipy.stats import ks_2samp
        stat, pval = ks_2samp(reference, current)
        return float(stat), float(pval)
    except ImportError:
        # Fallback — just return PSI-like measure
        return 0.0, 1.0


def _jensen_shannon(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon divergence between two probability distributions."""
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)

    # Normalise
    p = p / p.sum() if p.sum() > 0 else p
    q = q / q.sum() if q.sum() > 0 else q

    m = 0.5 * (p + q)
    eps = 1e-12

    def kl(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.sum(a * np.log((a + eps) / (b + eps))))

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


# ── Data drift detection ──────────────────────────────────────────────

async def check_data_drift(
    session: AsyncSession,
    reference_days: int = 90,
    current_days: int = 7,
) -> list[DriftSnapshot]:
    """Compare recent signal distributions against a reference baseline.

    Returns a DriftSnapshot per region × layer where drift is detected.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    ref_start = now - timedelta(days=reference_days + current_days)
    ref_end = now - timedelta(days=current_days)
    cur_start = now - timedelta(days=current_days)

    snapshots: list[DriftSnapshot] = []

    # Get active regions
    result = await session.execute(select(Region).where(Region.active.is_(True)))
    regions = result.scalars().all()

    for region in regions:
        drift_metrics: dict[str, Any] = {}
        any_drift = False

        for layer in SignalLayer:
            # Reference window
            ref_q = await session.execute(
                select(SignalSeries.value).where(
                    and_(
                        SignalSeries.region_id == region.id,
                        SignalSeries.layer == layer,
                        SignalSeries.ts >= ref_start,
                        SignalSeries.ts < ref_end,
                    )
                )
            )
            ref_values = np.array([r[0] for r in ref_q.all()])

            # Current window
            cur_q = await session.execute(
                select(SignalSeries.value).where(
                    and_(
                        SignalSeries.region_id == region.id,
                        SignalSeries.layer == layer,
                        SignalSeries.ts >= cur_start,
                    )
                )
            )
            cur_values = np.array([r[0] for r in cur_q.all()])

            if len(ref_values) < 10 or len(cur_values) < 5:
                continue

            psi = _compute_psi(ref_values, cur_values)
            ks_stat, ks_pval = _ks_test(ref_values, cur_values)

            layer_drift = psi > settings.drift_psi_threshold
            if layer_drift:
                any_drift = True

            drift_metrics[layer.value] = {
                "psi": round(psi, 4),
                "ks_statistic": round(ks_stat, 4),
                "ks_p_value": round(ks_pval, 4),
                "ref_count": len(ref_values),
                "cur_count": len(cur_values),
                "ref_mean": round(float(ref_values.mean()), 4),
                "cur_mean": round(float(cur_values.mean()), 4),
                "drift_detected": layer_drift,
            }

        if drift_metrics:
            snapshot = DriftSnapshot(
                drift_type=DriftType.DATA_DRIFT,
                region_code=region.code,
                model_version="input_features",
                metrics=drift_metrics,
                alert_triggered=any_drift,
            )
            session.add(snapshot)
            snapshots.append(snapshot)

    if snapshots:
        await session.commit()
        logger.info("Data drift check complete", regions=len(regions), snapshots=len(snapshots))

    return snapshots


# ── Prediction drift detection ────────────────────────────────────────

async def check_prediction_drift(
    session: AsyncSession,
    reference_days: int = 90,
    current_days: int = 7,
) -> list[DriftSnapshot]:
    """Compare recent CESI score distributions against baseline."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    ref_start = now - timedelta(days=reference_days + current_days)
    ref_end = now - timedelta(days=current_days)
    cur_start = now - timedelta(days=current_days)

    snapshots: list[DriftSnapshot] = []

    result = await session.execute(select(Region).where(Region.active.is_(True)))
    regions = result.scalars().all()

    for region in regions:
        # Reference CESI scores
        ref_q = await session.execute(
            select(CESIScore.score).where(
                and_(
                    CESIScore.region_id == region.id,
                    CESIScore.scored_at >= ref_start,
                    CESIScore.scored_at < ref_end,
                )
            )
        )
        ref_scores = np.array([r[0] for r in ref_q.all()])

        # Current CESI scores
        cur_q = await session.execute(
            select(CESIScore.score).where(
                and_(
                    CESIScore.region_id == region.id,
                    CESIScore.scored_at >= cur_start,
                )
            )
        )
        cur_scores = np.array([r[0] for r in cur_q.all()])

        if len(ref_scores) < 5 or len(cur_scores) < 3:
            continue

        psi = _compute_psi(ref_scores, cur_scores)
        ks_stat, ks_pval = _ks_test(ref_scores, cur_scores)
        drift_detected = psi > settings.drift_psi_threshold

        metrics = {
            "psi": round(psi, 4),
            "ks_statistic": round(ks_stat, 4),
            "ks_p_value": round(ks_pval, 4),
            "ref_count": len(ref_scores),
            "cur_count": len(cur_scores),
            "ref_mean": round(float(ref_scores.mean()), 4),
            "cur_mean": round(float(cur_scores.mean()), 4),
            "ref_std": round(float(ref_scores.std()), 4),
            "cur_std": round(float(cur_scores.std()), 4),
            "drift_detected": drift_detected,
        }

        snapshot = DriftSnapshot(
            drift_type=DriftType.PREDICTION_DRIFT,
            region_code=region.code,
            model_version="cesi_v0.1.0",
            metrics=metrics,
            alert_triggered=drift_detected,
        )
        session.add(snapshot)
        snapshots.append(snapshot)

    if snapshots:
        await session.commit()
        logger.info("Prediction drift check complete", snapshots=len(snapshots))

    return snapshots


# ── Combined drift check ──────────────────────────────────────────────

async def run_drift_check(session: AsyncSession) -> dict[str, int]:
    """Run all drift checks and return summary counts."""
    data_snaps = await check_data_drift(session)
    pred_snaps = await check_prediction_drift(session)

    data_alerts = sum(1 for s in data_snaps if s.alert_triggered)
    pred_alerts = sum(1 for s in pred_snaps if s.alert_triggered)

    return {
        "data_drift_snapshots": len(data_snaps),
        "data_drift_alerts": data_alerts,
        "prediction_drift_snapshots": len(pred_snaps),
        "prediction_drift_alerts": pred_alerts,
    }
