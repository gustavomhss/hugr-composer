from __future__ import annotations


async def init_recorder(redis_url: str, ttl_s: int=3600, max_entries: int=10000, exclude_paths: list[str] | None=None) -> None:
    """Initialise the global recorder.  Call once at app startup.

    Args:
        redis_url: Redis connection URL.
        ttl_s: TTL for the ring-buffer list key.
        max_entries: Maximum entries in the ring buffer.
        exclude_paths: Paths to skip (default: ["/healthz", "/metrics"]).
    """
    from redis.asyncio import Redis
    global _recorder
    redis = Redis.from_url(redis_url, decode_responses=True)
    _recorder = RequestRecorder(redis=redis, ttl_s=ttl_s, max_entries=max_entries, exclude_paths=exclude_paths)
