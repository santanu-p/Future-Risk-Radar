"""EIA (Energy Information Administration) ingestion client.

Source: https://www.eia.gov/opendata/
Layer: energy_conflict

Indicators:
- Brent crude spot price
- WTI crude spot price
- Natural gas Henry Hub
- Global petroleum inventory
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

EIA_BASE_URL = "https://api.eia.gov/v2"

# (route, indicator_name, facets, region)
EIA_SERIES: list[tuple[str, str, dict, str]] = [
    (
        "/petroleum/pri/spt/data/",
        "BRENT_CRUDE_SPOT",
        {"product": "EPCBRENT", "duoarea": "Y35NY"},
        "MENA",
    ),
    (
        "/petroleum/pri/spt/data/",
        "WTI_CRUDE_SPOT",
        {"product": "EPCWTI", "duoarea": "Y35NY"},
        "LATAM",
    ),
    (
        "/natural-gas/pri/sum/data/",
        "NG_HENRY_HUB",
        {"process": "PRS", "duoarea": "SUS"},
        "EU",
    ),
]


class EIAClient(BaseSourceClient):
    SOURCE_NAME = "EIA"
    LAYER = SignalLayer.ENERGY_CONFLICT

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()
        if not settings.eia_api_key:
            from structlog import get_logger

            get_logger().warning("EIA API key not configured — skipping")
            return

        for route, indicator, facets, region in EIA_SERIES:
            params = {
                "api_key": settings.eia_api_key,
                "frequency": "monthly",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": settings.ingestion_batch_size,
            }
            for k, v in facets.items():
                params[f"facets[{k}][]"] = v

            try:
                data = await self._get(f"{EIA_BASE_URL}{route}", params=params)
                for row in data.get("response", {}).get("data", []):
                    value = row.get("value")
                    if value is None:
                        continue
                    yield SignalRecord(
                        region_code=region,
                        layer=self.LAYER,
                        source=self.SOURCE_NAME,
                        indicator=indicator,
                        ts=datetime.fromisoformat(row["period"] + "-01") if len(row["period"]) == 7 else datetime.fromisoformat(row["period"]),
                        value=float(value),
                        metadata={"route": route, "facets": facets},
                    )
            except Exception as e:
                from structlog import get_logger

                get_logger().error("EIA fetch failed", indicator=indicator, error=str(e))
