"""Organizations API — multi-tenant org management + API key CRUD."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from frr.api.deps import AdminUser, CurrentUser, DbSession, SuperAdmin
from frr.api.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from frr.db.models import ApiKey, Organization

router = APIRouter()


# ── Organizations ──────────────────────────────────────────────────────

@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(db: DbSession, user: AdminUser) -> list[Organization]:
    result = await db.execute(
        select(Organization).where(Organization.is_active.is_(True)).order_by(Organization.name)
    )
    return list(result.scalars().all())


@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(body: OrganizationCreate, db: DbSession, user: SuperAdmin) -> Organization:
    # Check slug uniqueness
    existing = await db.execute(select(Organization).where(Organization.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already in use")

    org = Organization(
        name=body.name,
        slug=body.slug,
        allowed_regions=body.allowed_regions,
        tier=body.tier,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/organizations/{org_id}", response_model=OrganizationOut)
async def get_organization(org_id: uuid.UUID, db: DbSession, user: AdminUser) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.patch("/organizations/{org_id}", response_model=OrganizationOut)
async def update_organization(
    org_id: uuid.UUID, body: OrganizationUpdate, db: DbSession, user: SuperAdmin
) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(org, field, value)

    await db.commit()
    await db.refresh(org)
    return org


# ── API Keys ───────────────────────────────────────────────────────────

@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(db: DbSession, user: AdminUser) -> list[ApiKey]:
    """List API keys for the user's organization."""
    query = select(ApiKey).where(ApiKey.is_active.is_(True))
    if user.organization_id:
        query = query.where(ApiKey.organization_id == user.organization_id)
    query = query.order_by(ApiKey.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(body: ApiKeyCreate, db: DbSession, user: AdminUser) -> dict:
    """Generate a new API key. The raw key is shown ONLY in this response."""
    if not user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to an organization to create API keys",
        )

    # Generate raw key: frr_<random-hex>
    raw_key = f"frr_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:12]

    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    api_key = ApiKey(
        organization_id=user.organization_id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        expires_at=expires_at,
        created_by=user.id,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return {
        "key": raw_key,
        "detail": api_key,
    }


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID, db: DbSession, user: AdminUser) -> None:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = False
    await db.commit()
