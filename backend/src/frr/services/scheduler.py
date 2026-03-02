"""APScheduler-based job scheduler for periodic ingestion and scoring."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from frr.config import get_settings

logger = structlog.get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> None:
    """Start the async scheduler with ingestion + scoring jobs."""
    global _scheduler
    settings = get_settings()

    _scheduler = AsyncIOScheduler()

    # ── Ingestion job ──────────────────────────────────────────────────
    _scheduler.add_job(
        _run_ingestion,
        trigger="interval",
        minutes=settings.ingestion_interval_minutes,
        id="ingestion_cycle",
        name="Signal Ingestion Cycle",
        replace_existing=True,
    )

    # ── Scoring job (runs after each ingestion) ────────────────────────
    _scheduler.add_job(
        _run_scoring,
        trigger="interval",
        minutes=settings.ingestion_interval_minutes + 5,
        id="scoring_cycle",
        name="CESI Scoring Cycle",
        replace_existing=True,
    )

    # ── Training job (daily retraining at 03:00 UTC) ──────────────────
    _scheduler.add_job(
        _run_training,
        trigger="cron",
        hour=3,
        minute=0,
        id="training_cycle",
        name="Daily Model Re-training",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started",
        ingestion_interval=settings.ingestion_interval_minutes,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


# ── Job implementations ───────────────────────────────────────────────
async def _run_ingestion() -> None:
    """Execute a full ingestion cycle across all sources."""
    logger.info("Ingestion cycle started")
    from frr.ingestion.runner import run_ingestion_cycle

    await run_ingestion_cycle()
    logger.info("Ingestion cycle completed")


async def _run_scoring() -> None:
    """Recompute CESI scores for all regions."""
    logger.info("Scoring cycle started")
    from frr.scoring.engine import compute_all_cesi

    await compute_all_cesi()
    logger.info("Scoring cycle completed")


async def _run_training() -> None:
    """Execute full model re-training pipeline (GAT → LSTM → Bayesian)."""
    import asyncio

    logger.info("Training cycle started")
    try:
        from frr.models.training import train_pipeline

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, train_pipeline)
        logger.info("Training cycle completed")
    except Exception as e:
        logger.error("Training cycle failed", error=str(e))
