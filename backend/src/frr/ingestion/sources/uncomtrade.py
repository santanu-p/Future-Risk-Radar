"""UN Comtrade ingestion client.

Source: UN Comtrade API
Layer: supply_chain

Computes monthly trade stress proxies:
- UNCOMTRADE_IMPORT_VALUE
- UNCOMTRADE_EXPORT_VALUE
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

REPORTER_BY_REGION = {
    "EU": ["276", "250", "380", "724"],
    "MENA": ["682", "818", "364", "368"],
    "EAST_ASIA": ["156", "392", "410"],
    "SOUTH_ASIA": ["356", "586", "050", "144"],
    "LATAM": ["076", "484", "032", "170"],
}


class UNComtradeClient(BaseSourceClient):
    SOURCE_NAME = "UN_COMTRADE"
    LAYER = SignalLayer.SUPPLY_CHAIN

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()

        for region_code, reporters in REPORTER_BY_REGION.items():
            params = {
                "frequency": "M",
                "reporterCode": ",".join(reporters),
                "maxRecords": settings.ingestion_batch_size,
            }
            try:
                data = await self._get(f"{settings.uncomtrade_api_url}/preview/C/A/HS", params=params)
            except Exception:
                data = {}

            rows = data.get("data", []) if isinstance(data, dict) else []
            monthly_imports: dict[str, float] = defaultdict(float)
            monthly_exports: dict[str, float] = defaultdict(float)

            for row in rows:
                period = str(row.get("period", ""))
                if len(period) == 6 and period.isdigit():
                    month_key = f"{period[:4]}-{period[4:6]}"
                else:
                    month_key = period[:7]
                if len(month_key) < 7:
                    continue

                flow = str(row.get("flowDesc", "")).lower()
                value = float(row.get("primaryValue", 0) or 0)
                if "import" in flow:
                    monthly_imports[month_key] += value
                elif "export" in flow:
                    monthly_exports[month_key] += value

            for month_key in sorted(set(monthly_imports.keys()) | set(monthly_exports.keys())):
                ts = datetime.fromisoformat(f"{month_key}-01")
                yield SignalRecord(
                    region_code=region_code,
                    layer=self.LAYER,
                    source=self.SOURCE_NAME,
                    indicator="UNCOMTRADE_IMPORT_VALUE",
                    ts=ts,
                    value=float(monthly_imports.get(month_key, 0.0)),
                    metadata={"reporters": reporters},
                )
                yield SignalRecord(
                    region_code=region_code,
                    layer=self.LAYER,
                    source=self.SOURCE_NAME,
                    indicator="UNCOMTRADE_EXPORT_VALUE",
                    ts=ts,
                    value=float(monthly_exports.get(month_key, 0.0)),
                    metadata={"reporters": reporters},
                )
