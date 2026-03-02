"""WebSocket router — real-time CESI score and signal updates via Redis pub/sub.

Clients connect to ``/ws/scores`` to receive live CESI updates, or
``/ws/signals/{region_code}`` for per-region signal events.

Architecture:
- Backend publishes updates to Redis channels on score/signal changes.
- WebSocket connections subscribe to relevant Redis channels.
- Fan-out: one Redis subscriber per connection (acceptable for MVP scale).

Channels:
- ``frr:cesi:*``              — CESI score updates for all regions
- ``frr:cesi:{region_code}``  — CESI score for a specific region
- ``frr:signals:{region}``    — new signal ingest events for a region
- ``frr:alerts``              — system-wide alert events
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from frr.services.cache import get_redis, publish

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── Channel constants ──────────────────────────────────────────────────
CHANNEL_CESI_ALL = "frr:cesi:all"
CHANNEL_CESI_REGION = "frr:cesi:{region}"
CHANNEL_SIGNALS = "frr:signals:{region}"
CHANNEL_ALERTS = "frr:alerts"


# ── Connection manager ─────────────────────────────────────────────────

class ConnectionManager:
    """Manage active WebSocket connections and handle cleanup."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, channel: str) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.setdefault(channel, set()).add(ws)
        logger.debug("WebSocket connected", channel=channel)

    async def disconnect(self, ws: WebSocket, channel: str) -> None:
        async with self._lock:
            conns = self._connections.get(channel, set())
            conns.discard(ws)
            if not conns:
                self._connections.pop(channel, None)
        logger.debug("WebSocket disconnected", channel=channel)

    async def broadcast(self, channel: str, data: dict[str, Any]) -> None:
        """Send a message to all connections subscribed to a channel."""
        async with self._lock:
            conns = list(self._connections.get(channel, set()))

        disconnected: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)

        # Cleanup dead connections
        for ws in disconnected:
            await self.disconnect(ws, channel)

    @property
    def active_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


manager = ConnectionManager()


# ── Redis subscriber background task ──────────────────────────────────

async def _redis_subscriber(ws: WebSocket, channels: list[str]) -> None:
    """Subscribe to Redis pub/sub channels and forward messages to WebSocket."""
    redis = get_redis()
    pubsub = redis.pubsub()

    try:
        await pubsub.subscribe(*channels)
        logger.debug("Redis subscriber started", channels=channels)

        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await ws.send_json({
                        "channel": message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"],
                        "data": data,
                    })
                except (json.JSONDecodeError, Exception):
                    continue
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()


# ── WebSocket endpoints ───────────────────────────────────────────────

@router.websocket("/ws/scores")
async def ws_cesi_scores(ws: WebSocket) -> None:
    """Stream live CESI score updates for all regions.

    Message format:
    ```json
    {
      "channel": "frr:cesi:all",
      "data": {
        "event": "cesi_update",
        "region_code": "EU",
        "score": 42.5,
        "severity": "elevated",
        "amplification_applied": false,
        "scored_at": "2026-03-01T12:00:00Z"
      }
    }
    ```
    """
    channel = CHANNEL_CESI_ALL
    await manager.connect(ws, channel)
    subscriber_task = asyncio.create_task(_redis_subscriber(ws, [channel]))

    try:
        # Keep connection alive; handle client pings
        while True:
            try:
                msg = await ws.receive_text()
                # Handle ping/pong
                if msg == "ping":
                    await ws.send_text("pong")
            except WebSocketDisconnect:
                break
    finally:
        subscriber_task.cancel()
        await manager.disconnect(ws, channel)


@router.websocket("/ws/scores/{region_code}")
async def ws_cesi_region(ws: WebSocket, region_code: str) -> None:
    """Stream live CESI score updates for a specific region."""
    channel = CHANNEL_CESI_REGION.format(region=region_code.upper())
    await manager.connect(ws, channel)
    subscriber_task = asyncio.create_task(_redis_subscriber(ws, [channel, CHANNEL_CESI_ALL]))

    try:
        while True:
            try:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
            except WebSocketDisconnect:
                break
    finally:
        subscriber_task.cancel()
        await manager.disconnect(ws, channel)


@router.websocket("/ws/signals/{region_code}")
async def ws_signals(ws: WebSocket, region_code: str) -> None:
    """Stream live signal ingestion events for a specific region.

    Message format:
    ```json
    {
      "channel": "frr:signals:EU",
      "data": {
        "event": "signal_ingested",
        "source": "FRED",
        "indicator": "GDP_GROWTH_REAL",
        "value": -0.3,
        "ts": "2026-01-01T00:00:00Z",
        "layer": "research_funding"
      }
    }
    ```
    """
    channel = CHANNEL_SIGNALS.format(region=region_code.upper())
    await manager.connect(ws, channel)
    subscriber_task = asyncio.create_task(_redis_subscriber(ws, [channel]))

    try:
        while True:
            try:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
            except WebSocketDisconnect:
                break
    finally:
        subscriber_task.cancel()
        await manager.disconnect(ws, channel)


@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket) -> None:
    """Stream system-wide alert events (threshold breaches, amplification triggers).

    Message format:
    ```json
    {
      "channel": "frr:alerts",
      "data": {
        "event": "threshold_breach",
        "region_code": "MENA",
        "score": 78.2,
        "severity": "high_risk",
        "crisis_types": ["political_unrest", "recession"],
        "message": "CESI exceeded 75.0 threshold for MENA"
      }
    }
    ```
    """
    channel = CHANNEL_ALERTS
    await manager.connect(ws, channel)
    subscriber_task = asyncio.create_task(_redis_subscriber(ws, [channel]))

    try:
        while True:
            try:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
            except WebSocketDisconnect:
                break
    finally:
        subscriber_task.cancel()
        await manager.disconnect(ws, channel)


# ── Publish helpers (called from scoring engine / ingestion) ──────────

async def publish_cesi_update(
    region_code: str,
    score: float,
    severity: str,
    amplification_applied: bool,
    scored_at: str,
    crisis_probabilities: dict[str, Any] | None = None,
) -> None:
    """Publish a CESI score update to all relevant WebSocket channels."""
    payload = {
        "event": "cesi_update",
        "region_code": region_code,
        "score": round(score, 2),
        "severity": severity,
        "amplification_applied": amplification_applied,
        "scored_at": scored_at,
        "crisis_probabilities": crisis_probabilities or {},
    }

    # Publish to both all-scores and region-specific channels
    await publish(CHANNEL_CESI_ALL, payload)
    await publish(CHANNEL_CESI_REGION.format(region=region_code), payload)

    # Check for alert thresholds
    if score >= 75.0:
        alert_payload = {
            "event": "threshold_breach",
            "region_code": region_code,
            "score": round(score, 2),
            "severity": severity,
            "message": f"CESI exceeded 75.0 threshold for {region_code}",
        }
        await publish(CHANNEL_ALERTS, alert_payload)

    logger.debug(
        "CESI update published",
        region=region_code,
        score=round(score, 2),
        ws_connections=manager.active_connections,
    )


async def publish_signal_event(
    region_code: str,
    source: str,
    indicator: str,
    value: float,
    ts: str,
    layer: str,
) -> None:
    """Publish a new signal ingestion event."""
    payload = {
        "event": "signal_ingested",
        "source": source,
        "indicator": indicator,
        "value": value,
        "ts": ts,
        "layer": layer,
    }
    await publish(CHANNEL_SIGNALS.format(region=region_code), payload)
