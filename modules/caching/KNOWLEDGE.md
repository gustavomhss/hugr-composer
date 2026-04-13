# Module: Caching — Production Cache Strategies for FastAPI

> The LLM generates: `@cache` decorator with no TTL, no invalidation, no stampede prevention, no key design.
> The staff engineer knows: cache-aside with proper TTL, stampede prevention via probabilistic early refresh, event-driven invalidation, multi-level caching, distributed locks, cache key namespacing.

---

## 1. Cache-Aside Pattern (Read: Check Cache -> Miss -> DB -> Set Cache)

### WHY
Cache-aside (also called "lazy loading") is the most common caching pattern: the application checks the cache first, and on a miss, queries the database and populates the cache. The LLM puts a `@cache` decorator on an endpoint and calls it done. The staff engineer implements cache-aside with explicit TTL, serialization, error handling (cache failure should not crash the request), and metrics (hit/miss rate).

### HOW
```python
import redis.asyncio as redis
import json
from typing import TypeVar, Callable

T = TypeVar("T")

class CacheAside:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def get_or_set(
        self, key: str, fetch_fn: Callable[[], T], ttl: int = 300,
    ) -> T:
        """Check cache -> miss -> call fetch_fn -> set cache -> return."""
        # 1. Check cache
        cached = await self.redis.get(key)
        if cached is not None:
            return json.loads(cached)

        # 2. Cache miss — fetch from source
        value = await fetch_fn()

        # 3. Set cache (non-blocking, fire-and-forget on failure)
        try:
            await self.redis.set(key, json.dumps(value, default=str), ex=ttl)
        except redis.RedisError:
            pass  # Cache failure should NEVER break the request

        return value

# Usage in a route
@app.get("/users/{user_id}")
async def get_user(user_id: int, cache: CacheAside = Depends(get_cache)):
    key = f"user:{user_id}"
    return await cache.get_or_set(
        key,
        fetch_fn=lambda: db.get_user(user_id),
        ttl=300,  # 5 minutes
    )
```

### GOTCHA
Cache-aside has a consistency window: data is stale between the DB write and the next cache miss. For reads that must be immediately consistent (e.g., right after profile update), bypass the cache: pass a `skip_cache=True` parameter or use write-through (technique 4). Also: `json.dumps(value, default=str)` handles datetime/UUID serialization, but always test with your actual data types.

---

## 2. TTL Strategy by Data Type

### WHY
Not all data has the same staleness tolerance. User profile can be 5 minutes stale. Application config should be cached for an hour. Static reference data (country codes, currency list) can be cached for 24 hours. The LLM uses the same TTL (or no TTL) for everything. The staff engineer assigns TTL based on how frequently the data changes and how much staleness the use case tolerates.

### HOW
```python
from enum import IntEnum

class CacheTTL(IntEnum):
    """TTL in seconds, organized by data volatility."""
    REALTIME = 10          # Prices, live counters — barely cacheable
    HOT = 60               # Session data, active feeds
    WARM = 300             # User profiles, settings (5 min)
    STANDARD = 3600        # Config, permissions (1 hour)
    COLD = 86400           # Reference data, country codes (24 hours)
    STATIC = 604800        # Immutable data, historical records (7 days)

# Usage
await cache.set(f"user:{uid}", user_data, ex=CacheTTL.WARM)
await cache.set(f"config:feature_flags", flags, ex=CacheTTL.STANDARD)
await cache.set(f"ref:countries", countries, ex=CacheTTL.COLD)

# Add jitter to prevent synchronized expiration (thundering herd)
import random

def ttl_with_jitter(base_ttl: int, jitter_pct: float = 0.1) -> int:
    """Add +/- jitter% to TTL to desynchronize expirations."""
    jitter = int(base_ttl * jitter_pct)
    return base_ttl + random.randint(-jitter, jitter)
```

### GOTCHA
Adding jitter to TTL (e.g., 300 +/- 30 seconds) prevents the "thundering herd" scenario where all entries for a popular query expire at the same time, causing simultaneous cache misses. Always add jitter for keys with the same base TTL.

---

## 3. Cache Stampede Prevention — Probabilistic Early Refresh and Locking

### WHY
A cache stampede (thundering herd) happens when a popular cache key expires, and hundreds of concurrent requests simultaneously miss the cache and all hit the database. The database gets overwhelmed, requests queue up, and the system cascades into failure. Two proven solutions: (1) probabilistic early refresh refreshes before expiration, spreading the load; (2) distributed locking makes only one request fetch while others wait.

### HOW
```python
import math
import random
import time

async def get_with_stampede_prevention(
    redis_client: redis.Redis,
    key: str,
    fetch_fn,
    ttl: int = 300,
    beta: float = 1.0,
) -> any:
    """XFetch algorithm — probabilistic early recomputation.

    As the key approaches expiration, there's an increasing probability
    that any request will proactively refresh it. This spreads the
    refresh load and prevents stampede.

    beta=1.0 is optimal for most workloads.
    beta>1.0 refreshes earlier (more conservative).
    """
    raw = await redis_client.get(key)
    if raw is not None:
        entry = json.loads(raw)
        value = entry["value"]
        delta = entry["delta"]      # Time it took to compute
        expiry = entry["expiry"]    # When we set it to expire

        # Probabilistic early recomputation
        now = time.time()
        ttl_remaining = expiry - now
        should_refresh = ttl_remaining - delta * beta * math.log(random.random()) <= 0

        if not should_refresh:
            return value
        # Fall through to refresh

    # Recompute (either cache miss or probabilistic refresh)
    start = time.time()
    value = await fetch_fn()
    delta = time.time() - start

    entry = {
        "value": value,
        "delta": delta,
        "expiry": time.time() + ttl,
    }
    await redis_client.set(key, json.dumps(entry, default=str), ex=ttl)
    return value


# Alternative: distributed lock approach
async def get_with_lock(redis_client, key, fetch_fn, ttl=300, lock_ttl=10):
    """Only one request fetches on miss; others wait briefly, then retry."""
    cached = await redis_client.get(key)
    if cached:
        return json.loads(cached)

    lock_key = f"lock:{key}"
    acquired = await redis_client.set(lock_key, "1", nx=True, ex=lock_ttl)
    if acquired:
        try:
            value = await fetch_fn()
            await redis_client.set(key, json.dumps(value, default=str), ex=ttl)
            return value
        finally:
            await redis_client.delete(lock_key)
    else:
        # Another request is fetching — wait briefly and retry from cache
        await asyncio.sleep(0.1)
        cached = await redis_client.get(key)
        if cached:
            return json.loads(cached)
        # Fallback: fetch ourselves (lock holder may have failed)
        return await fetch_fn()
```

### GOTCHA
The XFetch/probabilistic approach is statistically superior — it doesn't add latency from lock contention and self-heals naturally. The lock approach is simpler to understand but has a failure mode: if the lock holder crashes before populating the cache, others are blocked for `lock_ttl` seconds. Always set `lock_ttl` short (5-10s) as a safety valve.

---

## 4. Cache Invalidation — Event-Driven, Write-Through, Write-Behind

### WHY
Cache invalidation is one of the two hard problems in computer science. Stale data causes bugs that are hard to reproduce. The three main strategies: (1) event-driven — invalidate on write; (2) write-through — write to cache AND DB simultaneously; (3) write-behind — write to cache, async flush to DB. Each has different consistency/performance tradeoffs.

### HOW
```python
# Event-driven invalidation (most common, recommended default)
class UserService:
    def __init__(self, db, cache: redis.Redis):
        self.db = db
        self.cache = cache

    async def update_user(self, user_id: int, data: dict):
        # 1. Write to database (source of truth)
        await self.db.update_user(user_id, data)
        # 2. Invalidate cache (NOT update — avoids race conditions)
        await self.cache.delete(f"user:{user_id}")
        # 3. Invalidate related caches (list caches, search results)
        await self._invalidate_related(user_id)

    async def _invalidate_related(self, user_id: int):
        """Invalidate list caches that might contain this user."""
        # Pattern-based deletion for list caches
        keys = []
        async for key in self.cache.scan_iter(match="users:list:*"):
            keys.append(key)
        if keys:
            await self.cache.delete(*keys)

# Write-through (strong consistency, higher write latency)
async def update_user_write_through(self, user_id: int, data: dict):
    await self.db.update_user(user_id, data)
    # Update cache with fresh data — not just invalidate
    fresh = await self.db.get_user(user_id)
    await self.cache.set(f"user:{user_id}", json.dumps(fresh), ex=CacheTTL.WARM)
```

### GOTCHA
Prefer DELETE over UPDATE for cache invalidation. With UPDATE, a race condition can occur: Request A reads old DB value, Request B updates DB AND cache, Request A writes stale value to cache. DELETE is safe because the next read triggers a fresh fetch. Only use write-through when read-after-write consistency is critical (e.g., user just updated their profile and immediately views it).

---

## 5. Redis Data Structures for Caching

### WHY
The LLM uses `SET key json_blob` for everything. Redis has purpose-built data structures that are more memory-efficient and support atomic partial updates. Hashes for objects (update one field without re-serializing), sorted sets for leaderboards/feeds, sets for tags/memberships. Choosing the right structure reduces serialization overhead and enables operations that string caching cannot do.

### HOW
```python
# String — simple key-value (JSON blob)
await redis.set("user:123", json.dumps(user_dict), ex=300)

# Hash — object with addressable fields (update one field without full re-serialize)
await redis.hset("user:123", mapping={"name": "Alice", "email": "alice@example.com"})
await redis.hset("user:123", "last_login", datetime.now().isoformat())  # Update single field
user = await redis.hgetall("user:123")
await redis.expire("user:123", 300)

# Sorted Set — leaderboard, feed (score-ordered, efficient range queries)
await redis.zadd("leaderboard:weekly", {"user:123": 1500, "user:456": 2300})
top_10 = await redis.zrevrange("leaderboard:weekly", 0, 9, withscores=True)

# Set — tags, memberships, deduplication
await redis.sadd("user:123:roles", "admin", "editor")
is_admin = await redis.sismember("user:123:roles", "admin")

# List — recent activity, bounded logs (LPUSH + LTRIM)
await redis.lpush("user:123:activity", json.dumps(event))
await redis.ltrim("user:123:activity", 0, 99)  # Keep only last 100
```

### GOTCHA
Redis Hashes are more memory-efficient than Strings for small objects due to ziplist encoding (objects with < 128 fields and values < 64 bytes). But they don't support nested objects — you need to flatten or serialize nested fields. Use Strings (JSON) for complex nested objects, Hashes for flat objects with frequent partial updates.

---

## 6. Response Caching with ETags — Conditional GET (304 Not Modified)

### WHY
HTTP-level caching with ETags reduces bandwidth and server load. If the data hasn't changed, the server returns 304 Not Modified with no body — the client uses its cached copy. This works with browser caches, CDN edge caches, and API clients. The LLM never generates ETag support. The staff engineer uses ETags for GET endpoints that return data which changes infrequently.

### HOW
```python
import hashlib
from fastapi import Request, Response

@app.get("/products/{product_id}")
async def get_product(
    product_id: int,
    request: Request,
    response: Response,
    cache: redis.Redis = Depends(get_redis),
):
    product = await db.get_product(product_id)
    if not product:
        raise HTTPException(404)

    # Generate ETag from content hash
    content = json.dumps(product, sort_keys=True, default=str)
    etag = hashlib.md5(content.encode()).hexdigest()

    # Check If-None-Match header (client's cached ETag)
    client_etag = request.headers.get("if-none-match")
    if client_etag and client_etag.strip('"') == etag:
        return Response(status_code=304)  # Not Modified — no body sent

    # Return with ETag and Cache-Control headers
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "private, max-age=60"
    return product
```

### GOTCHA
Use `"private, max-age=60"` for user-specific data (browser can cache, CDN cannot). Use `"public, max-age=3600"` for shared data (CDN can cache). Never use `"public"` for authenticated endpoints — CDN might serve one user's data to another. The ETag must change when content changes — use a hash of the serialized response, not the DB timestamp (which might not change on idempotent updates).

---

## 7. Multi-Level Cache — In-Process (LRU) + Redis + CDN

### WHY
Redis round-trip is ~0.5ms on localhost, ~1-5ms over network. For hyper-hot data read thousands of times per second (feature flags, rate limit counters, config), even Redis becomes a bottleneck. Multi-level caching adds an in-process LRU cache (0.001ms, zero network) in front of Redis, with Redis in front of the database. Each level has a shorter TTL than the level below it.

### HOW
```python
from functools import lru_cache
from cachetools import TTLCache
import asyncio

class MultiLevelCache:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        # Level 1: In-process TTL cache (fast, small, per-worker)
        self.l1 = TTLCache(maxsize=1000, ttl=30)  # 30s TTL, max 1000 items
        self._lock = asyncio.Lock()

    async def get(self, key: str, fetch_fn, redis_ttl: int = 300) -> any:
        # L1: In-process cache (instant, no network)
        if key in self.l1:
            return self.l1[key]

        # L2: Redis cache (fast, shared across workers)
        cached = await self.redis.get(key)
        if cached is not None:
            value = json.loads(cached)
            self.l1[key] = value  # Promote to L1
            return value

        # L3: Database (slow, authoritative)
        value = await fetch_fn()
        # Populate L2 and L1
        await self.redis.set(key, json.dumps(value, default=str), ex=redis_ttl)
        self.l1[key] = value
        return value

    def invalidate(self, key: str):
        """Invalidate L1 immediately. L2 invalidated via TTL or explicit delete."""
        self.l1.pop(key, None)
        # L2 invalidation is async — fire and forget
        asyncio.create_task(self.redis.delete(key))
```

### GOTCHA
L1 cache is PER WORKER PROCESS. With 4 uvicorn workers, each has its own L1 with potentially different data. L1 TTL must be SHORT (10-30s) to minimize inconsistency between workers. If you invalidate in Redis, the other workers' L1 caches are stale until their L1 TTL expires. For strong consistency, skip L1 or use L1 only for truly immutable data.

---

## 8. Cache Key Design — namespace:entity:id:version

### WHY
Poor key design causes collisions (two different queries sharing a key), debugging hell (what does `cache:abc123` mean?), and impossible invalidation (how do you delete all cache entries for a specific user?). The staff engineer uses a structured key convention: `{namespace}:{entity}:{identifier}:{qualifier}`.

### HOW
```python
class CacheKeys:
    """Centralized cache key builder. Single source of truth for key format."""

    @staticmethod
    def user(user_id: int) -> str:
        return f"user:{user_id}"

    @staticmethod
    def user_list(page: int, per_page: int, sort: str = "created") -> str:
        return f"users:list:p{page}:pp{per_page}:s{sort}"

    @staticmethod
    def user_roles(user_id: int) -> str:
        return f"user:{user_id}:roles"

    @staticmethod
    def product(product_id: int, locale: str = "en") -> str:
        return f"product:{product_id}:locale:{locale}"

    @staticmethod
    def config(key: str, version: int = 1) -> str:
        return f"config:{key}:v{version}"

    @staticmethod
    def rate_limit(user_id: str, endpoint: str) -> str:
        return f"rl:{user_id}:{endpoint}"

# Usage
key = CacheKeys.user(123)            # "user:123"
key = CacheKeys.product(456, "pt")   # "product:456:locale:pt"
key = CacheKeys.rate_limit("u1", "POST:/api/submit")  # "rl:u1:POST:/api/submit"

# Pattern-based invalidation (delete all user list caches)
async for key in redis.scan_iter(match="users:list:*"):
    await redis.delete(key)
```

### GOTCHA
Never use `KEYS pattern` in production — it is O(N) and blocks Redis. Always use `SCAN` for pattern-based operations. Keep keys short (Redis stores keys in memory) but readable. Avoid special characters that Redis treats specially (spaces, newlines). Colons (`:`) are the standard delimiter by convention.

---

## 9. Distributed Lock with Redis (SET NX EX + Lua for Release)

### WHY
Sometimes you need mutual exclusion across multiple workers: only one worker processes a specific job, only one request refreshes a cache entry, only one cron job runs cleanup. Redis SET with NX (not exists) and EX (expiry) creates a lock atomically. The Lua script for release ensures only the lock owner can release it (prevents one worker from releasing another's lock).

### HOW
```python
import uuid

RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

class RedisLock:
    def __init__(self, redis_client: redis.Redis, name: str, ttl: int = 30):
        self.redis = redis_client
        self.key = f"lock:{name}"
        self.ttl = ttl
        self.token = str(uuid.uuid4())  # Unique owner identifier
        self._release_script = self.redis.register_script(RELEASE_LOCK_SCRIPT)

    async def acquire(self) -> bool:
        """Acquire lock. Returns True if acquired, False if already held."""
        return await self.redis.set(self.key, self.token, nx=True, ex=self.ttl)

    async def release(self) -> bool:
        """Release lock. Only succeeds if we still own it."""
        result = await self._release_script(keys=[self.key], args=[self.token])
        return bool(result)

    async def __aenter__(self):
        acquired = await self.acquire()
        if not acquired:
            raise LockNotAcquired(f"Could not acquire lock: {self.key}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()

# Usage
async def process_unique_job(job_id: str, redis: redis.Redis):
    lock = RedisLock(redis, f"job:{job_id}", ttl=60)
    try:
        async with lock:
            await do_work(job_id)
    except LockNotAcquired:
        pass  # Another worker is handling it
```

### GOTCHA
The lock TTL is a safety valve, not a feature. If the lock holder crashes, the lock auto-releases after TTL seconds. Set TTL longer than the expected operation time but not too long (job takes 5s -> TTL 30s). If the operation can exceed TTL, implement lock renewal (extend TTL while still working). Never use `DEL` to release — always use the Lua script to check ownership first.

---

## 10. Cache Warming on Deploy — Preload Hot Data

### WHY
After a deploy, cache is cold. The first requests after deploy all miss the cache and hit the database simultaneously. For high-traffic applications, this cold-start spike can overwhelm the database. Cache warming preloads the most frequently accessed data into Redis during startup, before the server starts accepting traffic.

### HOW
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm cache BEFORE accepting traffic
    redis = await get_redis_pool()
    await warm_cache(redis)
    yield
    await redis.close()

async def warm_cache(redis: redis.Redis):
    """Preload hot data into cache during startup."""
    import logging
    logger = logging.getLogger("cache.warm")

    # 1. Feature flags (read on every request)
    flags = await db.get_all_feature_flags()
    await redis.set("config:feature_flags", json.dumps(flags), ex=CacheTTL.STANDARD)
    logger.info(f"Warmed {len(flags)} feature flags")

    # 2. Top products (most viewed)
    top_products = await db.get_top_products(limit=100)
    pipe = redis.pipeline()
    for p in top_products:
        pipe.set(f"product:{p['id']}", json.dumps(p), ex=CacheTTL.WARM)
    await pipe.execute()
    logger.info(f"Warmed {len(top_products)} top products")

    # 3. Rate limit config
    rl_config = await db.get_rate_limit_config()
    await redis.set("config:rate_limits", json.dumps(rl_config), ex=CacheTTL.STANDARD)
    logger.info("Warmed rate limit config")
```

### GOTCHA
Cache warming adds to startup time. If warming takes 30 seconds, your health check must account for it (`/health/startup` should return 503 until warming completes). Use Redis pipelines for bulk inserts — 100 individual SET commands take ~50ms, a pipeline with 100 SETs takes ~1ms. Never warm user-specific data — warm only shared, high-read data.
