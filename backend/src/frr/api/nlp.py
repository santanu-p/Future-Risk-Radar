"""NLP / News API — trigger scans and view extracted signals."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query, status
from sqlalchemy import select, and_, func
from datetime import datetime, timedelta, timezone

from frr.api.deps import AdminUser, CurrentUser, DbSession
from frr.api.schemas import NLPScanResult, NewsSignalOut
from frr.db.models import SignalSeries
from frr.db.session import get_session_factory

router = APIRouter()


async def _run_nlp_scan_background() -> None:
    from frr.ingestion.sources.news_nlp import scan_and_ingest_news
    factory = get_session_factory()
    async with factory() as session:
        await scan_and_ingest_news(session)


@router.post("/nlp/scan", status_code=status.HTTP_202_ACCEPTED)
async def trigger_nlp_scan(background: BackgroundTasks, user: AdminUser) -> dict:
    """Trigger a manual GDELT/news NLP scan (admin only)."""
    background.add_task(_run_nlp_scan_background)
    return {"status": "accepted", "message": "NLP scan started in background"}


@router.get("/nlp/signals", response_model=list[NewsSignalOut])
async def list_nlp_signals(
    db: DbSession,
    user: CurrentUser,
    region_code: str | None = Query(None),
    category: str | None = Query(None, description="e.g. sanctions_risk, trade_dispute"),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    """List recent NLP-extracted news signals."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    query = (
        select(SignalSeries)
        .where(
            and_(
                SignalSeries.source == "GDELT_NLP",
                SignalSeries.ts >= cutoff,
            )
        )
        .order_by(SignalSeries.ts.desc())
    )

    if region_code:
        from frr.db.models import Region
        region_q = await db.execute(select(Region).where(Region.code == region_code.upper()))
        region = region_q.scalar_one_or_none()
        if region:
            query = query.where(SignalSeries.region_id == region.id)

    if category:
        query = query.where(SignalSeries.indicator == f"nlp_{category}")

    query = query.limit(limit)
    result = await db.execute(query)
    signals = result.scalars().all()

    return [
        {
            "title": s.metadata.get("title", ""),
            "source_url": s.metadata.get("url", ""),
            "region_code": region_code or "unknown",
            "classification": s.metadata.get("risk_category", ""),
            "confidence": s.metadata.get("confidence", 0),
            "sentiment": s.metadata.get("sentiment", 0),
            "published_at": s.ts,
            "processed_at": s.ingested_at,
        }
        for s in signals
    ]


@router.get("/nlp/summary")
async def nlp_summary(db: DbSession, user: CurrentUser, hours: int = Query(24, ge=1, le=168)) -> dict:
    """Summary of NLP signals in the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Count by category
    result = await db.execute(
        select(SignalSeries.indicator, func.count(SignalSeries.id))
        .where(
            and_(
                SignalSeries.source == "GDELT_NLP",
                SignalSeries.ts >= cutoff,
            )
        )
        .group_by(SignalSeries.indicator)
    )
    category_counts = {}
    total = 0
    for indicator, count in result.all():
        cat = indicator.replace("nlp_", "")
        category_counts[cat] = count
        total += count

    return {
        "period_hours": hours,
        "total_signals": total,
        "by_category": category_counts,
    }
