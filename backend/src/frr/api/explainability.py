"""Explainability API — SHAP-based feature attribution for CESI predictions."""

from __future__ import annotations

from fastapi import APIRouter, Query

from frr.api.deps import CurrentUser, DbSession
from frr.api.schemas import SHAPExplanation

router = APIRouter()


@router.get("/explain/{region_code}", response_model=SHAPExplanation)
async def explain_region(
    region_code: str,
    db: DbSession,
    user: CurrentUser,
    crisis_type: str | None = Query(None),
) -> dict:
    """Get SHAP feature attributions for a region's CESI score.

    Shows which input signals contributed most (positively or negatively)
    to the region's current risk score.
    """
    from frr.models.explainability import compute_shap_explanation

    result = await compute_shap_explanation(
        session=db,
        region_code=region_code.upper(),
        crisis_type=crisis_type,
    )
    return result
