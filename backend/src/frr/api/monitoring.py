"""Model monitoring API — drift snapshots, health checks, and manual triggers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Query, status
from sqlalchemy import select

from frr.api.deps import AdminUser, CurrentUser, DbSession
from frr.api.schemas import DriftSnapshotOut
from frr.db.models import DriftSnapshot
from frr.db.session import get_session_factory

router = APIRouter()


async def _run_drift_in_background() -> None:
    from frr.services.monitoring import run_drift_check
    factory = get_session_factory()
    async with factory() as session:
        await run_drift_check(session)


@router.post("/monitoring/drift-check", status_code=status.HTTP_202_ACCEPTED)
async def trigger_drift_check(background: BackgroundTasks, user: AdminUser) -> dict:
    """Trigger a manual drift detection run (admin only)."""
    background.add_task(_run_drift_in_background)
    return {"status": "accepted", "message": "Drift check started in background"}


@router.get("/monitoring/drift", response_model=list[DriftSnapshotOut])
async def list_drift_snapshots(
    db: DbSession,
    user: CurrentUser,
    drift_type: str | None = Query(None),
    region_code: str | None = Query(None),
    alerts_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[DriftSnapshot]:
    query = select(DriftSnapshot).order_by(DriftSnapshot.computed_at.desc())
    if drift_type:
        query = query.where(DriftSnapshot.drift_type == drift_type)
    if region_code:
        query = query.where(DriftSnapshot.region_code == region_code)
    if alerts_only:
        query = query.where(DriftSnapshot.alert_triggered.is_(True))
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/monitoring/drift/{snapshot_id}", response_model=DriftSnapshotOut)
async def get_drift_snapshot(snapshot_id: uuid.UUID, db: DbSession, user: CurrentUser) -> DriftSnapshot:
    from fastapi import HTTPException
    result = await db.execute(select(DriftSnapshot).where(DriftSnapshot.id == snapshot_id))
    snap = result.scalar_one_or_none()
    if snap is None:
        raise HTTPException(status_code=404, detail="Drift snapshot not found")
    return snap


@router.get("/monitoring/health")
async def model_health(db: DbSession, user: CurrentUser) -> dict:
    """Summary of recent drift alerts across all regions."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Count recent alerts by type
    result = await db.execute(
        select(DriftSnapshot.drift_type, func.count(DriftSnapshot.id))
        .where(DriftSnapshot.computed_at >= cutoff, DriftSnapshot.alert_triggered.is_(True))
        .group_by(DriftSnapshot.drift_type)
    )
    alert_counts = {row[0].value if hasattr(row[0], "value") else row[0]: row[1] for row in result.all()}

    # Total snapshots in last 7 days
    total_result = await db.execute(
        select(func.count(DriftSnapshot.id)).where(DriftSnapshot.computed_at >= cutoff)
    )
    total = total_result.scalar() or 0

    has_alerts = sum(alert_counts.values()) > 0

    return {
        "status": "degraded" if has_alerts else "healthy",
        "recent_drift_alerts": alert_counts,
        "total_snapshots_7d": total,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
