"""WIPO PATENTSCOPE API ingestion client.

Source: https://patentscope.wipo.int/
Layer: patent_activity

Indicators:
- International patent filings (PCT) by jurisdiction
- IPC class distribution for strategic technology sectors
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

WIPO_BASE_URL = "https://patentscope.wipo.int/search/rest/v1"

# IPC classes of strategic interest (dual-use / structural)
STRATEGIC_IPC_CLASSES: dict[str, str] = {
    "H01L": "Semiconductors",
    "G06N": "AI/ML Computing",
    "H02J": "Energy Distribution",
    "C12N": "Biotech/Genetic Engineering",
    "G21B": "Nuclear Fusion",
    "B64G": "Space Technology",
}

# Map WIPO offices to FRR regions
OFFICE_REGION_MAP: dict[str, str] = {
    "EP": "EU",
    "WO": "EU",  # PCT international phase — EU as primary
    "US": "EAST_ASIA",  # US filings globally linked to East Asia supply chains
    "CN": "EAST_ASIA",
    "JP": "EAST_ASIA",
    "KR": "EAST_ASIA",
    "IN": "SOUTH_ASIA",
    "BR": "LATAM",
    "MX": "LATAM",
    "SA": "MENA",
    "EG": "MENA",
}


class WIPOClient(BaseSourceClient):
    """WIPO PATENTSCOPE client for international patent filing trends."""

    SOURCE_NAME = "WIPO"
    LAYER = SignalLayer.PATENT_ACTIVITY

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        """Fetch PCT filing counts by office and IPC class.

        Note: WIPO does not have a freely queryable REST API with full
        parametric access. This client uses the public search endpoint
        to approximate filing volumes. In production, replace with WIPO
        IP Statistics Data Center bulk download or SOAP API.
        """
        settings = get_settings()

        for office, region in OFFICE_REGION_MAP.items():
            try:
                params = {
                    "q": f"DP:{office}",
                    "s": "num_results",
                    "range": "last_12_months",
                }
                data = await self._get(f"{WIPO_BASE_URL}/search", params=params)

                total_filings = data.get("totalResults", 0) if isinstance(data, dict) else 0
                now = datetime.utcnow().replace(day=1)

                yield SignalRecord(
                    region_code=region,
                    layer=self.LAYER,
                    source=self.SOURCE_NAME,
                    indicator="WIPO_PCT_FILINGS",
                    ts=now,
                    value=float(total_filings),
                    metadata={"office": office},
                )

                # Strategic IPC class breakdown
                for ipc, desc in STRATEGIC_IPC_CLASSES.items():
                    ipc_params = {
                        "q": f"DP:{office} AND IC:{ipc}",
                        "s": "num_results",
                        "range": "last_12_months",
                    }
                    ipc_data = await self._get(f"{WIPO_BASE_URL}/search", params=ipc_params)
                    ipc_count = ipc_data.get("totalResults", 0) if isinstance(ipc_data, dict) else 0

                    if ipc_count > 0:
                        yield SignalRecord(
                            region_code=region,
                            layer=self.LAYER,
                            source=self.SOURCE_NAME,
                            indicator=f"WIPO_PCT_{ipc.replace('.', '_')}",
                            ts=now,
                            value=float(ipc_count),
                            metadata={"office": office, "ipc_class": ipc, "description": desc},
                        )

            except Exception as e:
                from structlog import get_logger
                get_logger().error("WIPO fetch failed", office=office, error=str(e))
