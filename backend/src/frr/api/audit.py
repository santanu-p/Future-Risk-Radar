"""Audit log API — read-only access to the audit trail (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from frr.api.deps import AdminUser, DbSession
from frr.api.schemas import AuditLogOut
from frr.db.models import AuditLog

router = APIRouter()


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    db: DbSession,
    user: AdminUser,
    resource: str | None = Query(None),
    action: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if resource:
        query = query.where(AuditLog.resource == resource)
    if action:
        query = query.where(AuditLog.action == action)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())
