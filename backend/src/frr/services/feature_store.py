"""Custom feature-store service backed by TimescaleDB.

Implements online and offline feature retrieval using existing FRR tables.
This satisfies the plan's "Feast or custom feature store" requirement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from frr.db.models import AnomalyScore, Region, SignalSeries


async def get_region_or_none(session: AsyncSession, region_code: str) -> Region | None:
    result = await session.execute(select(Region).where(Region.code == region_code))
    return result.scalar_one_or_none()


async def get_online_feature_vector(
    session: AsyncSession,
    region_code: str,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Return latest online feature vector for a region.

    Includes:
    - latest value per source/indicator
    - layer-level anomaly intensity (rolling lookback window)
    """
    region = await get_region_or_none(session, region_code)
    if region is None:
        return {"error": f"unknown region: {region_code}"}

    # Latest raw signal values (bounded query to keep endpoint responsive)
    signals_result = await session.execute(
        select(SignalSeries)
        .where(SignalSeries.region_id == region.id)
        .order_by(SignalSeries.ts.desc())
        .limit(4000)
    )
    rows = signals_result.scalars().all()

    latest_by_key: dict[tuple[str, str], SignalSeries] = {}
    for row in rows:
        key = (row.source, row.indicator)
        if key not in latest_by_key:
            latest_by_key[key] = row

    signal_features = {
        f"{r.source}:{r.indicator}": {
            "value": float(r.value),
            "layer": r.layer.value,
            "ts": r.ts.isoformat(),
        }
        for r in latest_by_key.values()
    }

    # Layer-level anomaly intensity over the lookback window
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    anomaly_result = await session.execute(
        select(
            AnomalyScore.layer,
            func.avg(func.abs(AnomalyScore.zscore)).label("avg_abs_zscore"),
            func.sum(
                case((AnomalyScore.is_anomaly.is_(True), 1), else_=0)
            ).label("anomaly_count"),
        )
        .where(
            and_(
                AnomalyScore.region_id == region.id,
                AnomalyScore.ts >= since,
            )
        )
        .group_by(AnomalyScore.layer)
    )

    anomaly_features: dict[str, Any] = {}
    for layer, avg_abs_zscore, anomaly_count in anomaly_result.all():
        anomaly_features[layer.value] = {
            "avg_abs_zscore": float(avg_abs_zscore or 0.0),
            "anomaly_count": int(anomaly_count or 0),
        }

    return {
        "region_code": region.code,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "signals": signal_features,
        "anomalies": anomaly_features,
    }


async def get_offline_feature_history(
    session: AsyncSession,
    region_code: str,
    months: int = 36,
) -> dict[str, Any]:
    """Return monthly offline feature history for training/backtesting."""
    region = await get_region_or_none(session, region_code)
    if region is None:
        return {"error": f"unknown region: {region_code}"}

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=months * 31)

    result = await session.execute(
        select(
            func.date_trunc("month", SignalSeries.ts).label("month"),
            SignalSeries.source,
            SignalSeries.indicator,
            func.avg(SignalSeries.value).label("avg_value"),
        )
        .where(
            and_(
                SignalSeries.region_id == region.id,
                SignalSeries.ts >= start,
            )
        )
        .group_by(
            func.date_trunc("month", SignalSeries.ts),
            SignalSeries.source,
            SignalSeries.indicator,
        )
        .order_by(func.date_trunc("month", SignalSeries.ts).asc())
    )

    by_month: dict[str, dict[str, float]] = {}
    for month, source, indicator, avg_value in result.all():
        month_key = month.strftime("%Y-%m")
        by_month.setdefault(month_key, {})[f"{source}:{indicator}"] = float(avg_value)

    history = [
        {"month": month, "features": features}
        for month, features in by_month.items()
    ]

    return {
        "region_code": region.code,
        "months": months,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history": history,
    }
