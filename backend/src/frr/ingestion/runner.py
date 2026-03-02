"""Ingestion runner — orchestrates a full ingestion cycle across all sources."""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select

from frr.db.models import Region
from frr.db.session import get_session_factory
from frr.ingestion.sources import ALL_SOURCES
from frr.models.anomaly import compute_anomaly_scores

logger = structlog.get_logger(__name__)


async def run_ingestion_cycle() -> dict[str, int]:
    """Run all source clients and return a summary of records ingested.

    Each source runs independently — failures in one source don't block others.
    """
    results: dict[str, int] = {}

    for source_cls in ALL_SOURCES:
        source_name = source_cls.SOURCE_NAME
        try:
            async with source_cls() as client:
                count = await client.ingest()
                results[source_name] = count
        except Exception as e:
            logger.error("Source ingestion failed", source=source_name, error=str(e))
            results[source_name] = -1  # -1 = error sentinel

    total = sum(v for v in results.values() if v >= 0)
    errors = sum(1 for v in results.values() if v < 0)

    # Run Layer 1 anomaly normalization after ingestion
    anomaly_count = await _run_anomaly_stage()

    logger.info(
        "Ingestion cycle summary",
        total_records=total,
        sources_ok=len(results) - errors,
        sources_failed=errors,
        anomaly_scores=anomaly_count,
        breakdown=results,
    )
    return results


async def run_single_source(source_name: str) -> int:
    """Run ingestion for a single named source (for debugging / manual triggers)."""
    for source_cls in ALL_SOURCES:
        if source_cls.SOURCE_NAME == source_name:
            async with source_cls() as client:
                return await client.ingest()

    raise ValueError(f"Unknown source: {source_name}. Available: {[s.SOURCE_NAME for s in ALL_SOURCES]}")


async def _run_anomaly_stage() -> int:
    """Compute per-signal z-score anomalies for all active regions."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Region).where(Region.active.is_(True)))
        regions = result.scalars().all()

        total = 0
        for region in regions:
            total += await compute_anomaly_scores(session, str(region.id))

    logger.info("Anomaly stage complete", total_scores=total, regions=len(regions))
    return total
