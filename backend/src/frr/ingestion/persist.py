"""Persist ingested signal records into the database."""

from __future__ import annotations

import uuid
from datetime import timezone

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from frr.db.models import Region, SignalSeries
from frr.db.session import get_session_factory
from frr.ingestion.base import SignalRecord

logger = structlog.get_logger(__name__)


async def persist_signals(records: list[SignalRecord]) -> int:
    """Upsert signal records into the database.

    Uses PostgreSQL ``ON CONFLICT DO UPDATE`` to avoid duplicates on the
    natural key ``(region_id, source, indicator, ts)``.
    """
    factory = get_session_factory()
    async with factory() as session:
        # Preload region mapping
        result = await session.execute(select(Region))
        region_map = {r.code: r.id for r in result.scalars().all()}

        persisted = 0
        for record in records:
            region_id = region_map.get(record.region_code)
            if region_id is None:
                logger.warning("Unknown region — skipping", region=record.region_code, source=record.source)
                continue

            stmt = pg_insert(SignalSeries).values(
                id=uuid.uuid4(),
                region_id=region_id,
                layer=record.layer,
                source=record.source,
                indicator=record.indicator,
                ts=record.ts.replace(tzinfo=timezone.utc) if record.ts.tzinfo is None else record.ts,
                value=record.value,
                metadata_=record.metadata,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_signal_natural_key",
                set_={"value": stmt.excluded.value, "metadata_": stmt.excluded.metadata_},
            )
            await session.execute(stmt)
            persisted += 1

        await session.commit()
        return persisted
