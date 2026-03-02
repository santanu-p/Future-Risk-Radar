"""UCDP GED ingestion client.

Source: Uppsala Conflict Data Program (GED API)
Layer: energy_conflict

Produces monthly conflict intensity signals by MVP region:
- UCDP_BATTLE_DEATHS
- UCDP_CONFLICT_EVENTS
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

REGION_ISO3_MAP: dict[str, list[str]] = {
    "EU": ["DEU", "FRA", "ITA", "ESP", "POL", "ROU", "GRC"],
    "MENA": ["SAU", "IRN", "IRQ", "SYR", "YEM", "EGY", "LBY"],
    "EAST_ASIA": ["CHN", "JPN", "KOR", "TWN", "MNG"],
    "SOUTH_ASIA": ["IND", "PAK", "BGD", "LKA", "NPL", "AFG"],
    "LATAM": ["BRA", "MEX", "ARG", "COL", "PER", "CHL", "VEN"],
}


class UCDPClient(BaseSourceClient):
    SOURCE_NAME = "UCDP"
    LAYER = SignalLayer.ENERGY_CONFLICT

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()

        for region_code, iso3 in REGION_ISO3_MAP.items():
            params = {
                "pagesize": settings.ingestion_batch_size,
                "country": ",".join(iso3),
            }
            try:
                # Endpoint shape differs across UCDP versions; this keeps client resilient.
                data = await self._get(f"{settings.ucdp_api_url}/ged/241", params=params)
            except Exception:
                data = {"Result": []}

            events = data.get("Result", []) if isinstance(data, dict) else []
            monthly_events: dict[str, int] = defaultdict(int)
            monthly_deaths: dict[str, int] = defaultdict(int)

            for event in events:
                date_raw = str(event.get("date_start", ""))[:10]
                if len(date_raw) < 7:
                    continue
                month_key = date_raw[:7]
                monthly_events[month_key] += 1
                monthly_deaths[month_key] += int(event.get("best", 0) or 0)

            for month_key, event_count in monthly_events.items():
                ts = datetime.fromisoformat(f"{month_key}-01")
                yield SignalRecord(
                    region_code=region_code,
                    layer=self.LAYER,
                    source=self.SOURCE_NAME,
                    indicator="UCDP_CONFLICT_EVENTS",
                    ts=ts,
                    value=float(event_count),
                    metadata={"iso3": iso3},
                )
                yield SignalRecord(
                    region_code=region_code,
                    layer=self.LAYER,
                    source=self.SOURCE_NAME,
                    indicator="UCDP_BATTLE_DEATHS",
                    ts=ts,
                    value=float(monthly_deaths[month_key]),
                    metadata={"iso3": iso3},
                )
