"""EPO Open Patent Services ingestion client.

Source: https://developers.epo.org/
Layer: patent_activity

Indicators:
- European patent applications by country
- Opposition proceedings (signal of strategic patent conflict)
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

EPO_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_BASE_URL = "https://ops.epo.org/3.2/rest-services"

# Map EPO country codes to FRR regions
COUNTRY_REGION_MAP: dict[str, str] = {
    "DE": "EU", "FR": "EU", "GB": "EU", "IT": "EU", "ES": "EU",
    "NL": "EU", "SE": "EU", "CH": "EU", "AT": "EU", "BE": "EU",
    "CN": "EAST_ASIA", "JP": "EAST_ASIA", "KR": "EAST_ASIA",
    "IN": "SOUTH_ASIA",
    "BR": "LATAM", "MX": "LATAM",
    "SA": "MENA", "AE": "MENA", "IL": "MENA",
}


class EPOClient(BaseSourceClient):
    """EPO Open Patent Services client for European patent trends."""

    SOURCE_NAME = "EPO"
    LAYER = SignalLayer.PATENT_ACTIVITY

    _access_token: str | None = None

    async def _authenticate(self) -> None:
        """Obtain OAuth2 bearer token from EPO OPS."""
        settings = get_settings()
        if not settings.epo_consumer_key or not settings.epo_consumer_secret.get_secret_value():
            return

        credentials = base64.b64encode(
            f"{settings.epo_consumer_key}:{settings.epo_consumer_secret.get_secret_value()}".encode()
        ).decode()

        resp = await self.client.post(
            EPO_AUTH_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials",
        )
        if resp.status_code == 200:
            self._access_token = resp.json().get("access_token")

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()
        if not settings.epo_consumer_key:
            from structlog import get_logger
            get_logger().warning("EPO credentials not configured — skipping")
            return

        await self._authenticate()
        if not self._access_token:
            from structlog import get_logger
            get_logger().warning("EPO authentication failed — skipping")
            return

        headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}
        now = datetime.utcnow()
        current_year = now.year

        for country, region in COUNTRY_REGION_MAP.items():
            try:
                # Published applications search
                search_url = f"{EPO_BASE_URL}/published-data/search"
                params = {
                    "q": f"pa={country} and pd={current_year}",
                    "Range": "1-1",
                }
                resp = await self.client.get(search_url, params=params, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    total = 0
                    try:
                        total = int(
                            data.get("ops:world-patent-data", {})
                            .get("ops:biblio-search", {})
                            .get("@total-result-count", 0)
                        )
                    except (ValueError, TypeError):
                        pass

                    yield SignalRecord(
                        region_code=region,
                        layer=self.LAYER,
                        source=self.SOURCE_NAME,
                        indicator="EPO_PATENT_APPLICATIONS",
                        ts=now.replace(day=1),
                        value=float(total),
                        metadata={"country": country, "year": current_year},
                    )

            except Exception as e:
                from structlog import get_logger
                get_logger().error("EPO fetch failed", country=country, error=str(e))
