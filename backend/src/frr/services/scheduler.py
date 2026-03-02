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

    # ── Drift detection (daily at 04:00 UTC) ──────────────────────────
    _scheduler.add_job(
        _run_drift_check,
        trigger="cron",
        hour=4,
        minute=0,
        id="drift_check",
        name="Model Drift Detection",
        replace_existing=True,
    )

    # ── NLP / GDELT scan (hourly) ─────────────────────────────────────
    _scheduler.add_job(
        _run_nlp_scan,
        trigger="interval",
        minutes=settings.gdelt_scan_interval_minutes,
        id="nlp_scan",
        name="GDELT NLP Scan",
        replace_existing=True,
    )

    # ── Monthly report generation (1st of month at 06:00 UTC) ─────────
    _scheduler.add_job(
        _run_monthly_reports,
        trigger="cron",
        day=1,
        hour=6,
        minute=0,
        id="monthly_reports",
        name="Monthly Report Generation",
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


async def _run_drift_check() -> None:
    """Run data drift + prediction drift detection."""
    logger.info("Drift check started")
    try:
        from frr.services.monitoring import run_drift_check
        from frr.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            result = await run_drift_check(session)
            logger.info("Drift check completed", **result)
    except Exception as e:
        logger.error("Drift check failed", error=str(e))


async def _run_nlp_scan() -> None:
    """Scan GDELT/news sources for NLP-based risk signals."""
    logger.info("NLP scan started")
    try:
        from frr.ingestion.sources.news_nlp import scan_and_ingest_news
        from frr.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            result = await scan_and_ingest_news(session)
            logger.info("NLP scan completed", **result)
    except Exception as e:
        logger.error("NLP scan failed", error=str(e))


async def _run_monthly_reports() -> None:
    """Generate monthly intelligence briefs for all active regions."""
    from datetime import datetime, timedelta, timezone

    logger.info("Monthly report generation started")
    try:
        from frr.services.reports import generate_report
        from frr.db.session import get_session_factory
        from frr.db.models import Region, ReportFormat, ReportJob

        now = datetime.now(timezone.utc)
        period_end = now.replace(day=1, hour=0, minute=0, second=0)
        period_start = (period_end - timedelta(days=1)).replace(day=1)

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            result = await session.execute(select(Region).where(Region.active.is_(True)))
            regions = result.scalars().all()

            for region in regions:
                job = ReportJob(
                    region_code=region.code,
                    report_format=ReportFormat.PDF,
                    period_start=period_start,
                    period_end=period_end,
                )
                session.add(job)
                await session.commit()
                await session.refresh(job)
                await generate_report(session, job)

            logger.info("Monthly reports generated", count=len(regions))
    except Exception as e:
        logger.error("Monthly report generation failed", error=str(e))
