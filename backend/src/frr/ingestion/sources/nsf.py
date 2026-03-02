"""NSF Awards ingestion client.

Source: NSF Awards API
Layer: research_funding

Tracks monthly research funding momentum:
- NSF_AWARD_COUNT
- NSF_AWARD_TOTAL_USD
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

# Mapping institution/country exposure to MVP regions is refined later.
REGION_DEFAULT = "EAST_ASIA"


class NSFClient(BaseSourceClient):
    SOURCE_NAME = "NSF_AWARDS"
    LAYER = SignalLayer.RESEARCH_FUNDING

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()
        params = {
            "offset": 1,
            "printFields": "date,estimatedTotalAmt,agency,awardeeName,piFirstName,piLastName",
            "rpp": settings.ingestion_batch_size,
        }

        try:
            data = await self._get(settings.nsf_api_url, params=params)
        except Exception:
            data = {}

        awards = data.get("response", {}).get("award", []) if isinstance(data, dict) else []
        monthly_count: dict[str, int] = defaultdict(int)
        monthly_amount: dict[str, float] = defaultdict(float)

        for award in awards:
            date_raw = str(award.get("date", ""))
            if len(date_raw) < 7:
                continue
            if "-" in date_raw:
                month_key = date_raw[:7]
            elif len(date_raw) == 8:
                month_key = f"{date_raw[0:4]}-{date_raw[4:6]}"
            else:
                continue

            monthly_count[month_key] += 1
            monthly_amount[month_key] += float(award.get("estimatedTotalAmt", 0) or 0)

        for month_key, count in monthly_count.items():
            ts = datetime.fromisoformat(f"{month_key}-01")
            yield SignalRecord(
                region_code=REGION_DEFAULT,
                layer=self.LAYER,
                source=self.SOURCE_NAME,
                indicator="NSF_AWARD_COUNT",
                ts=ts,
                value=float(count),
                metadata={"source": "NSF Awards API"},
            )
            yield SignalRecord(
                region_code=REGION_DEFAULT,
                layer=self.LAYER,
                source=self.SOURCE_NAME,
                indicator="NSF_AWARD_TOTAL_USD",
                ts=ts,
                value=float(monthly_amount[month_key]),
                metadata={"source": "NSF Awards API"},
            )
