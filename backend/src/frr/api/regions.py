"""Regions router — CRUD + summary with latest CESI."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from frr.api.deps import CurrentUser, DbSession, TenantOrg, get_tenant_region_filter
from frr.api.schemas import RegionOut, RegionSummary
from frr.db.models import CESIScore, Region

router = APIRouter()


@router.get("/", response_model=list[RegionSummary])
async def list_regions(db: DbSession, user: CurrentUser = None, org: TenantOrg = None) -> list[RegionSummary]:
    """All active regions with their latest CESI score (dashboard list).

    Multi-tenant: results are filtered to the user's organization's allowed regions.
    """
    query = select(Region).where(Region.active.is_(True)).order_by(Region.code)

    # Apply tenant region filter
    allowed_regions = get_tenant_region_filter(org)
    if allowed_regions:
        query = query.where(Region.code.in_(allowed_regions))

    result = await db.execute(query)
    regions = result.scalars().all()

    summaries: list[RegionSummary] = []
    for r in regions:
        # Fetch latest CESI score
        latest = await db.execute(
            select(CESIScore)
            .where(CESIScore.region_id == r.id)
            .order_by(CESIScore.scored_at.desc())
            .limit(1)
        )
        cesi = latest.scalar_one_or_none()

        summaries.append(
            RegionSummary(
                id=r.id,
                code=r.code,
                name=r.name,
                centroid_lat=r.centroid_lat,
                centroid_lon=r.centroid_lon,
                latest_cesi=cesi.score if cesi else None,
                severity=cesi.severity.value if cesi else None,
            )
        )

    return summaries


@router.get("/{region_code}", response_model=RegionOut)
async def get_region(region_code: str, db: DbSession) -> Region:
    result = await db.execute(select(Region).where(Region.code == region_code.upper()))
    region = result.scalar_one_or_none()
    if region is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Region '{region_code}' not found")
    return region
