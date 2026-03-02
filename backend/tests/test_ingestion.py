"""Tests for ingestion base classes and source clients."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from frr.db.models import SignalLayer
from frr.ingestion.base import BaseSourceClient, SignalRecord


# ── SignalRecord ───────────────────────────────────────────────────────


class TestSignalRecord:
    """SignalRecord dataclass validation."""

    def test_create_minimal(self):
        sr = SignalRecord(
            region_code="EU",
            layer=SignalLayer.ENERGY_CONFLICT,
            source="TEST",
            indicator="OIL_PRICE",
            ts=datetime(2024, 1, 1),
            value=75.5,
        )
        assert sr.region_code == "EU"
        assert sr.layer == SignalLayer.ENERGY_CONFLICT
        assert sr.source == "TEST"
        assert sr.indicator == "OIL_PRICE"
        assert sr.value == 75.5
        assert sr.metadata == {}

    def test_create_with_metadata(self):
        sr = SignalRecord(
            region_code="MENA",
            layer=SignalLayer.SUPPLY_CHAIN,
            source="WTO",
            indicator="TRADE_VOL",
            ts=datetime(2024, 6, 1),
            value=1234.56,
            metadata={"unit": "USD_M"},
        )
        assert sr.metadata == {"unit": "USD_M"}

    def test_slots(self):
        """SignalRecord uses __slots__ for memory efficiency."""
        sr = SignalRecord(
            region_code="EU",
            layer=SignalLayer.RESEARCH_FUNDING,
            source="NSF",
            indicator="AWARD_COUNT",
            ts=datetime(2024, 1, 1),
            value=100.0,
        )
        assert hasattr(sr, "__slots__")


# ── BaseSourceClient ──────────────────────────────────────────────────


class ConcreteTestClient(BaseSourceClient):
    """Concrete implementation for testing."""

    SOURCE_NAME = "TEST_SOURCE"
    LAYER = SignalLayer.RESEARCH_FUNDING

    async def fetch(self):
        data = await self._get("https://api.example.com/data", params={"key": "test"})
        for item in data.get("results", []):
            yield SignalRecord(
                region_code="EU",
                layer=self.LAYER,
                source=self.SOURCE_NAME,
                indicator="TEST_IND",
                ts=datetime(2024, 1, 1),
                value=float(item["value"]),
            )


class TestBaseSourceClient:
    """Base client HTTP logic and lifecycle."""

    async def test_context_manager(self):
        async with ConcreteTestClient() as client:
            assert client._client is not None
        assert client._client is None

    async def test_client_property_raises_without_context(self):
        c = ConcreteTestClient()
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = c.client

    @respx.mock
    async def test_get_success(self):
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(200, json={"results": [{"value": 42}]})
        )

        async with ConcreteTestClient() as client:
            data = await client._get("https://api.example.com/data")
            assert data == {"results": [{"value": 42}]}

    @respx.mock
    async def test_get_rate_limit(self):
        from frr.exceptions import RateLimitError

        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "30"})
        )

        async with ConcreteTestClient() as client:
            with pytest.raises(RateLimitError) as exc_info:
                await client._get("https://api.example.com/data")
            assert exc_info.value.retry_after == 30

    @respx.mock
    async def test_get_ingestion_error(self):
        from frr.exceptions import IngestionError

        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        async with ConcreteTestClient() as client:
            with pytest.raises(IngestionError):
                await client._get("https://api.example.com/data")

    @respx.mock
    async def test_fetch_yields_records(self):
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(200, json={"results": [{"value": 10}, {"value": 20}]})
        )

        records = []
        async with ConcreteTestClient() as client:
            async for record in client.fetch():
                records.append(record)

        assert len(records) == 2
        assert records[0].value == 10.0
        assert records[1].value == 20.0

    @respx.mock
    async def test_ingest_calls_persist(self):
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(200, json={"results": [{"value": 10}]})
        )

        with patch("frr.ingestion.base.persist_signals", new_callable=AsyncMock, return_value=1) as mock_persist:
            async with ConcreteTestClient() as client:
                count = await client.ingest()

            assert count == 1
            mock_persist.assert_called_once()
            records = mock_persist.call_args[0][0]
            assert len(records) == 1

    @respx.mock
    async def test_ingest_no_records(self):
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        async with ConcreteTestClient() as client:
            count = await client.ingest()
            assert count == 0
