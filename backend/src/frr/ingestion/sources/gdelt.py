"""GDELT ingestion client.

Source: GDELT DOC API
Layer: energy_conflict

Produces weak-signal intensity indicators:
- GDELT_RISK_ARTICLE_COUNT
- GDELT_AVG_SENTIMENT
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

REGION_QUERIES = {
    "EU": "(europe OR eurozone) (energy crisis OR sanctions OR supply chain)",
    "MENA": "(middle east OR north africa) (oil shock OR conflict OR unrest)",
    "EAST_ASIA": "(east asia OR china OR japan OR korea) (semiconductor OR trade tension)",
    "SOUTH_ASIA": "(south asia OR india OR pakistan OR sri lanka) (inflation OR debt crisis)",
    "LATAM": "(latin america OR brazil OR argentina OR mexico) (currency crisis OR debt)",
}


class GDELTClient(BaseSourceClient):
    SOURCE_NAME = "GDELT"
    LAYER = SignalLayer.ENERGY_CONFLICT

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()

        now = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1)

        for region_code, query in REGION_QUERIES.items():
            params = {
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 250,
                "sort": "DateDesc",
            }
            try:
                data = await self._get(settings.gdelt_api_url, params=params)
            except Exception:
                data = {}

            articles = data.get("articles", []) if isinstance(data, dict) else []
            count = float(len(articles))

            # DOC API doesn't consistently expose per-article tone across mirrors.
            avg_sentiment = 0.0

            yield SignalRecord(
                region_code=region_code,
                layer=self.LAYER,
                source=self.SOURCE_NAME,
                indicator="GDELT_RISK_ARTICLE_COUNT",
                ts=month_start,
                value=count,
                metadata={"query": query},
            )
            yield SignalRecord(
                region_code=region_code,
                layer=self.LAYER,
                source=self.SOURCE_NAME,
                indicator="GDELT_AVG_SENTIMENT",
                ts=month_start,
                value=avg_sentiment,
                metadata={"query": query},
            )
