from __future__ import annotations


async def init_store(redis_url: str | None=None, ttl_s: int=60) -> None:
    """Initialise the global fingerprint store.  Call once at app startup.

    Args:
        redis_url: Redis connection URL.  When ``None`` or empty, uses
            the in-memory fallback only.
        ttl_s: Fingerprint TTL in seconds.
    """
    global _store
    redis = None
    if redis_url:
        try:
            from redis.asyncio import Redis
            redis = Redis.from_url(redis_url, decode_responses=True)
        except Exception:
            logger.warning('FingerprintStore: Redis init failed, using memory', exc_info=True)
    _store = FingerprintStore(redis=redis, ttl_s=ttl_s)
