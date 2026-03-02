"""Freightos Baltic Index (FBX) ingestion client.

Source: https://fbx.freightos.com/
Layer: supply_chain

Indicators:
- Container shipping rates by major trade route
- Composite global container freight index
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

# Freightos does not have a fully free REST API.
# We use the FRED-hosted FBX composite index as a proxy.
# Production: use Freightos Enterprise API for route-level granularity.
FRED_FBX_URL = "https://api.stlouisfed.org/fred/series/observations"

# FBX route indices mapped to affected regions
FREIGHT_ROUTES: list[tuple[str, str, str]] = [
    # (FRED series / proxy identifier, indicator_name, primary_affected_region)
    ("FBX01", "FBX_CHINA_US_WEST_COAST", "EAST_ASIA"),
    ("FBX03", "FBX_CHINA_EUROPE", "EU"),
    ("FBX11", "FBX_EUROPE_US_EAST_COAST", "EU"),
    ("FBX_GLOBAL", "FBX_GLOBAL_COMPOSITE", "EAST_ASIA"),
]


class FreightosClient(BaseSourceClient):
    """Freightos Baltic Index client for container shipping rate trends.

    Uses FRED as data proxy for the global composite. In production,
    integrate with the Freightos Enterprise API for per-route data.
    """

    SOURCE_NAME = "FREIGHTOS"
    LAYER = SignalLayer.SUPPLY_CHAIN

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()

        # Strategy: fetch FRED-based freight proxy series
        # PCU483111483111 = Producer Price Index: Deep Sea Freight
        fred_series = [
            ("PCU483111483111", "FREIGHT_PPI_DEEPSEA", "EAST_ASIA"),
            ("WPUSI012011", "FREIGHT_IMPORT_PRICE_INDEX", "EU"),
        ]

        if not settings.fred_api_key:
            from structlog import get_logger
            get_logger().warning("FRED API key not set — Freightos proxy series unavailable")
            return

        for series_id, indicator, region in fred_series:
            try:
                params = {
                    "series_id": series_id,
                    "api_key": settings.fred_api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 60,  # ~5 years monthly
                }
                data = await self._get(FRED_FBX_URL, params=params)

                for obs in data.get("observations", []):
                    val = obs.get("value", ".")
                    if val == ".":
                        continue
                    yield SignalRecord(
                        region_code=region,
                        layer=self.LAYER,
                        source=self.SOURCE_NAME,
                        indicator=indicator,
                        ts=datetime.fromisoformat(obs["date"]),
                        value=float(val),
                        metadata={"fred_series": series_id},
                    )

                # Propagate to other affected regions with attenuation
                for dest_region in ["MENA", "SOUTH_ASIA", "LATAM"]:
                    for obs in data.get("observations", []):
                        val = obs.get("value", ".")
                        if val == ".":
                            continue
                        yield SignalRecord(
                            region_code=dest_region,
                            layer=self.LAYER,
                            source=self.SOURCE_NAME,
                            indicator=f"{indicator}_SPILLOVER",
                            ts=datetime.fromisoformat(obs["date"]),
                            value=float(val) * 0.6,  # attenuation factor
                            metadata={"fred_series": series_id, "spillover": True},
                        )

            except Exception as e:
                from structlog import get_logger
                get_logger().error("Freightos fetch failed", series=series_id, error=str(e))
