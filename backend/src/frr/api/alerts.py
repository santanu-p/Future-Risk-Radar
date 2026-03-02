"""Alert rules & history API — CRUD for alert thresholds and triggered alert log."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, func

from frr.api.deps import AnalystUser, CurrentUser, DbSession, TenantOrg, get_tenant_region_filter
from frr.api.schemas import AlertHistoryOut, AlertRuleCreate, AlertRuleOut, AlertRuleUpdate
from frr.db.models import AlertChannel, AlertHistory, AlertRule

router = APIRouter()


# ── Alert Rules CRUD ───────────────────────────────────────────────────

@router.get("/alerts/rules", response_model=list[AlertRuleOut])
async def list_alert_rules(
    db: DbSession,
    user: CurrentUser,
    org: TenantOrg,
    active_only: bool = Query(True),
) -> list[AlertRule]:
    """List alert rules visible to the current user/org."""
    query = select(AlertRule)
    if org:
        query = query.where(AlertRule.organization_id == org.id)
    elif user.organization_id:
        query = query.where(AlertRule.organization_id == user.organization_id)
    if active_only:
        query = query.where(AlertRule.is_active.is_(True))
    query = query.order_by(AlertRule.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/alerts/rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    body: AlertRuleCreate,
    db: DbSession,
    user: AnalystUser,
    org: TenantOrg,
) -> AlertRule:
    """Create a new alert rule (analyst+ only)."""
    # Validate region if org restricts regions
    allowed = get_tenant_region_filter(org)
    if allowed and body.region_code and body.region_code not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Region not in tenant scope")

    try:
        channel = AlertChannel(body.channel)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid channel: {body.channel}")

    rule = AlertRule(
        name=body.name,
        description=body.description,
        region_code=body.region_code,
        crisis_type=body.crisis_type,
        metric=body.metric,
        operator=body.operator,
        threshold=body.threshold,
        channel=channel,
        channel_config=body.channel_config,
        cooldown_minutes=body.cooldown_minutes,
        organization_id=org.id if org else user.organization_id,
        created_by=user.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/alerts/rules/{rule_id}", response_model=AlertRuleOut)
async def get_alert_rule(rule_id: uuid.UUID, db: DbSession, user: CurrentUser) -> AlertRule:
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule


@router.patch("/alerts/rules/{rule_id}", response_model=AlertRuleOut)
async def update_alert_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    db: DbSession,
    user: AnalystUser,
) -> AlertRule:
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "channel":
            value = AlertChannel(value)
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/alerts/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: uuid.UUID, db: DbSession, user: AnalystUser) -> None:
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await db.delete(rule)
    await db.commit()


# ── Alert History ──────────────────────────────────────────────────────

@router.get("/alerts/history", response_model=list[AlertHistoryOut])
async def list_alert_history(
    db: DbSession,
    user: CurrentUser,
    org: TenantOrg,
    rule_id: uuid.UUID | None = Query(None),
    region_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AlertHistory]:
    """Paginated alert history with optional filters."""
    query = select(AlertHistory).order_by(AlertHistory.fired_at.desc())

    # Tenant scoping — filter by rules belonging to the user's org
    if org:
        query = query.join(AlertRule).where(AlertRule.organization_id == org.id)
    elif user.organization_id:
        query = query.join(AlertRule).where(AlertRule.organization_id == user.organization_id)

    if rule_id:
        query = query.where(AlertHistory.rule_id == rule_id)
    if region_code:
        query = query.where(AlertHistory.region_code == region_code)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/alerts/history/count")
async def alert_history_count(
    db: DbSession,
    user: CurrentUser,
    delivered: bool | None = Query(None),
) -> dict:
    query = select(func.count(AlertHistory.id))
    if delivered is not None:
        query = query.where(AlertHistory.delivered == delivered)
    result = await db.execute(query)
    return {"count": result.scalar() or 0}
