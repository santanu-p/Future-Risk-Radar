"""CESI router — Composite Economic Stress Index endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from frr.api.deps import CurrentUser, DbSession, TenantOrg, get_tenant_region_filter
from frr.api.schemas import (
    CESIHistoryPoint,
    CESIRegionDetail,
    CESIScoreOut,
    PredictionOut,
    RegionOut,
)
from frr.db.models import CESIScore, Prediction, Region

router = APIRouter()


@router.get("/scores", response_model=list[CESIScoreOut])
async def latest_scores(db: DbSession, user: CurrentUser = None, org: TenantOrg = None) -> list[CESIScore]:
    """Latest CESI score for every active region — powers the globe heatmap.

    Multi-tenant: results are filtered to the user's organization's allowed regions.
    """
    query = select(Region).where(Region.active.is_(True))
    allowed_regions = get_tenant_region_filter(org)
    if allowed_regions:
        query = query.where(Region.code.in_(allowed_regions))

    regions_result = await db.execute(query)
    regions = regions_result.scalars().all()

    scores: list[CESIScore] = []
    for region in regions:
        result = await db.execute(
            select(CESIScore)
            .where(CESIScore.region_id == region.id)
            .order_by(CESIScore.scored_at.desc())
            .limit(1)
        )
        score = result.scalar_one_or_none()
        if score:
            scores.append(score)

    return scores


@router.get("/{region_code}", response_model=CESIRegionDetail)
async def region_detail(
    region_code: str,
    db: DbSession,
    history_limit: int = Query(90, ge=1, le=365, description="Days of CESI history"),
) -> CESIRegionDetail:
    """Full CESI detail for a region: current score, history, and predictions."""
    result = await db.execute(select(Region).where(Region.code == region_code.upper()))
    region = result.scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Region '{region_code}' not found")

    # Current score
    current_result = await db.execute(
        select(CESIScore)
        .where(CESIScore.region_id == region.id)
        .order_by(CESIScore.scored_at.desc())
        .limit(1)
    )
    current = current_result.scalar_one_or_none()

    # History
    history_result = await db.execute(
        select(CESIScore)
        .where(CESIScore.region_id == region.id)
        .order_by(CESIScore.scored_at.desc())
        .limit(history_limit)
    )
    history = [
        CESIHistoryPoint(
            score=s.score,
            severity=s.severity.value,
            scored_at=s.scored_at,
        )
        for s in history_result.scalars().all()
    ]

    # Latest predictions per crisis type
    predictions_result = await db.execute(
        select(Prediction)
        .where(Prediction.region_id == region.id)
        .order_by(Prediction.created_at.desc())
        .limit(5)  # one per crisis type
    )
    predictions = list(predictions_result.scalars().all())

    return CESIRegionDetail(
        region=region,
        current_score=current,
        history=history,
        predictions=predictions,
    )


@router.get("/{region_code}/history", response_model=list[CESIHistoryPoint])
async def cesi_history(
    region_code: str,
    db: DbSession,
    since: Optional[datetime] = Query(None),
    limit: int = Query(365, ge=1, le=1000),
) -> list[CESIHistoryPoint]:
    """CESI score history for a region — powers the sparkline charts."""
    result = await db.execute(select(Region).where(Region.code == region_code.upper()))
    region = result.scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Region '{region_code}' not found")

    stmt = (
        select(CESIScore)
        .where(CESIScore.region_id == region.id)
        .order_by(CESIScore.scored_at.asc())
        .limit(limit)
    )
    if since:
        stmt = stmt.where(CESIScore.scored_at >= since)

    scores = await db.execute(stmt)
    return [
        CESIHistoryPoint(score=s.score, severity=s.severity.value, scored_at=s.scored_at)
        for s in scores.scalars().all()
    ]
