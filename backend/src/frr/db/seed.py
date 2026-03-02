"""Seed data — MVP regions and initial crisis labels for back-testing."""

from __future__ import annotations

import asyncio
import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog

from frr.config import PROJECT_ROOT
from frr.db.models import CrisisLabel, CrisisType, Region
from frr.db.session import get_session_factory, init_db

logger = structlog.get_logger(__name__)

CRISIS_LABELS_CSV = PROJECT_ROOT / "data" / "historical_crisis_labels.csv"

# ── MVP Regions ────────────────────────────────────────────────────────
MVP_REGIONS: list[dict] = [
    {
        "code": "EU",
        "name": "European Union",
        "centroid_lat": 50.1,
        "centroid_lon": 9.7,
        "iso_codes": {
            "members": [
                "DE", "FR", "IT", "ES", "NL", "BE", "AT", "PL", "SE",
                "FI", "DK", "IE", "PT", "GR", "CZ", "RO", "HU", "BG",
                "HR", "SK", "SI", "LT", "LV", "EE", "LU", "MT", "CY",
            ]
        },
        "description": "EU-27 economic bloc — world's largest single market",
    },
    {
        "code": "MENA",
        "name": "Middle East & North Africa",
        "centroid_lat": 29.0,
        "centroid_lon": 41.0,
        "iso_codes": {
            "members": [
                "SA", "AE", "QA", "KW", "BH", "OM", "IR", "IQ", "SY",
                "JO", "LB", "IL", "PS", "EG", "LY", "TN", "DZ", "MA",
                "YE",
            ]
        },
        "description": "Energy-rich region — geopolitical hotspot",
    },
    {
        "code": "EAST_ASIA",
        "name": "East Asia",
        "centroid_lat": 35.0,
        "centroid_lon": 120.0,
        "iso_codes": {
            "members": ["CN", "JP", "KR", "TW", "HK", "MO", "MN"]
        },
        "description": "Global manufacturing & technology hub — semiconductor supply chain epicentre",
    },
    {
        "code": "SOUTH_ASIA",
        "name": "South Asia",
        "centroid_lat": 23.0,
        "centroid_lon": 80.0,
        "iso_codes": {
            "members": ["IN", "PK", "BD", "LK", "NP", "BT", "MV", "AF"]
        },
        "description": "1.9B+ population — emerging technology & demographic dividend",
    },
    {
        "code": "LATAM",
        "name": "Latin America",
        "centroid_lat": -15.0,
        "centroid_lon": -60.0,
        "iso_codes": {
            "members": [
                "BR", "MX", "AR", "CO", "CL", "PE", "EC", "VE", "BO",
                "PY", "UY", "CR", "PA", "DO", "GT", "HN", "SV", "NI",
                "CU",
            ]
        },
        "description": "Resource-rich, currency-volatile — commodity cycle exposure",
    },
]


# ── Historical Crisis Labels (for training) ───────────────────────────
def _parse_crisis_type(raw: str) -> CrisisType:
    return CrisisType(raw.strip().lower())


def load_historical_crises(csv_path: Path = CRISIS_LABELS_CSV) -> list[dict]:
    """Load historical crisis labels from CSV.

    Expected columns:
    - region
    - crisis_type
    - event_date (YYYY-MM-DD)
    - source
    - notes (optional)
    - severity (optional float)
    """
    if not csv_path.exists():
        logger.warning("Historical crisis CSV not found", path=str(csv_path))
        return []

    records: list[dict] = []
    with csv_path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            try:
                records.append(
                    {
                        "region": (row.get("region") or "").strip().upper(),
                        "type": _parse_crisis_type(row.get("crisis_type") or ""),
                        "date": (row.get("event_date") or "").strip(),
                        "source": (row.get("source") or "unknown").strip(),
                        "notes": (row.get("notes") or "").strip() or None,
                        "severity": float(row.get("severity") or 1.0),
                    }
                )
            except Exception as exc:
                logger.warning("Skipping malformed crisis label row", row=row, error=str(exc))

    logger.info("Loaded historical crisis labels", count=len(records), path=str(csv_path))
    return records


async def seed_regions() -> None:
    """Insert MVP regions if they don't already exist."""
    factory = get_session_factory()
    async with factory() as session:
        for data in MVP_REGIONS:
            from sqlalchemy import select

            existing = await session.execute(
                select(Region).where(Region.code == data["code"])
            )
            if existing.scalar_one_or_none() is None:
                session.add(Region(id=uuid.uuid4(), **data))
                logger.info("Seeded region", code=data["code"])
        await session.commit()


async def seed_crisis_labels() -> None:
    """Insert historical crisis labels for model training."""
    historical_crises = load_historical_crises()
    if not historical_crises:
        logger.warning("No historical crisis labels loaded; skipping crisis seeding")
        return

    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import select

        regions = {r.code: r.id for r in (await session.execute(select(Region))).scalars().all()}

        inserted = 0
        for crisis in historical_crises:
            region_id = regions.get(crisis["region"])
            if region_id is None:
                continue

            existing = await session.execute(
                select(CrisisLabel).where(
                    CrisisLabel.region_id == region_id,
                    CrisisLabel.crisis_type == crisis["type"],
                    CrisisLabel.event_date == datetime.fromisoformat(crisis["date"]).replace(tzinfo=timezone.utc),
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            label = CrisisLabel(
                id=uuid.uuid4(),
                region_id=region_id,
                crisis_type=crisis["type"],
                event_date=datetime.fromisoformat(crisis["date"]).replace(tzinfo=timezone.utc),
                source=crisis["source"],
                notes=crisis.get("notes"),
                severity=crisis.get("severity", 1.0),
            )
            session.add(label)
            inserted += 1
            logger.info("Seeded crisis label", region=crisis["region"], type=crisis["type"].value)
        await session.commit()
        logger.info("Crisis label seeding completed", inserted=inserted)


async def run_seed() -> None:
    await init_db()
    await seed_regions()
    await seed_crisis_labels()
    logger.info("Seeding complete")


if __name__ == "__main__":
    asyncio.run(run_seed())
