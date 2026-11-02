"""FastAPI dependencies — shared singletons (Redis, etc.)."""
from __future__ import annotations

from redis.asyncio import Redis

from shared.config import get_settings

settings = get_settings()
_redis: Redis | None = None


async def get_redis() -> Redis:
    """FastAPI dependency — returns a singleton Redis connection."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def get_redis_direct() -> Redis:
    """Direct Redis connection for use outside FastAPI DI (e.g. Temporal
    activities). The caller must ``await .aclose()`` when done."""
    return Redis.from_url(settings.redis_url, decode_responses=True)
