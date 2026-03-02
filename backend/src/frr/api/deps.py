"""FastAPI dependencies — shared across routers (RBAC, API key, tenant scoping)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from frr.config import get_settings
from frr.db.models import ApiKey, Organization, User, UserRole
from frr.db.session import get_session

security = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session — auto-closed after request."""
    async for session in get_session():
        yield session


# ── JWT user auth ──────────────────────────────────────────────────────

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate via JWT bearer token **or** X-Api-Key header.

    API-key auth: hash the provided key, look up in ``api_keys`` table,
    and return the creating user (or a synthetic one for org-level keys).
    """
    # Try API-key auth first
    if x_api_key:
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        result = await db.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        )
        api_key_obj = result.scalar_one_or_none()
        if api_key_obj is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        # Check expiry
        if api_key_obj.expires_at and api_key_obj.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

        # Update last_used_at
        api_key_obj.last_used_at = datetime.now(timezone.utc)
        await db.commit()

        # Resolve the creating user
        if api_key_obj.created_by:
            user_result = await db.execute(select(User).where(User.id == api_key_obj.created_by))
            user = user_result.scalar_one_or_none()
            if user and user.is_active:
                return user

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key user not found")

    # JWT auth
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        email: str | None = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token validation failed")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


# ── Role-based guards ─────────────────────────────────────────────────

def require_role(*roles: UserRole):
    """Factory that returns a dependency enforcing one of the given roles."""

    async def _guard(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(r.value for r in roles)}",
            )
        return user

    return _guard


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Admin-only guard — matches ADMIN or SUPER_ADMIN roles."""
    if user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN) and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_analyst_or_above(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Analyst, admin, or super_admin."""
    allowed = {UserRole.ANALYST, UserRole.ADMIN, UserRole.SUPER_ADMIN}
    if user.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Analyst access required")
    return user


async def require_super_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Super-admin only — for cross-org operations."""
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super-admin access required")
    return user


# ── Tenant scoping ────────────────────────────────────────────────────

async def get_tenant_org(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Organization | None:
    """Resolve the user's organization for tenant-scoped queries.

    Super-admins with no org may access all data (returns None).
    """
    if user.organization_id is None:
        if user.role == UserRole.SUPER_ADMIN:
            return None  # global access
        return None  # org-less user — gets default view
    result = await db.execute(
        select(Organization).where(Organization.id == user.organization_id, Organization.is_active.is_(True))
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization inactive or not found")
    return org


def get_tenant_region_filter(org: Organization | None) -> list[str] | None:
    """Return the list of region codes the current tenant may access.

    Returns ``None`` when ALL regions are allowed (super-admin / no restriction).
    """
    if org is None:
        return None
    regions = org.allowed_regions
    if not regions:
        return None  # empty list = all regions
    return regions


# ── Type aliases ───────────────────────────────────────────────────────
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
AnalystUser = Annotated[User, Depends(require_analyst_or_above)]
SuperAdmin = Annotated[User, Depends(require_super_admin)]
TenantOrg = Annotated[Organization | None, Depends(get_tenant_org)]
