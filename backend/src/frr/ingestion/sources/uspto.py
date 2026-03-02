"""USPTO PatentsView ingestion client.

Source: USPTO / PatentsView APIs
Layer: patent_activity

Produces monthly patent momentum signals:
- USPTO_PATENT_APPLICATIONS
- USPTO_PATENT_GRANTS
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

# MVP approximation: map all US patent throughput initially to EAST_ASIA + EU + LATAM
REGION_WEIGHTS: dict[str, float] = {
    "EAST_ASIA": 0.45,
    "EU": 0.35,
    "LATAM": 0.20,
}


class USPTOClient(BaseSourceClient):
    SOURCE_NAME = "USPTO_PATENTSVIEW"
    LAYER = SignalLayer.PATENT_ACTIVITY

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()
        params = {
            "page": 1,
            "per_page": settings.ingestion_batch_size,
        }

        applications_data: dict = {}
        grants_data: dict = {}

        try:
            applications_data = await self._get(f"{settings.uspto_api_url}/patent/applications", params=params)
        except Exception:
            applications_data = {}

        try:
            grants_data = await self._get(f"{settings.uspto_api_url}/patent/grants", params=params)
        except Exception:
            grants_data = {}

        app_monthly = self._aggregate_monthly(applications_data, date_field="filing_date")
        grant_monthly = self._aggregate_monthly(grants_data, date_field="grant_date")

        for month_key in sorted(set(app_monthly.keys()) | set(grant_monthly.keys())):
            ts = datetime.fromisoformat(f"{month_key}-01")
            apps = float(app_monthly.get(month_key, 0))
            grants = float(grant_monthly.get(month_key, 0))

            for region_code, weight in REGION_WEIGHTS.items():
                yield SignalRecord(
                    region_code=region_code,
                    layer=self.LAYER,
                    source=self.SOURCE_NAME,
                    indicator="USPTO_PATENT_APPLICATIONS",
                    ts=ts,
                    value=apps * weight,
                    metadata={"allocation_weight": weight},
                )
                yield SignalRecord(
                    region_code=region_code,
                    layer=self.LAYER,
                    source=self.SOURCE_NAME,
                    indicator="USPTO_PATENT_GRANTS",
                    ts=ts,
                    value=grants * weight,
                    metadata={"allocation_weight": weight},
                )

    @staticmethod
    def _aggregate_monthly(payload: dict, date_field: str) -> dict[str, int]:
        items = payload.get("data", []) if isinstance(payload, dict) else []
        monthly: dict[str, int] = defaultdict(int)
        for item in items:
            raw = str(item.get(date_field, ""))
            if len(raw) >= 7:
                monthly[raw[:7]] += 1
        return dict(monthly)
