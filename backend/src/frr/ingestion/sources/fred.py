"""FRED (Federal Reserve Economic Data) ingestion client.

Source: https://fred.stlouisfed.org/docs/api/
Layer: research_funding (economic fundamentals that proxy research investment climate)

Indicators pulled:
- GDP growth (real, quarterly)
- Unemployment rate
- CPI inflation
- Federal funds rate
- Yield curve (10Y - 2Y)
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

# FRED series → (indicator_name, region_code)
FRED_SERIES: list[tuple[str, str, str]] = [
    ("A191RL1Q225SBEA", "GDP_GROWTH_REAL", "EU"),        # Proxy — replace with Eurostat
    ("UNRATE", "UNEMPLOYMENT_RATE", "EU"),
    ("CPIAUCSL", "CPI_INDEX", "EU"),
    ("DFF", "FED_FUNDS_RATE", "EU"),
    ("T10Y2Y", "YIELD_CURVE_10Y_2Y", "EU"),
]

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


class FREDClient(BaseSourceClient):
    SOURCE_NAME = "FRED"
    LAYER = SignalLayer.RESEARCH_FUNDING

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()
        if not settings.fred_api_key:
            self._log_skip()
            return

        for series_id, indicator, region in FRED_SERIES:
            params = {
                "series_id": series_id,
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": settings.ingestion_batch_size,
            }

            try:
                data = await self._get(FRED_BASE_URL, params=params)
                for obs in data.get("observations", []):
                    if obs["value"] == ".":
                        continue  # FRED uses "." for missing values
                    yield SignalRecord(
                        region_code=region,
                        layer=self.LAYER,
                        source=self.SOURCE_NAME,
                        indicator=indicator,
                        ts=datetime.fromisoformat(obs["date"]),
                        value=float(obs["value"]),
                        metadata={"series_id": series_id},
                    )
            except Exception as e:
                self._logger.error("FRED fetch failed", series=series_id, error=str(e))

    def _log_skip(self) -> None:
        from structlog import get_logger

        get_logger().warning("FRED API key not configured — skipping")

    @property
    def _logger(self):
        from structlog import get_logger

        return get_logger(__name__)
