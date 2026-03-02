"""Training & backtest API router.

Endpoints:
- POST /train          — Trigger model (re)training
- GET  /train/status   — Current training status
- GET  /backtest       — Run backtesting against historical / known crises
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── In-memory training state (MVP; replace with Redis/DB for production) ─────

class _TrainingState:
    status: str = "idle"          # idle | running | completed | failed
    started_at: datetime | None = None
    completed_at: datetime | None = None
    current_step: str | None = None
    progress: float = 0.0
    error: str | None = None

_state = _TrainingState()


# ── Response schemas ──────────────────────────────────────────────────

class TrainingTriggerResponse(BaseModel):
    status: str
    message: str

class TrainingStatusResponse(BaseModel):
    status: str
    started_at: str | None
    completed_at: str | None
    current_step: str | None
    progress: float
    error: str | None

class BacktestResponse(BaseModel):
    total_points: int
    detections: int
    avg_brier_score: float
    avg_brier_skill_score: float
    avg_auc: float
    brier_scores: dict[str, float]
    roc_results: dict[str, Any]
    known_crisis_validations: list[dict[str, Any]]


# ── Background training task ─────────────────────────────────────────

async def _run_training() -> None:
    """Execute the full training pipeline in the background."""
    global _state
    _state.status = "running"
    _state.started_at = datetime.now(timezone.utc)
    _state.completed_at = None
    _state.error = None
    _state.progress = 0.0

    try:
        from frr.models.training import train_pipeline

        # The training pipeline is sync-heavy (PyTorch), so run in executor
        def _update_step(step: str, pct: float) -> None:
            _state.current_step = step
            _state.progress = pct

        _update_step("Building dataset", 0.05)
        loop = asyncio.get_event_loop()

        # Run training pipeline (blocking) in a thread
        await loop.run_in_executor(None, train_pipeline)

        _state.status = "completed"
        _state.progress = 1.0
        _state.current_step = "Done"
        _state.completed_at = datetime.now(timezone.utc)
        logger.info("Training pipeline completed")

    except Exception as e:
        _state.status = "failed"
        _state.error = str(e)
        _state.completed_at = datetime.now(timezone.utc)
        logger.error("Training pipeline failed", error=str(e))


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/train", response_model=TrainingTriggerResponse)
async def trigger_training(background_tasks: BackgroundTasks) -> TrainingTriggerResponse:
    """Trigger model (re)training.

    Returns immediately; actual training runs in the background.
    Poll ``GET /train/status`` for progress.
    """
    if _state.status == "running":
        raise HTTPException(status_code=409, detail="Training is already running")

    background_tasks.add_task(_run_training)
    return TrainingTriggerResponse(
        status="started",
        message="Training pipeline started in the background.",
    )


@router.get("/train/status", response_model=TrainingStatusResponse)
async def training_status() -> TrainingStatusResponse:
    """Get current training pipeline status."""
    return TrainingStatusResponse(
        status=_state.status,
        started_at=_state.started_at.isoformat() if _state.started_at else None,
        completed_at=_state.completed_at.isoformat() if _state.completed_at else None,
        current_step=_state.current_step,
        progress=_state.progress,
        error=_state.error,
    )


@router.get("/backtest", response_model=BacktestResponse)
async def run_backtest(
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
) -> BacktestResponse:
    """Run the backtesting framework against historical data.

    This is a synchronous operation and may take 30–60 s for the full
    2015-2024 range.
    """
    from frr.scoring.backtest import run_full_backtest
    from frr.db.session import get_session_factory

    factory = get_session_factory()

    try:
        async with factory() as session:
            result = await run_full_backtest(session)
    except Exception as e:
        logger.error("Backtest failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Backtest failed: {e}")

    # Serialise ROC results
    roc_dict = {}
    if hasattr(result, "roc_results") and result.roc_results:
        for ct, roc in result.roc_results.items():
            roc_dict[ct] = {
                "auc": roc.auc,
                "best_threshold": roc.best_threshold,
            }

    # Serialise known crisis validations
    kcv = []
    if hasattr(result, "known_crisis_validations") and result.known_crisis_validations:
        for v in result.known_crisis_validations:
            kcv.append({
                "name": v.get("name", ""),
                "region": v.get("region", ""),
                "detected": v.get("detected", False),
                "peak_score": v.get("peak_score", 0.0),
            })

    return BacktestResponse(
        total_points=result.total_points,
        detections=len(result.detections) if hasattr(result, "detections") else 0,
        avg_brier_score=getattr(result, "avg_brier_score", 0.0),
        avg_brier_skill_score=getattr(result, "avg_brier_skill_score", 0.0),
        avg_auc=getattr(result, "avg_auc", 0.0),
        brier_scores=getattr(result, "brier_scores", {}),
        roc_results=roc_dict,
        known_crisis_validations=kcv,
    )
