"""Tests for FRED ingestion source client."""

from __future__ import annotations

import httpx
import pytest
import respx

from frr.db.models import SignalLayer
from frr.ingestion.sources.fred import FRED_SERIES, FREDClient


class TestFREDClient:
    """FRED source client — economic indicators."""

    def test_source_name(self):
        assert FREDClient.SOURCE_NAME == "FRED"

    def test_layer(self):
        assert FREDClient.LAYER == SignalLayer.SUPPLY_CHAIN

    def test_series_config(self):
        """FRED should have at least 5 series defined."""
        assert len(FRED_SERIES) >= 5
        # Each tuple: (series_id, indicator_name, region)
        for series_id, indicator, region in FRED_SERIES:
            assert isinstance(series_id, str)
            assert isinstance(indicator, str)
            assert isinstance(region, str)

    @respx.mock
    async def test_fetch_yields_records(self):
        """FRED fetch parses observation responses correctly."""
        # Mock all FRED API calls
        respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
            return_value=httpx.Response(
                200,
                json={
                    "observations": [
                        {"date": "2024-01-01", "value": "1234.5"},
                        {"date": "2024-02-01", "value": "1245.6"},
                        {"date": "2024-03-01", "value": "."},  # missing value
                    ]
                },
            )
        )

        records = []
        async with FREDClient() as client:
            async for record in client.fetch():
                records.append(record)

        # Should skip the "." missing value
        assert len(records) >= 2  # at least 2 per series (5 series = 10 records)
        assert all(r.source == "FRED" for r in records)
        assert all(isinstance(r.value, float) for r in records)

    @respx.mock
    async def test_fetch_skips_on_no_api_key(self):
        """Without FRED API key, fetch should yield nothing."""
        from unittest.mock import patch

        from frr.config import Settings

        mock_settings = Settings(fred_api_key="")
        with patch("frr.ingestion.sources.fred.get_settings", return_value=mock_settings):
            records = []
            async with FREDClient() as client:
                async for record in client.fetch():
                    records.append(record)
            assert len(records) == 0
