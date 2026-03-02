"""SHAP explainability module — per-prediction feature attribution.

Provides interpretable breakdowns of which input signals drove a given CESI score
or crisis probability prediction using SHAP (SHapley Additive exPlanations).

For the MVP, we use a surrogate model approach:
1. Collect the latest feature matrix (signal values per layer × region)
2. Train a lightweight gradient-boosted surrogate on CESI scores
3. Compute SHAP values using TreeExplainer
4. Return top-K features with their SHAP contributions

This avoids requiring SHAP-compatible wrappers around the GAT/LSTM/Bayesian ensemble.
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
    CrisisType,
    Prediction,
    Region,
    SignalLayer,
    SignalSeries,
)

logger = structlog.get_logger(__name__)


async def _build_feature_matrix(
    session: AsyncSession,
    lookback_days: int = 60,
) -> tuple[np.ndarray, list[str], list[str], np.ndarray]:
    """Build a feature matrix from recent signal data.

    Returns (X, feature_names, region_codes, y) where:
    - X: (n_samples, n_features) — signal values
    - feature_names: list of "layer::source::indicator" feature labels
    - region_codes: list of region codes corresponding to rows
    - y: (n_samples,) — CESI scores (target)
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    # Get all regions with scores
    region_result = await session.execute(select(Region).where(Region.active.is_(True)))
    regions = region_result.scalars().all()

    # Collect feature columns from signal data
    # First pass: discover all unique (layer, source, indicator) tuples
    feat_q = await session.execute(
        select(
            SignalSeries.layer, SignalSeries.source, SignalSeries.indicator
        ).where(SignalSeries.ts >= cutoff).distinct()
    )
    feature_keys: list[tuple[str, str, str]] = []
    feature_names: list[str] = []
    for row in feat_q.all():
        layer_val = row[0].value if hasattr(row[0], "value") else str(row[0])
        key = (layer_val, row[1], row[2])
        feature_keys.append(key)
        feature_names.append(f"{layer_val}::{row[1]}::{row[2]}")

    if not feature_keys or not regions:
        return np.array([]), feature_names, [], np.array([])

    # Build matrix: for each region, get average signal value per feature
    X_rows: list[list[float]] = []
    y_vals: list[float] = []
    region_codes: list[str] = []

    for region in regions:
        # Get latest CESI score
        cesi_q = await session.execute(
            select(CESIScore.score)
            .where(CESIScore.region_id == region.id)
            .order_by(CESIScore.scored_at.desc())
            .limit(1)
        )
        score_row = cesi_q.scalar_one_or_none()
        if score_row is None:
            continue

        row_values: list[float] = []
        for layer_val, source, indicator in feature_keys:
            val_q = await session.execute(
                select(func.avg(SignalSeries.value)).where(
                    and_(
                        SignalSeries.region_id == region.id,
                        SignalSeries.source == source,
                        SignalSeries.indicator == indicator,
                        SignalSeries.ts >= cutoff,
                    )
                )
            )
            avg_val = val_q.scalar()
            row_values.append(float(avg_val) if avg_val is not None else 0.0)

        X_rows.append(row_values)
        y_vals.append(float(score_row))
        region_codes.append(region.code)

    return np.array(X_rows), feature_names, region_codes, np.array(y_vals)


async def compute_shap_explanation(
    session: AsyncSession,
    region_code: str,
    crisis_type: str | None = None,
) -> dict[str, Any]:
    """Compute SHAP values for a specific region's CESI score.

    Returns a dict with:
    - top_features: list of {feature, shap_value, abs_importance}
    - shap_values: full dict of feature → shap value
    - base_value: expected model output value
    - model_version: surrogate model identifier
    """
    settings = get_settings()

    X, feature_names, region_codes, y = await _build_feature_matrix(session)

    if X.size == 0 or len(X) < 3:
        return {
            "region_code": region_code,
            "crisis_type": crisis_type,
            "top_features": [],
            "shap_values": {},
            "base_value": 0.0,
            "model_version": "insufficient_data",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # Find the target region index
    try:
        target_idx = region_codes.index(region_code)
    except ValueError:
        return {
            "region_code": region_code,
            "crisis_type": crisis_type,
            "top_features": [],
            "shap_values": {},
            "base_value": 0.0,
            "model_version": "region_not_found",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    try:
        # Train a lightweight surrogate (GradientBoosting)
        from sklearn.ensemble import GradientBoostingRegressor
        import shap

        model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )
        model.fit(X, y)

        # SHAP TreeExplainer
        n_background = min(settings.shap_background_samples, len(X))
        explainer = shap.TreeExplainer(model, X[:n_background])
        shap_values = explainer.shap_values(X[target_idx:target_idx + 1])

        sv = shap_values[0]  # Single sample
        base_value = float(explainer.expected_value)

        # Build sorted feature importance
        feature_importance: list[dict[str, Any]] = []
        for i, fname in enumerate(feature_names):
            feature_importance.append({
                "feature": fname,
                "shap_value": round(float(sv[i]), 4),
                "abs_importance": round(abs(float(sv[i])), 4),
            })

        feature_importance.sort(key=lambda x: x["abs_importance"], reverse=True)
        top_features = feature_importance[: settings.shap_max_features]

        shap_dict = {fname: round(float(sv[i]), 4) for i, fname in enumerate(feature_names)}

        return {
            "region_code": region_code,
            "crisis_type": crisis_type,
            "top_features": top_features,
            "shap_values": shap_dict,
            "base_value": round(base_value, 4),
            "model_version": "surrogate_gbr_v1",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    except ImportError as e:
        logger.warning("SHAP/sklearn not available", error=str(e))
        return {
            "region_code": region_code,
            "crisis_type": crisis_type,
            "top_features": [],
            "shap_values": {},
            "base_value": 0.0,
            "model_version": "dependencies_missing",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("SHAP computation failed", error=str(e), region=region_code)
        return {
            "region_code": region_code,
            "crisis_type": crisis_type,
            "top_features": [],
            "shap_values": {},
            "base_value": 0.0,
            "model_version": f"error: {str(e)[:100]}",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
