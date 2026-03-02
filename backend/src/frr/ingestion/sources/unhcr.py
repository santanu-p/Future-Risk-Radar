"""UNHCR Operational Data Portal ingestion client.

Source: https://data.unhcr.org/
Layer: energy_conflict (refugee flows as a conflict/instability indicator)

Indicators:
- Refugee population by country of asylum
- Asylum applications received
- Internally displaced persons (IDPs)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

UNHCR_BASE_URL = "https://data.unhcr.org/api/v2"

# UNHCR country codes → FRR regions
COUNTRY_REGION_MAP: dict[str, str] = {
    # EU
    "DEU": "EU", "FRA": "EU", "ITA": "EU", "ESP": "EU", "GRC": "EU",
    "POL": "EU", "SWE": "EU", "AUT": "EU", "NLD": "EU", "BEL": "EU",
    # MENA
    "TUR": "MENA", "JOR": "MENA", "LBN": "MENA", "IRQ": "MENA",
    "EGY": "MENA", "SAU": "MENA", "YEM": "MENA", "SYR": "MENA",
    "IRN": "MENA",
    # EAST_ASIA
    "CHN": "EAST_ASIA", "JPN": "EAST_ASIA", "KOR": "EAST_ASIA",
    "MYS": "EAST_ASIA", "THA": "EAST_ASIA", "MMR": "EAST_ASIA",
    # SOUTH_ASIA
    "IND": "SOUTH_ASIA", "PAK": "SOUTH_ASIA", "BGD": "SOUTH_ASIA",
    "AFG": "SOUTH_ASIA", "LKA": "SOUTH_ASIA", "NPL": "SOUTH_ASIA",
    # LATAM
    "COL": "LATAM", "BRA": "LATAM", "PER": "LATAM", "ECU": "LATAM",
    "MEX": "LATAM", "CHL": "LATAM", "VEN": "LATAM",
}


class UNHCRClient(BaseSourceClient):
    """UNHCR Operational Data Portal client for displacement data."""

    SOURCE_NAME = "UNHCR"
    LAYER = SignalLayer.ENERGY_CONFLICT

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        current_year = datetime.utcnow().year

        # Fetch population statistics
        try:
            data = await self._get(
                f"{UNHCR_BASE_URL}/population",
                params={
                    "yearFrom": current_year - 3,
                    "yearTo": current_year,
                    "limit": 1000,
                },
            )

            items = data.get("items", []) if isinstance(data, dict) else data if isinstance(data, list) else []

            # Aggregate by region and year
            region_yearly: dict[str, dict[int, dict[str, float]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(float))
            )

            for item in items:
                country = item.get("country_of_asylum_code") or item.get("coa_iso", "")
                region = COUNTRY_REGION_MAP.get(country)
                if region is None:
                    continue

                year = item.get("year")
                if year is None:
                    continue

                try:
                    year = int(year)
                except (ValueError, TypeError):
                    continue

                refugees = float(item.get("refugees", 0) or 0)
                asylum_seekers = float(item.get("asylum_seekers", 0) or 0)
                idps = float(item.get("idps", 0) or 0)

                region_yearly[region][year]["refugees"] += refugees
                region_yearly[region][year]["asylum_seekers"] += asylum_seekers
                region_yearly[region][year]["idps"] += idps

            # Emit records (monthly interpolation from annual data)
            for region, yearly_data in region_yearly.items():
                for year, metrics in yearly_data.items():
                    for month in range(1, 13):
                        ts = datetime(year, month, 1)

                        yield SignalRecord(
                            region_code=region,
                            layer=self.LAYER,
                            source=self.SOURCE_NAME,
                            indicator="UNHCR_REFUGEE_POPULATION",
                            ts=ts,
                            value=metrics["refugees"] / 12.0,
                            metadata={"annual_total": metrics["refugees"], "year": year},
                        )

                        yield SignalRecord(
                            region_code=region,
                            layer=self.LAYER,
                            source=self.SOURCE_NAME,
                            indicator="UNHCR_ASYLUM_SEEKERS",
                            ts=ts,
                            value=metrics["asylum_seekers"] / 12.0,
                            metadata={"annual_total": metrics["asylum_seekers"], "year": year},
                        )

                        if metrics["idps"] > 0:
                            yield SignalRecord(
                                region_code=region,
                                layer=self.LAYER,
                                source=self.SOURCE_NAME,
                                indicator="UNHCR_IDP_POPULATION",
                                ts=ts,
                                value=metrics["idps"] / 12.0,
                                metadata={"annual_total": metrics["idps"], "year": year},
                            )

        except Exception as e:
            from structlog import get_logger
            get_logger().error("UNHCR fetch failed", error=str(e))
