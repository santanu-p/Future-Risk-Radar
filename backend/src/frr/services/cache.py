"""Redis cache service — hot signal cache and pub/sub."""

from __future__ import annotations

from typing import Any

import orjson
import redis.asyncio as aioredis
import structlog

from frr.config import get_settings

logger = structlog.get_logger(__name__)

_pool: aioredis.Redis | None = None


async def init_redis() -> None:
    """Initialise the global async Redis connection pool."""
    global _pool
    settings = get_settings()
    _pool = aioredis.from_url(
        settings.redis_url,
        decode_responses=False,
        max_connections=50,
    )
    await _pool.ping()
    logger.info("Redis connected", url=settings.redis_url)


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()  # type: ignore[union-attr]
        _pool = None
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    if _pool is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _pool


# ── Convenience helpers ────────────────────────────────────────────────
async def cache_get(key: str) -> Any | None:
    raw = await get_redis().get(key)
    if raw is None:
        return None
    return orjson.loads(raw)


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    settings = get_settings()
    ttl = ttl or settings.redis_cache_ttl
    await get_redis().set(key, orjson.dumps(value), ex=ttl)


async def cache_delete(key: str) -> None:
    await get_redis().delete(key)


async def publish(channel: str, payload: dict[str, Any]) -> None:
    """Publish a message to Redis pub/sub — used for WebSocket fan-out."""
    await get_redis().publish(channel, orjson.dumps(payload))
