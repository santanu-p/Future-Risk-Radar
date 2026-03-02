"""Signals router — time-series data, anomaly scores, and filtering."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, select

from frr.api.deps import DbSession
from frr.api.schemas import SignalOut, SignalTimeSeries, SignalTimeSeriesPoint
from frr.db.models import AnomalyScore, Region, SignalLayer, SignalSeries

router = APIRouter()


@router.get("/{region_code}", response_model=list[SignalOut])
async def list_signals(
    region_code: str,
    db: DbSession,
    layer: Optional[SignalLayer] = Query(None, description="Filter by signal layer"),
    source: Optional[str] = Query(None, description="Filter by data source (e.g. FRED)"),
    since: Optional[datetime] = Query(None, description="Only signals after this timestamp"),
    limit: int = Query(500, ge=1, le=5000),
) -> list[SignalSeries]:
    """Fetch raw signal data for a region with optional filters."""
    region = await _get_region_or_404(db, region_code)

    stmt = select(SignalSeries).where(SignalSeries.region_id == region.id)
    if layer:
        stmt = stmt.where(SignalSeries.layer == layer)
    if source:
        stmt = stmt.where(SignalSeries.source == source)
    if since:
        stmt = stmt.where(SignalSeries.ts >= since)

    stmt = stmt.order_by(SignalSeries.ts.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{region_code}/timeseries", response_model=SignalTimeSeries)
async def get_timeseries(
    region_code: str,
    db: DbSession,
    source: str = Query(..., description="Data source (e.g. FRED)"),
    indicator: str = Query(..., description="Indicator code (e.g. GDP_GROWTH)"),
    since: Optional[datetime] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
) -> SignalTimeSeries:
    """Single indicator time-series with anomaly z-scores overlaid."""
    region = await _get_region_or_404(db, region_code)

    signals_stmt = (
        select(SignalSeries)
        .where(
            and_(
                SignalSeries.region_id == region.id,
                SignalSeries.source == source,
                SignalSeries.indicator == indicator,
            )
        )
        .order_by(SignalSeries.ts.asc())
        .limit(limit)
    )
    if since:
        signals_stmt = signals_stmt.where(SignalSeries.ts >= since)

    result = await db.execute(signals_stmt)
    signals = result.scalars().all()

    if not signals:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No data for this indicator")

    # Enrich with anomaly scores
    signal_ids = [s.id for s in signals]
    anomaly_result = await db.execute(
        select(AnomalyScore).where(AnomalyScore.signal_id.in_(signal_ids))
    )
    anomalies = {a.signal_id: a for a in anomaly_result.scalars().all()}

    data_points = []
    for s in signals:
        a = anomalies.get(s.id)
        data_points.append(
            SignalTimeSeriesPoint(
                ts=s.ts,
                value=s.value,
                zscore=a.zscore if a else None,
                is_anomaly=a.is_anomaly if a else False,
            )
        )

    return SignalTimeSeries(
        region_code=region.code,
        source=source,
        indicator=indicator,
        layer=signals[0].layer.value,
        data=data_points,
    )


async def _get_region_or_404(db, region_code: str) -> Region:
    result = await db.execute(select(Region).where(Region.code == region_code.upper()))
    region = result.scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Region '{region_code}' not found")
    return region
