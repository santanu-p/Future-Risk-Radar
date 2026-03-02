"""WTO Integrated Trade Intelligence Portal (I-TIP) ingestion client.

Source: https://www.wto.org/english/res_e/statis_e/itip_e.htm
Layer: supply_chain

Indicators:
- Trade restriction count (SPS/TBT barriers)
- Tariff change events
- Export restrictions and subsidies
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

WTO_BASE_URL = "https://api.wto.org/timeseries/v1"

# WTO indicator codes for trade policy monitoring
WTO_INDICATORS: list[tuple[str, str, str]] = [
    # (indicator_code, frr_indicator_name, description)
    ("HS_M_0010", "WTO_IMPORT_TARIFF_AVG", "Average applied MFN tariff"),
    ("TP_A_0010", "WTO_TRADE_POLICY_MEASURES", "New trade policy measures count"),
]

# WTO reporter codes → FRR regions
REPORTER_REGION_MAP: dict[str, str] = {
    "918": "EU",        # European Union (28/27)
    "682": "MENA",      # Saudi Arabia
    "156": "EAST_ASIA",  # China
    "392": "EAST_ASIA",  # Japan
    "410": "EAST_ASIA",  # Korea
    "356": "SOUTH_ASIA",  # India
    "586": "SOUTH_ASIA",  # Pakistan
    "076": "LATAM",      # Brazil
    "484": "LATAM",      # Mexico
    "032": "LATAM",      # Argentina
}


class WTOClient(BaseSourceClient):
    """WTO I-TIP client for trade restriction and tariff data."""

    SOURCE_NAME = "WTO"
    LAYER = SignalLayer.SUPPLY_CHAIN

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()
        current_year = datetime.utcnow().year

        for reporter_code, region in REPORTER_REGION_MAP.items():
            for indicator_code, indicator_name, desc in WTO_INDICATORS:
                try:
                    params = {
                        "i": indicator_code,
                        "r": reporter_code,
                        "ps": f"{current_year - 2}-{current_year}",
                        "fmt": "json",
                        "mode": "full",
                        "lang": "1",
                    }
                    data = await self._get(f"{WTO_BASE_URL}/data", params=params)

                    dataset = data if isinstance(data, list) else data.get("Dataset", [])
                    for row in dataset:
                        year = row.get("Year") or row.get("year")
                        value = row.get("Value") or row.get("value")
                        if year is None or value is None:
                            continue

                        try:
                            ts = datetime(int(year), 6, 1)  # mid-year for annual data
                            val = float(value)
                        except (ValueError, TypeError):
                            continue

                        yield SignalRecord(
                            region_code=region,
                            layer=self.LAYER,
                            source=self.SOURCE_NAME,
                            indicator=indicator_name,
                            ts=ts,
                            value=val,
                            metadata={
                                "reporter_code": reporter_code,
                                "wto_indicator": indicator_code,
                                "description": desc,
                            },
                        )

                except Exception as e:
                    from structlog import get_logger
                    get_logger().error(
                        "WTO fetch failed",
                        reporter=reporter_code,
                        indicator=indicator_code,
                        error=str(e),
                    )
