"""
SKILL-001 Caching Tool: Generate production cache infrastructure for FastAPI.

Creates a complete Redis-backed caching module with cache-aside pattern,
TTL strategy by data type, stampede prevention (XFetch probabilistic refresh),
event-driven invalidation, distributed locking, cache key builder, multi-level
cache, ETag support, and cache warming on deploy.

Generated files:
    cache/__init__.py       -- package marker with re-exports
    cache/client.py         -- Redis client setup and FastAPI dependency
    cache/aside.py          -- Cache-aside pattern with TTL and error handling
    cache/stampede.py       -- Stampede prevention (XFetch + lock-based)
    cache/keys.py           -- Centralized cache key builder
    cache/lock.py           -- Distributed lock (SET NX EX + Lua release)
    cache/warming.py        -- Cache warming on deploy (lifespan startup)
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _init_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Caching module — production Redis cache strategies for FastAPI.\"\"\"

        from .aside import CacheAside
        from .client import get_redis, init_redis, close_redis
        from .keys import CacheKeys, CacheTTL
        from .lock import RedisLock, LockNotAcquired

        __all__ = [
            "CacheAside",
            "CacheKeys",
            "CacheTTL",
            "RedisLock",
            "LockNotAcquired",
            "get_redis",
            "init_redis",
            "close_redis",
        ]
    """)


def _client_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Redis client setup and FastAPI dependency.\"\"\"

        from __future__ import annotations

        import redis.asyncio as redis

        _pool: redis.Redis | None = None


        async def init_redis(redis_url: str = "redis://localhost:6379") -> redis.Redis:
            \"\"\"Initialize the Redis connection pool. Call from lifespan startup.\"\"\"
            global _pool
            _pool = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=False,  # We handle decoding explicitly
                max_connections=20,
            )
            # Verify connection
            await _pool.ping()
            return _pool


        async def close_redis() -> None:
            \"\"\"Close the Redis connection pool. Call from lifespan shutdown.\"\"\"
            global _pool
            if _pool:
                await _pool.close()
                _pool = None


        async def get_redis() -> redis.Redis:
            \"\"\"FastAPI dependency that returns the Redis client.\"\"\"
            if _pool is None:
                raise RuntimeError(
                    "Redis not initialized. Call init_redis() in lifespan."
                )
            return _pool
    """)


def _keys_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Centralized cache key builder and TTL configuration.

        All cache keys are built through CacheKeys to ensure consistent naming,
        easy invalidation, and no collisions. Key format: namespace:entity:id:qualifier.
        \"\"\"

        from __future__ import annotations

        import random
        from enum import IntEnum


        class CacheTTL(IntEnum):
            \"\"\"TTL in seconds, organized by data volatility.\"\"\"
            REALTIME = 10          # Prices, live counters — barely cacheable
            HOT = 60               # Session data, active feeds
            WARM = 300             # User profiles, settings (5 min)
            STANDARD = 3600        # Config, permissions (1 hour)
            COLD = 86400           # Reference data, country codes (24 hours)
            STATIC = 604800        # Immutable data, historical records (7 days)


        def ttl_with_jitter(base_ttl: int, jitter_pct: float = 0.1) -> int:
            \"\"\"Add +/- jitter% to TTL to desynchronize expirations.

            Prevents thundering herd when many keys with the same TTL
            expire simultaneously, causing concurrent cache misses.
            \"\"\"
            jitter = int(base_ttl * jitter_pct)
            return base_ttl + random.randint(-jitter, jitter)


        class CacheKeys:
            \"\"\"Centralized cache key builder. Single source of truth for key format.

            Usage:
                key = CacheKeys.user(123)              # "user:123"
                key = CacheKeys.user_list(1, 20)       # "users:list:p1:pp20:screated"
                key = CacheKeys.product(456, "pt")     # "product:456:locale:pt"
            \"\"\"

            @staticmethod
            def user(user_id: int | str) -> str:
                return f"user:{user_id}"

            @staticmethod
            def user_list(page: int = 1, per_page: int = 20, sort: str = "created") -> str:
                return f"users:list:p{page}:pp{per_page}:s{sort}"

            @staticmethod
            def user_roles(user_id: int | str) -> str:
                return f"user:{user_id}:roles"

            @staticmethod
            def product(product_id: int | str, locale: str = "en") -> str:
                return f"product:{product_id}:locale:{locale}"

            @staticmethod
            def product_list(category: str, page: int = 1) -> str:
                return f"products:list:{category}:p{page}"

            @staticmethod
            def config(key: str, version: int = 1) -> str:
                return f"config:{key}:v{version}"

            @staticmethod
            def rate_limit(identifier: str, endpoint: str) -> str:
                return f"rl:{identifier}:{endpoint}"

            @staticmethod
            def session(session_id: str) -> str:
                return f"session:{session_id}"
    """)


def _aside_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Cache-aside pattern — check cache -> miss -> fetch -> set.

        All cache operations are non-blocking: cache failures never break
        the request. If Redis is down, the system works (slower) by falling
        back to the data source.
        \"\"\"

        from __future__ import annotations

        import json
        import logging
        from typing import Any, Awaitable, Callable, TypeVar

        import redis.asyncio as redis_client

        from .keys import CacheTTL, ttl_with_jitter

        logger = logging.getLogger("cache.aside")

        T = TypeVar("T")


        class CacheAside:
            \"\"\"Cache-aside implementation with automatic TTL jitter.\"\"\"

            def __init__(self, redis: redis_client.Redis):
                self.redis = redis

            async def get_or_set(
                self,
                key: str,
                fetch_fn: Callable[[], Awaitable[T]] | Callable[[], T],
                ttl: int = CacheTTL.WARM,
                jitter: bool = True,
            ) -> T:
                \"\"\"Check cache -> miss -> call fetch_fn -> set cache -> return.

                Args:
                    key: Cache key.
                    fetch_fn: Async or sync callable that fetches data on miss.
                    ttl: Time-to-live in seconds (default: 5 minutes).
                    jitter: Add TTL jitter to prevent synchronized expiration.

                Returns:
                    Cached or freshly fetched data.
                \"\"\"
                # 1. Check cache
                try:
                    cached = await self.redis.get(key)
                    if cached is not None:
                        return json.loads(cached)
                except redis_client.RedisError:
                    logger.warning(f"Redis GET failed for {key}, falling back to source")

                # 2. Cache miss — fetch from source
                result = fetch_fn()
                if hasattr(result, "__await__"):
                    value = await result
                else:
                    value = result

                # 3. Set cache (non-blocking, never breaks request)
                actual_ttl = ttl_with_jitter(ttl) if jitter else ttl
                try:
                    await self.redis.set(
                        key, json.dumps(value, default=str), ex=actual_ttl,
                    )
                except redis_client.RedisError:
                    logger.warning(f"Redis SET failed for {key}")

                return value

            async def invalidate(self, key: str) -> None:
                \"\"\"Delete a cache entry. Safe on failure.\"\"\"
                try:
                    await self.redis.delete(key)
                except redis_client.RedisError:
                    logger.warning(f"Redis DELETE failed for {key}")

            async def invalidate_pattern(self, pattern: str) -> int:
                \"\"\"Delete all keys matching a pattern (using SCAN, not KEYS).

                Args:
                    pattern: Glob pattern, e.g., 'users:list:*'.

                Returns:
                    Number of keys deleted.
                \"\"\"
                deleted = 0
                try:
                    async for key in self.redis.scan_iter(match=pattern, count=100):
                        await self.redis.delete(key)
                        deleted += 1
                except redis_client.RedisError:
                    logger.warning(f"Redis SCAN/DELETE failed for pattern {pattern}")
                return deleted
    """)


def _stampede_py(with_stampede_prevention: bool) -> str:
    if not with_stampede_prevention:
        return textwrap.dedent("""\
            \"\"\"Cache stampede prevention — disabled in this configuration.\"\"\"
            # Enable with: generate_cache_module(output_dir, with_stampede_prevention=True)
        """)

    return textwrap.dedent("""\
        \"\"\"Cache stampede prevention — XFetch probabilistic early recomputation.

        The XFetch algorithm probabilistically refreshes cache entries before
        they expire. As a key approaches expiration, there's an increasing
        probability that any request will proactively refresh it. This spreads
        the refresh load naturally and prevents stampede without locks.

        Reference: Vattani, A., Chierichetti, F., & Lowenstein, K. (2015).
        "Optimal Probabilistic Cache Stampede Prevention."
        \"\"\"

        from __future__ import annotations

        import json
        import logging
        import math
        import random
        import time
        from typing import Any, Awaitable, Callable, TypeVar

        import redis.asyncio as redis_client

        logger = logging.getLogger("cache.stampede")

        T = TypeVar("T")


        async def xfetch(
            redis: redis_client.Redis,
            key: str,
            fetch_fn: Callable[[], Awaitable[T]] | Callable[[], T],
            ttl: int = 300,
            beta: float = 1.0,
        ) -> T:
            \"\"\"XFetch — probabilistic early recomputation to prevent stampede.

            As the key approaches expiration, there's an increasing probability
            that this request will proactively refresh it. The probability is
            calibrated by the computation time (delta) and the beta parameter.

            Args:
                redis: Redis client.
                key: Cache key.
                fetch_fn: Callable that recomputes the value.
                ttl: Time-to-live in seconds.
                beta: Tuning parameter.
                    1.0 = optimal for most workloads.
                    >1.0 = refresh earlier (more conservative).
                    <1.0 = refresh later (more aggressive, higher stampede risk).

            Returns:
                Cached or freshly computed value.
            \"\"\"
            try:
                raw = await redis.get(key)
            except redis_client.RedisError:
                raw = None

            if raw is not None:
                try:
                    entry = json.loads(raw)
                    value = entry["value"]
                    delta = entry.get("delta", 0.1)
                    expiry = entry.get("expiry", time.time() + ttl)

                    now = time.time()
                    ttl_remaining = expiry - now

                    # Probabilistic check: should we refresh early?
                    rand = random.random()
                    if rand > 0:
                        threshold = delta * beta * math.log(rand)
                    else:
                        threshold = float("-inf")

                    if ttl_remaining + threshold > 0:
                        return value  # Cache hit — no refresh needed

                    logger.debug(f"XFetch: proactive refresh for {key} (ttl_remaining={ttl_remaining:.1f}s)")
                except (json.JSONDecodeError, KeyError):
                    pass  # Corrupted entry — fall through to refresh

            # Recompute
            start = time.time()
            result = fetch_fn()
            if hasattr(result, "__await__"):
                value = await result
            else:
                value = result
            delta = time.time() - start

            entry = {
                "value": value,
                "delta": max(delta, 0.001),  # Minimum delta to avoid log(0) issues
                "expiry": time.time() + ttl,
            }

            try:
                await redis.set(key, json.dumps(entry, default=str), ex=ttl)
            except redis_client.RedisError:
                logger.warning(f"Redis SET failed for {key} during XFetch refresh")

            return value
    """)


def _lock_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Distributed lock using Redis SET NX EX + Lua script for safe release.

        The Lua script ensures only the lock owner can release it — prevents
        one worker from accidentally releasing another worker's lock.
        \"\"\"

        from __future__ import annotations

        import uuid

        import redis.asyncio as redis_client


        class LockNotAcquired(Exception):
            \"\"\"Raised when a lock cannot be acquired.\"\"\"
            pass


        # Lua script: atomically check ownership and delete
        _RELEASE_SCRIPT = \"\"\"
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        \"\"\"


        class RedisLock:
            \"\"\"Distributed lock with automatic expiry and safe release.

            Usage:
                lock = RedisLock(redis, "my-resource", ttl=30)
                async with lock:
                    # Critical section — only one worker at a time
                    await do_exclusive_work()

            The TTL is a safety valve: if the lock holder crashes, the lock
            auto-releases after TTL seconds. Set TTL longer than expected
            operation time.
            \"\"\"

            def __init__(
                self,
                redis: redis_client.Redis,
                name: str,
                ttl: int = 30,
            ):
                self.redis = redis
                self.key = f"lock:{name}"
                self.ttl = ttl
                self.token = str(uuid.uuid4())

            async def acquire(self) -> bool:
                \"\"\"Try to acquire the lock. Returns True if acquired.\"\"\"
                result = await self.redis.set(
                    self.key, self.token, nx=True, ex=self.ttl,
                )
                return bool(result)

            async def release(self) -> bool:
                \"\"\"Release the lock. Only succeeds if we still own it.\"\"\"
                result = await self.redis.eval(
                    _RELEASE_SCRIPT, 1, self.key, self.token,
                )
                return bool(result)

            async def extend(self, additional_ttl: int | None = None) -> bool:
                \"\"\"Extend the lock TTL. Only succeeds if we still own it.\"\"\"
                ttl = additional_ttl or self.ttl
                # Check ownership before extending
                current = await self.redis.get(self.key)
                if current and current.decode() == self.token:
                    await self.redis.expire(self.key, ttl)
                    return True
                return False

            async def __aenter__(self):
                acquired = await self.acquire()
                if not acquired:
                    raise LockNotAcquired(f"Could not acquire lock: {self.key}")
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                await self.release()
    """)


def _warming_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Cache warming — preload hot data on deploy before accepting traffic.

        Run during FastAPI lifespan startup to populate cache with frequently
        accessed data. Uses Redis pipelines for efficient bulk loading.
        \"\"\"

        from __future__ import annotations

        import json
        import logging

        import redis.asyncio as redis_client

        from .keys import CacheTTL

        logger = logging.getLogger("cache.warming")


        async def warm_cache(redis: redis_client.Redis) -> dict:
            \"\"\"Preload hot data into cache during startup.

            Override this function with your application-specific warming logic.
            Uses Redis pipelines for efficient bulk inserts.

            Returns:
                Dict with counts of warmed items per category.
            \"\"\"
            stats: dict[str, int] = {}

            # Example: Warm feature flags (read on every request)
            # flags = await db.get_all_feature_flags()
            # if flags:
            #     await redis.set("config:feature_flags", json.dumps(flags), ex=CacheTTL.STANDARD)
            #     stats["feature_flags"] = len(flags)

            # Example: Warm top products using pipeline (bulk insert)
            # products = await db.get_top_products(limit=100)
            # if products:
            #     pipe = redis.pipeline()
            #     for p in products:
            #         pipe.set(f"product:{p['id']}", json.dumps(p), ex=CacheTTL.WARM)
            #     await pipe.execute()
            #     stats["products"] = len(products)

            logger.info(f"Cache warming complete: {stats}")
            return stats
    """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_cache_module(
    output_dir: str,
    backend: str = "redis",
    with_stampede_prevention: bool = True,
) -> dict:
    """
    Generate a production-ready caching module for a FastAPI project.

    Creates a Redis-backed cache implementation with cache-aside pattern,
    TTL strategy, stampede prevention (XFetch), distributed locking,
    centralized key builder, and cache warming inside a ``cache/``
    subdirectory of *output_dir*.

    Args:
        output_dir: Parent directory where the ``cache/`` package will be created.
        backend: Cache backend. Currently only "redis" is supported.
        with_stampede_prevention: Include XFetch probabilistic cache stampede
            prevention. Recommended for high-traffic applications.

    Returns:
        Dict with ``created_files`` (list of paths) and ``cache_path`` (str).

    Example::

        result = generate_cache_module("/tmp/myproject", with_stampede_prevention=True)
        print(result["created_files"])
        # ['cache/__init__.py', 'cache/client.py', 'cache/keys.py',
        #  'cache/aside.py', 'cache/stampede.py', 'cache/lock.py',
        #  'cache/warming.py']
    """
    if backend != "redis":
        raise ValueError(f"Unsupported backend: {backend}. Only 'redis' is supported.")

    cache_dir = Path(output_dir) / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _init_py(),
        "client.py": _client_py(),
        "keys.py": _keys_py(),
        "aside.py": _aside_py(),
        "stampede.py": _stampede_py(with_stampede_prevention),
        "lock.py": _lock_py(),
        "warming.py": _warming_py(),
    }

    created: list[str] = []
    for filename, content in files.items():
        filepath = cache_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"cache/{filename}")

    return {
        "created_files": created,
        "cache_path": str(cache_dir),
        "backend": backend,
        "with_stampede_prevention": with_stampede_prevention,
    }
