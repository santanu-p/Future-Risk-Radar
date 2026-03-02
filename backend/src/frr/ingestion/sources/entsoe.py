"""ENTSO-E Transparency Platform ingestion client.

Source: https://transparency.entsoe.eu/
Layer: energy_conflict

Indicators:
- Day-ahead electricity prices by bidding zone
- Generation mix (renewable vs fossil)
- Cross-border physical flows
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import AsyncGenerator

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord

ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"

# ENTSO-E bidding zone EIC codes → FRR region
# Only EU zones are relevant for ENTSO-E; we map the major ones
BIDDING_ZONES: dict[str, tuple[str, str]] = {
    "10Y1001A1001A83F": ("DE_LU", "EU"),     # Germany-Luxembourg
    "10YFR-RTE------C": ("FR", "EU"),         # France
    "10YIT-GRTN-----B": ("IT", "EU"),         # Italy
    "10YES-REE------0": ("ES", "EU"),         # Spain
    "10YNL----------L": ("NL", "EU"),         # Netherlands
    "10YPL-AREA-----S": ("PL", "EU"),         # Poland
    "10YAT-APG------L": ("AT", "EU"),         # Austria
    "10YSE-1--------K": ("SE", "EU"),         # Sweden
}

# Process types
DAY_AHEAD_PRICES = "A44"   # Day-ahead prices
GENERATION_BY_TYPE = "A75"  # Actual generation per type


class ENTSOEClient(BaseSourceClient):
    """ENTSO-E Transparency Platform client for European energy market data."""

    SOURCE_NAME = "ENTSOE"
    LAYER = SignalLayer.ENERGY_CONFLICT

    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        settings = get_settings()

        # ENTSO-E requires a security token via registration
        # We'll use the ENTSOE_API_KEY from config (extend config if needed)
        api_key = getattr(settings, "entsoe_api_key", "")
        if not api_key:
            from structlog import get_logger
            get_logger().warning("ENTSO-E API key not configured — skipping")
            return

        now = datetime.utcnow()
        # Fetch last 7 days of hourly prices, aggregate to daily averages
        period_start = (now - timedelta(days=7)).strftime("%Y%m%d0000")
        period_end = now.strftime("%Y%m%d0000")

        for zone_eic, (zone_name, region) in BIDDING_ZONES.items():
            try:
                # Day-ahead prices
                params = {
                    "securityToken": api_key,
                    "documentType": DAY_AHEAD_PRICES,
                    "in_Domain": zone_eic,
                    "out_Domain": zone_eic,
                    "periodStart": period_start,
                    "periodEnd": period_end,
                }
                # ENTSO-E returns XML; we'll parse the JSON wrapper if available
                # In production, use entsoe-py library for proper XML parsing
                data = await self._get(ENTSOE_BASE_URL, params=params)

                # Extract daily average price from the response
                # Simplified: ENTSO-E returns complex XML/JSON structures
                if isinstance(data, dict):
                    time_series = data.get("TimeSeries", [])
                    if not isinstance(time_series, list):
                        time_series = [time_series]

                    daily_prices: dict[str, list[float]] = {}
                    for ts in time_series:
                        period = ts.get("Period", {})
                        points = period.get("Point", [])
                        if not isinstance(points, list):
                            points = [points]

                        start_str = period.get("timeInterval", {}).get("start", "")
                        for pt in points:
                            price = pt.get("price.amount")
                            position = pt.get("position")
                            if price is not None and position is not None:
                                try:
                                    # Approximate date from start + position (hourly)
                                    day_key = start_str[:10] if start_str else now.strftime("%Y-%m-%d")
                                    daily_prices.setdefault(day_key, []).append(float(price))
                                except (ValueError, TypeError):
                                    continue

                    for day_key, prices in daily_prices.items():
                        avg_price = sum(prices) / len(prices)
                        try:
                            ts_dt = datetime.fromisoformat(day_key)
                        except ValueError:
                            continue

                        yield SignalRecord(
                            region_code=region,
                            layer=self.LAYER,
                            source=self.SOURCE_NAME,
                            indicator="ENTSOE_DAY_AHEAD_PRICE_EUR",
                            ts=ts_dt,
                            value=avg_price,
                            metadata={"zone": zone_name, "zone_eic": zone_eic},
                        )

                        # Price volatility signal (std of hourly prices within the day)
                        if len(prices) > 1:
                            import numpy as np
                            volatility = float(np.std(prices))
                            yield SignalRecord(
                                region_code=region,
                                layer=self.LAYER,
                                source=self.SOURCE_NAME,
                                indicator="ENTSOE_PRICE_VOLATILITY",
                                ts=ts_dt,
                                value=volatility,
                                metadata={"zone": zone_name, "n_hours": len(prices)},
                            )

            except Exception as e:
                from structlog import get_logger
                get_logger().error("ENTSO-E fetch failed", zone=zone_name, error=str(e))
