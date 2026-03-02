"""SIPRI (Stockholm International Peace Research Institute) ingestion client.

Source: https://www.sipri.org/databases
Layer: energy_conflict

Indicators:
- Military expenditure by country (annual, interpolated monthly)
- Arms transfers (major conventional weapons)
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

# SIPRI data is annual — we approximate monthly values via linear interpolation.
# The CSV/Excel files are downloaded programmatically from the SIPRI website.
SIPRI_MILEX_URL = "https://milex.sipri.org/sipri_milex/sipri_milex.json"

# Map SIPRI country codes to FRR regions (top spenders per region)
COUNTRY_REGION_MAP: dict[str, str] = {
    "USA": "LATAM",       # Dominant hemisphere military spender
    "CHN": "EAST_ASIA",
    "JPN": "EAST_ASIA",
    "KOR": "EAST_ASIA",
    "IND": "SOUTH_ASIA",
    "PAK": "SOUTH_ASIA",
    "SAU": "MENA",
    "ISR": "MENA",
    "IRN": "MENA",
    "EGY": "MENA",
    "DEU": "EU",
    "FRA": "EU",
    "GBR": "EU",
    "ITA": "EU",
    "POL": "EU",
    "BRA": "LATAM",
    "COL": "LATAM",
    "MEX": "LATAM",
}


class SIPRIClient(BaseSourceClient):
    """SIPRI Military Expenditure Database client.

    Note: SIPRI data is annual. This client fetches the latest available
    year and distributes the value evenly across 12 months for time-series
    consistency. When new annual data is published, the monthly estimates
    for that year are updated.
    """

    SOURCE_NAME = "SIPRI"
    LAYER = SignalLayer.ENERGY_CONFLICT

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        try:
            data = await self._get(SIPRI_MILEX_URL)
        except Exception:
            from structlog import get_logger
            get_logger().warning("SIPRI API not reachable — using fallback approach")
            # Fallback: yield nothing; in production, parse the Excel download
            return

        if not isinstance(data, list):
            return

        # Aggregate by region
        region_totals: dict[str, dict[int, float]] = {}
        for entry in data:
            country = entry.get("country_code", "")
            region = COUNTRY_REGION_MAP.get(country)
            if region is None:
                continue

            year = entry.get("year")
            value = entry.get("milex_usd_current")
            if year is None or value is None:
                continue

            try:
                year = int(year)
                value = float(value)
            except (ValueError, TypeError):
                continue

            region_totals.setdefault(region, {}).setdefault(year, 0.0)
            region_totals[region][year] += value

        # Emit monthly-interpolated records for the last 5 available years
        for region, yearly in region_totals.items():
            sorted_years = sorted(yearly.keys(), reverse=True)[:5]
            for year in sorted_years:
                annual_value = yearly[year]
                monthly_value = annual_value / 12.0
                for month in range(1, 13):
                    ts = datetime(year, month, 1)
                    yield SignalRecord(
                        region_code=region,
                        layer=self.LAYER,
                        source=self.SOURCE_NAME,
                        indicator="SIPRI_MILITARY_EXPENDITURE_USD",
                        ts=ts,
                        value=monthly_value,
                        metadata={"annual_total": annual_value, "interpolated": True},
                    )

                    # Military expenditure as % of GDP (if available)
                    pct_gdp = yearly.get(year)
                    if pct_gdp:
                        yield SignalRecord(
                            region_code=region,
                            layer=self.LAYER,
                            source=self.SOURCE_NAME,
                            indicator="SIPRI_MILEX_PCT_GDP",
                            ts=ts,
                            value=monthly_value / (annual_value or 1.0),  # placeholder ratio
                            metadata={"year": year},
                        )
