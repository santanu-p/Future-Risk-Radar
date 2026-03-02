"""Feature-store API endpoints.

Provides online/offline feature retrieval for model serving and diagnostics.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from frr.api.deps import AnalystUser, DbSession, TenantOrg, get_tenant_region_filter
from frr.services.feature_store import get_offline_feature_history, get_online_feature_vector

router = APIRouter()


@router.get("/features/{region_code}/online")
async def online_features(
    region_code: str,
    db: DbSession,
    _user: AnalystUser,
    org: TenantOrg,
    lookback_days: int = Query(30, ge=1, le=365),
):
    """Get latest online feature vector for a region."""
    allowed = get_tenant_region_filter(org)
    if allowed is not None and region_code not in allowed:
        raise HTTPException(status_code=403, detail="Region not allowed for your organization")

    data = await get_online_feature_vector(db, region_code=region_code, lookback_days=lookback_days)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


@router.get("/features/{region_code}/offline")
async def offline_features(
    region_code: str,
    db: DbSession,
    _user: AnalystUser,
    org: TenantOrg,
    months: int = Query(36, ge=3, le=240),
):
    """Get monthly offline feature history for training/backtesting."""
    allowed = get_tenant_region_filter(org)
    if allowed is not None and region_code not in allowed:
        raise HTTPException(status_code=403, detail="Region not allowed for your organization")

    data = await get_offline_feature_history(db, region_code=region_code, months=months)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data
