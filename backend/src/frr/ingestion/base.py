"""Abstract base client for data source ingestion.

All source clients inherit from ``BaseSourceClient`` and implement:
- ``fetch()`` → async generator of raw records
- ``transform()`` → normalise into SignalSeries rows

Retry logic (tenacity), rate-limit handling, and structured logging
are built into the base class.
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import Any, AsyncGenerator

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from frr.config import get_settings
from frr.db.models import SignalLayer
from frr.exceptions import IngestionError, RateLimitError

logger = structlog.get_logger(__name__)


class SignalRecord:
    """Normalised signal record ready for DB insertion."""

    __slots__ = ("region_code", "layer", "source", "indicator", "ts", "value", "metadata")

    def __init__(
        self,
        region_code: str,
        layer: SignalLayer,
        source: str,
        indicator: str,
        ts: datetime,
        value: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.region_code = region_code
        self.layer = layer
        self.source = source
        self.indicator = indicator
        self.ts = ts
        self.value = value
        self.metadata = metadata or {}


class BaseSourceClient(abc.ABC):
    """Base class for all data source ingestion clients."""

    SOURCE_NAME: str = "UNKNOWN"
    LAYER: SignalLayer = SignalLayer.RESEARCH_FUNDING  # override in subclasses

    def __init__(self) -> None:
        settings = get_settings()
        self._timeout = httpx.Timeout(settings.ingestion_timeout_seconds)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BaseSourceClient":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Client not initialised — use 'async with' context manager")
        return self._client

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """HTTP GET with automatic retry on transport errors."""
        logger.debug("HTTP GET", url=url, source=self.SOURCE_NAME)
        resp = await self.client.get(url, params=params)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            raise RateLimitError(self.SOURCE_NAME, retry_after)

        if resp.status_code >= 400:
            raise IngestionError(self.SOURCE_NAME, f"HTTP {resp.status_code}: {resp.text[:200]}")

        return resp.json()

    @abc.abstractmethod
    async def fetch(self) -> AsyncGenerator[SignalRecord, None]:
        """Yield normalised signal records from the external source."""
        ...  # pragma: no cover

    async def ingest(self) -> int:
        """Run the full ingestion cycle: fetch → persist.

        Returns the number of records persisted.
        """
        from frr.ingestion.persist import persist_signals

        records: list[SignalRecord] = []
        async for record in self.fetch():
            records.append(record)

        if records:
            count = await persist_signals(records)
            logger.info("Ingestion complete", source=self.SOURCE_NAME, records=count)
            return count

        logger.warning("No records fetched", source=self.SOURCE_NAME)
        return 0
