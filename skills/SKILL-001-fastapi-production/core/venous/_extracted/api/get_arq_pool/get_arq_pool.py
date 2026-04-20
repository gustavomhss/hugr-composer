from __future__ import annotations


async def get_arq_pool() -> 'ArqRedis':
    """Return a connected ARQ Redis pool for enqueuing background jobs.

    Uses ``settings.REDIS_URL``. Imports ``arq`` lazily inside the
    function body so ``app.main`` boots cleanly even when the
    package is not installed — the import error only surfaces
    when a caller actually tries to enqueue a job.

    Returns:
        Connected ``ArqRedis`` pool.
    """
    from arq.connections import RedisSettings, create_pool
    redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
    return await create_pool(RedisSettings.from_dsn(redis_url))
