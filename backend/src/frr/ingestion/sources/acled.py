"""ACLED (Armed Conflict Location & Event Data) ingestion client.

Source: https://acleddata.com/
Layer: energy_conflict (political violence + protest events)

Pulls event counts aggregated by region & month for conflict intensity tracking.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

ACLED_BASE_URL = "https://api.acleddata.com/acled/read"

# ISO codes per MVP region for filtering
REGION_ISO_MAP: dict[str, list[str]] = {
    "EU": ["DEU", "FRA", "ITA", "ESP", "NLD", "POL", "ROU", "GRC"],
    "MENA": ["SAU", "IRQ", "SYR", "YEM", "LBY", "EGY", "IRN"],
    "EAST_ASIA": ["CHN", "JPN", "KOR", "TWN"],
    "SOUTH_ASIA": ["IND", "PAK", "BGD", "LKA", "AFG"],
    "LATAM": ["BRA", "MEX", "ARG", "COL", "VEN", "CHL"],
}


class ACLEDClient(BaseSourceClient):
    SOURCE_NAME = "ACLED"
    LAYER = SignalLayer.ENERGY_CONFLICT

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()
        if not settings.acled_api_key or not settings.acled_email:
            from structlog import get_logger

            get_logger().warning("ACLED credentials not configured — skipping")
            return

        for region_code, iso_list in REGION_ISO_MAP.items():
            params = {
                "key": settings.acled_api_key,
                "email": settings.acled_email,
                "iso": "|".join(str(c) for c in iso_list),
                "limit": settings.ingestion_batch_size,
                "fields": "event_date|event_type|fatalities|country",
            }

            try:
                data = await self._get(ACLED_BASE_URL, params=params)
                events = data.get("data", [])

                # Aggregate by month → event count & fatalities
                monthly_events: dict[str, int] = defaultdict(int)
                monthly_fatalities: dict[str, int] = defaultdict(int)

                for event in events:
                    month_key = event["event_date"][:7]  # YYYY-MM
                    monthly_events[month_key] += 1
                    monthly_fatalities[month_key] += int(event.get("fatalities", 0))

                for month_key, count in monthly_events.items():
                    ts = datetime.fromisoformat(f"{month_key}-01")
                    yield SignalRecord(
                        region_code=region_code,
                        layer=self.LAYER,
                        source=self.SOURCE_NAME,
                        indicator="CONFLICT_EVENT_COUNT",
                        ts=ts,
                        value=float(count),
                        metadata={"iso_codes": iso_list},
                    )
                    yield SignalRecord(
                        region_code=region_code,
                        layer=self.LAYER,
                        source=self.SOURCE_NAME,
                        indicator="CONFLICT_FATALITIES",
                        ts=ts,
                        value=float(monthly_fatalities[month_key]),
                        metadata={"iso_codes": iso_list},
                    )

            except Exception as e:
                from structlog import get_logger

                get_logger().error("ACLED fetch failed", region=region_code, error=str(e))
