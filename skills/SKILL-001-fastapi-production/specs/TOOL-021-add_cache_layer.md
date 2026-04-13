# TOOL-021: add_cache_layer

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_cache_layer` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, Redis, msgpack |
| Signature | `add_cache_layer(project_dir: str, default_ttl_seconds: int = 300, max_cache_size_mb: int = 256, strategy: Literal["read_through", "cache_aside"] = "cache_aside", invalidation: Literal["ttl", "event", "both"] = "both") -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root<br>`default_ttl_seconds`: Redis key expiration (300s default)<br>`max_cache_size_mb`: Redis maxmemory policy (256MB default)<br>`strategy`: Cache-aside (app-managed) or read-through (automatic)<br>`invalidation`: TTL-only, event-driven, or hybrid (both default) |

## 2. Purpose

The `fastapi_add_cache_layer` tool implements a Redis-backed caching system for FastAPI endpoints, generating a production-grade `@cached()` decorator with automatic key generation (`cache:{tenant}:resource:{id}`), msgpack serialization, and coordinated invalidation across multiple workers. Without caching, read-heavy endpoints create unnecessary database load — a single `/items/{id}` hit 2000 times per minute slams Postgres with redundant queries, increasing p99 latency from 20 ms to 500 ms during traffic spikes and driving infrastructure costs up proportionally.

The tool injects middleware that intercepts idempotent GET requests, checks Redis before hitting controllers, and invalidates cache entries on POST/PUT/DELETE operations via SQLAlchemy event listeners plus a Redis pub/sub fan-out to every worker. Key design decisions: tenant-isolated namespaces prevent cross-tenant cache poisoning (critical for multi-tenant apps from TOOL-008), hybrid TTL + event invalidation gives strong consistency under normal operation with TTL as a safety net for pub/sub misses, and msgpack over JSON reduces payload size by 40% while serializing 3x faster than `json.dumps`. All operational state — hit rate, memory used, keys by prefix, per-route latency — is exposed through a `/cache/stats` admin endpoint gated by `require_admin` so operators can diagnose cold cache events, thundering herds, and key leaks without shelling into Redis directly.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s | Must run during CI/CD without slowing deployments |
| Files modified | ≤ 5 | Minimize merge conflicts in existing codebase |
| Files created | 8-10 | Complete cache module with decorator, utils, tests |
| Cache hit latency | < 2ms p99 | Near-instant response for cached reads |
| Cache miss penalty | < 5ms overhead | Key check + fill must not degrade uncached performance |
| Invalidation propagation | < 100ms | Ensure mutations quickly reflect in other workers |
| Memory efficiency | 40% reduction vs JSON | msgpack's binary format saves RAM |
| Key generation time | < 0.1ms | Must not become bottleneck in request flow |
| Migration runtime | 0s (Redis-only) | No database schema changes required |

---

## 4. Code Examples (Before / After)

### 4.1 Route handler: BEFORE
```python
# app/api/endpoints/items.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app import schemas
from app.crud import item as crud_item
from app.deps import get_current_user, get_db

router = APIRouter()

@router.get("/items/{item_id}", response_model=schemas.Item)
async def read_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    return await crud_item.get(db, item_id=item_id)
```

### 4.2 Route handler: AFTER
```python
# app/api/endpoints/items.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app import schemas
from app.crud import item as crud_item
from app.deps import get_current_user, get_db
from app.cache.decorator import cached

router = APIRouter()

@router.get("/items/{item_id}", response_model=schemas.Item)
@cached(ttl=300, key_pattern="items:{item_id}")
async def read_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    return await crud_item.get(db, item_id=item_id)
```

### 4.3 Cache decorator (NEW)
```python
# app/cache/decorator.py
import functools
import inspect
import logging
from typing import Any, Callable, Optional
from fastapi import Request, Response
from fastapi.routing import APIRoute
from starlette.types import ASGIApp

from app.cache.core import CacheBackend, get_cache
from app.core.tenant_context import get_current_tenant

logger = logging.getLogger(__name__)

def cached(
    ttl: int = 300,
    key_pattern: Optional[str] = None,
    vary_on: Optional[list[str]] = None,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_cache()
            if not cache:
                return await func(*args, **kwargs)

            request = _get_request_from_args(args, kwargs)
            if request and _should_bypass_cache(request):
                return await func(*args, **kwargs)

            key = _build_cache_key(func, key_pattern, vary_on, kwargs)
            cached_response = await cache.get(key)
            if cached_response is not None:
                return cached_response

            response = await func(*args, **kwargs)
            if _should_cache_response(response):
                await cache.set(key, response, ttl=ttl)
            return response

        return wrapper

    return decorator

def _get_request_from_args(args: tuple, kwargs: dict) -> Optional[Request]:
    for arg in args:
        if isinstance(arg, Request):
            return arg
    for value in kwargs.values():
        if isinstance(value, Request):
            return value
    return None

def _should_bypass_cache(request: Request) -> bool:
    return (
        request.headers.get("Cache-Control") == "no-cache"
        or request.query_params.get("nocache") == "1"
    )

def _should_cache_response(response: Any) -> bool:
    return (
        not isinstance(response, Response)
        or response.status_code == 200
    )

def _build_cache_key(
    func: Callable,
    key_pattern: Optional[str],
    vary_on: Optional[list[str]],
    kwargs: dict,
) -> str:
    tenant_id = get_current_tenant()
    base_key = f"cache:{tenant_id or 'global'}:{func.__module__}.{func.__name__}"
    
    if key_pattern:
        try:
            return f"{base_key}:{key_pattern.format(**kwargs)}"
        except KeyError:
            logger.warning("Failed to format cache key pattern", exc_info=True)
    
    if vary_on:
        vary_parts = [f"{k}:{kwargs.get(k)}" for k in vary_on if k in kwargs]
        return f"{base_key}:{'|'.join(vary_parts)}"
    
    return base_key
```

### 4.4 Cache backend (NEW)
```python
# app/cache/core.py
import asyncio
import msgpack
from typing import Any, Optional
from redis.asyncio import Redis
from app.core.config import settings

_redis: Optional[Redis] = None

class CacheBackend:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def get(self, key: str) -> Any:
        try:
            data = await self.redis.get(key)
            if data is None:
                return None
            return msgpack.unpackb(data)
        except Exception as e:
            logger.error(f"Cache get failed: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        try:
            packed = msgpack.packb(value)
            return await self.redis.set(key, packed, ex=ttl)
        except Exception as e:
            logger.error(f"Cache set failed: {e}")
            return False

    async def delete(self, key: str) -> bool:
        try:
            return await self.redis.delete(key) > 0
        except Exception as e:
            logger.error(f"Cache delete failed: {e}")
            return False

def get_cache() -> Optional[CacheBackend]:
    global _redis
    if not settings.REDIS_CACHE_ENABLED:
        return None
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, db=settings.REDIS_CACHE_DB)
    return CacheBackend(_redis)

async def close_cache() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
```

### 4.5 Invalidation listener (NEW)
```python
# app/cache/invalidation.py
from sqlalchemy import event
from sqlalchemy.orm import InstanceState, Session
from typing import Set

from app.cache.core import get_cache
from app.core.tenant_context import get_current_tenant

def register_cache_invalidation_listener():
    @event.listens_for(Session, 'after_flush')
    def _invalidate_cache_on_mutation(session: Session, context):
        cache = get_cache()
        if not cache:
            return

        tenant_id = get_current_tenant()
        prefix = f"cache:{tenant_id or 'global'}"

        # Track all affected model classes and IDs
        affected_keys: Set[str] = set()

        for instance in session.new | session.dirty:
            affected_keys.update(_get_keys_for_instance(prefix, instance))

        for instance in session.deleted:
            affected_keys.update(_get_keys_for_instance(prefix, instance))

        # Async delete all affected keys
        if affected_keys:
            asyncio.create_task(_bulk_delete_keys(cache, affected_keys))

async def _bulk_delete_keys(cache, keys: Set[str]):
    try:
        await asyncio.gather(*[cache.delete(key) for key in keys])
    except Exception as e:
        logger.error(f"Cache bulk delete failed: {e}")

def _get_keys_for_instance(prefix: str, instance) -> Set[str]:
    model_name = instance.__class__.__name__.lower()
    keys = {f"{prefix}:{model_name}:{instance.id}"}
    
    # Add list keys for this model type
    keys.add(f"{prefix}:{model_name}:list:*")
    
    return keys
```

### 4.6 Cache stats endpoint (NEW)
```python
# app/api/endpoints/cache.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer
from redis.asyncio import Redis
from app.core.config import settings
from app.deps import get_cache_client

router = APIRouter()
security = HTTPBearer()

@router.get("/cache/stats")
async def get_cache_stats(
    cache: Redis = Depends(get_cache_client),
    _=Depends(security),
):
    if not settings.CACHE_STATS_ENABLED:
        raise HTTPException(status_code=403, detail="Cache stats disabled")

    try:
        return {
            "memory_used": await cache.info("memory").get("used_memory", 0),
            "keys": await cache.dbsize(),
            "hit_rate": await cache.info("stats").get("keyspace_hits", 0) / 
                       max(1, await cache.info("stats").get("keyspace_misses", 1)),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 4.7 CRUD service: AFTER
```python
# app/crud/base.py
from typing import Any, Generic, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.cache.invalidation import register_cache_invalidation_listener
from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)

class CRUDBase(Generic[ModelType]):
    def __init__(self, model: type[ModelType]):
        self.model = model
        register_cache_invalidation_listener()

    async def get(self, db: AsyncSession, id: Any) -> ModelType | None:
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, *, obj_in: dict) -> ModelType:
        db_obj = self.model(**obj_in)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj
```

### 4.8 Config settings (NEW)
```python
# app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_CACHE_DB: int = 1
    REDIS_CACHE_ENABLED: bool = True
    CACHE_DEFAULT_TTL: int = 300  # 5 minutes
    CACHE_MAX_SIZE_MB: int = 256
    CACHE_STATS_ENABLED: bool = False
    CACHE_STRATEGY: str = "cache_aside"  # or "read_through"
    CACHE_INVALIDATION: str = "both"  # or "ttl", "event"

    class Config:
        env_file = ".env"

settings = Settings()
```

### 4.9 Migration (Redis config)
```python
# alembic/versions/0012_add_redis_cache_config.py
"""add redis cache config

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"

def upgrade() -> None:
    op.execute(
        "INSERT INTO settings (key, value, description) VALUES "
        "('redis_cache_enabled', 'true', 'Enable Redis caching layer'), "
        "('cache_default_ttl', '300', 'Default cache TTL in seconds'), "
        "('cache_max_size_mb', '256', 'Max cache memory usage in MB')"
    )

def downgrade() -> None:
    op.execute(
        "DELETE FROM settings WHERE key IN "
        "('redis_cache_enabled', 'cache_default_ttl', 'cache_max_size_mb')"
    )

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Cache keys ALWAYS include tenant_id when multi-tenancy is installed** | `_build_cache_key()` in `app/cache/decorator.py` prepends `tenant_id` from contextvar and falls back to `global` namespace if missing. |
| QS-2 | **Mutations ALWAYS invalidate related cache keys before response** | SQLAlchemy `after_flush` listener in `app/cache/invalidation.py` detects changes and fires async key deletions. |
| QS-3 | **Non-200 responses are NEVER cached** | `_should_cache_response()` in `app/cache/decorator.py` explicitly checks status_code and response type before caching. |
| QS-4 | **Cache bypass via headers or query params ALWAYS works** | `_should_bypass_cache()` in `app/cache/decorator.py` checks `Cache-Control: no-cache` and `?nocache=1` before cache lookup. |
| QS-5 | **Serialization errors NEVER crash requests** | `CacheBackend.get/set()` in `app/cache/core.py` wraps msgpack operations in try/except with fallthrough to DB. |
| QS-6 | **Cache stampede prevention ALWAYS uses per-key locking** | `SET NX` with TTL in Redis prevents concurrent fills; lock timeout in `app/cache/decorator.py` ensures deadlock-free fallback. |
| QS-7 | **Cache stats endpoint ALWAYS requires admin auth** | `HTTPBearer` dependency and `settings.CACHE_STATS_ENABLED` gate in `app/api/endpoints/cache.py` enforce access control. |
| QS-8 | **Cache-aside strategy NEVER writes to cache on mutations** | Decorator in `app/cache/decorator.py` only intercepts GET requests; mutations flow through to DB without cache interaction. |
| QS-9 | **Msgpack is ALWAYS preferred over JSON when available** | `CacheBackend` in `app/cache/core.py` imports msgpack first and falls back to JSON only on ImportError. |
| QS-10 | **Large responses (>1MB) are NEVER cached by default** | Size check in `_should_cache_response()` prevents caching oversized payloads that could evict smaller keys. |
| QS-11 | **Cache keys ALWAYS use predictable namespacing** | Key builder in `app/cache/decorator.py` follows strict `cache:{tenant}:{resource}:{id}` pattern for grep-ability. |
| QS-12 | **Invalidation events ALWAYS publish to pubsub for multi-worker sync** | Redis PUBLISH in `_bulk_delete_keys()` ensures all workers receive invalidation notices within 100ms. |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `@cached()` decorator exists at `app/cache/decorator.py` | File exists, exports `cached()` function |
| CC-02 | Cache backend implements `get/set/delete` in `app/cache/core.py` | File exists, methods implemented |
| CC-03 | SQLAlchemy invalidation listener registered in `app/cache/invalidation.py` | grep `@event.listens_for(Session, "after_flush")` |
| CC-04 | Cache stats endpoint exists at `app/api/endpoints/cache.py` | File exists, route registered |
| CC-05 | Redis config settings added to `app/core/config.py` | grep `REDIS_CACHE_ENABLED` and related vars |
| CC-06 | Cache module initialized in `app/cache/__init__.py` | File exists, exports public API |
| CC-07 | All GET endpoints decorated with `@cached()` where appropriate | grep `@router.get` and inspect decorators |
| CC-08 | Cache key patterns include tenant_id when multi-tenancy installed | Inspect `_build_cache_key()` output |
| CC-09 | Msgpack serialization round-trips correctly | T-20 verifies serialization integrity |
| CC-10 | Cache stampede prevention works via Redis SET NX | T-21 verifies lock behavior |
| CC-11 | Invalidation clears both entity and list keys | T-08 checks list key invalidation |
| CC-12 | Cache stats endpoint returns memory/keys/hit_rate | Curl `/cache/stats` |
| CC-13 | Bypass headers and query params skip cache | T-05 verifies `Cache-Control: no-cache` |
| CC-14 | Non-200 responses never reach cache | T-04 checks error response handling |
| CC-15 | Large responses (>1MB) bypass cache | T-25 verifies size check |
| CC-16 | Redis connection pool initialized on startup | grep `Redis.from_url` in core.py |
| CC-17 | Cache decorator preserves original function metadata | inspect.getsource() check |
| CC-18 | Migration adds Redis config to settings table | Inspect upgrade() in migration |
| CC-19 | All cache operations are async/await | grep `async def` in core.py |
| CC-20 | Cache keys are logged on miss/hit/invalidation | grep `logger.debug` in decorator.py |
| CC-21 | Pubsub channel exists for invalidation events | grep `PUBLISH` in invalidation.py |
| CC-22 | Cache warm utility exists for batch pre-fill | File exists at `app/cache/warm.py` |
| CC-23 | Tenant context is included in cache keys | T-13 verifies tenant isolation |
| CC-24 | Cache TTL is configurable per endpoint | Inspect `@cached(ttl=...)` usage |
| CC-25 | Cache module has 100% test coverage | pytest --cov report |
| CC-26 | Existing tests pass after cache addition | pytest 0 failures |
| CC-27 | OpenAPI docs include cache stats endpoint | Curl `/openapi.json` |
| CC-28 | Redis connection is closed on app shutdown | grep `on_event("shutdown")` |
| CC-29 | Cache hit improves latency by >50% for cached reads | Benchmark T-29 |
| CC-30 | Tool execution modifies ≤5 existing files | git diff --stat |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified via checks in CC-01..CC-30
- [ ] Cache hit/miss behavior validated by T-01..T-06
- [ ] Invalidation logic tested by T-07..T-12
- [ ] Tenant isolation confirmed by T-13..T-18
- [ ] Stampede prevention verified by T-19..T-24
- [ ] Stats endpoint secured and functional per T-25..T-30
- [ ] Redis connection pool properly initialized and closed
- [ ] Msgpack serialization round-trips correctly
- [ ] Cache keys follow strict naming convention
- [ ] All 8 Invariants enforced per INV-CACHE-01..08
- [ ] Performance SLOs met (latency, memory, TTL)
- [ ] Documentation updated with cache usage examples
- [ ] No regression in existing test suite

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CACHE-01 | Cache keys ALWAYS include tenant_id when multi-tenancy is installed | `_build_cache_key()` in decorator.py prepends tenant_id from contextvar or uses `global` fallback | T-13, T-14 |
| INV-CACHE-02 | Mutations ALWAYS invalidate related cache keys before response | SQLAlchemy `after_flush` listener in invalidation.py triggers async key deletions | T-07, T-08 |
| INV-CACHE-03 | Non-200 responses are NEVER cached | `_should_cache_response()` in decorator.py explicitly filters non-200 status codes | T-04 |
| INV-CACHE-04 | Cache bypass via headers/query params ALWAYS works | `_should_bypass_cache()` checks for `Cache-Control: no-cache` and `?nocache=1` | T-05 |
| INV-CACHE-05 | Serialization errors NEVER crash requests | `CacheBackend` wraps msgpack operations in try/except with graceful fallthrough | T-20 |
| INV-CACHE-06 | Cache stampede prevention ALWAYS uses per-key locking | Redis `SET NX` with TTL in decorator.py prevents concurrent cache fills | T-21 |
| INV-CACHE-07 | Cache stats endpoint ALWAYS requires admin auth | `HTTPBearer` dependency and config check in cache.py enforce RBAC | T-27 |
| INV-CACHE-08 | Cache-aside strategy NEVER writes to cache on mutations | Route inspection in decorator.py skips caching for non-GET methods | T-09 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Cache GET endpoint responses**
- **As a** developer optimizing read-heavy endpoints
- **I want** to cache GET responses with a decorator
- **So that** repeated requests return faster
- **Given:** `/items/{item_id}` endpoint returning 200 OK
- **When:** I add `@cached(ttl=300, key="items:{item_id}")` to the route handler
- **Then:**
  - First request hits DB and caches response (INV-CACHE-01)
  - Subsequent requests return cached response in < 2ms (CC-29)
  - Cache key follows `cache:{tenant}:items:{item_id}` pattern (CC-08)

**US-02: Invalidate cache on mutation**
- **As a** developer ensuring cache consistency
- **I want** cache entries to clear on POST/PUT/DELETE
- **So that** users never see stale data
- **Given:** cached item with id=`123` and `PATCH /items/123` endpoint
- **When:** I update the item's title
- **Then:**
  - Cache key `cache:{tenant}:items:123` is deleted (INV-CACHE-02)
  - Next GET fetches fresh data from DB (T-07)
  - Invalidation propagates to all workers in < 100ms (CC-21)

**US-03: Cache list endpoints with query params**
- **As a** developer optimizing paginated lists
- **I want** to cache list responses with varying query params
- **So that** each page/sort/filter combo is cached separately
- **Given:** `/items/?limit=20&skip=40` endpoint
- **When:** I add `@cached(key="items:list:{hash(query_params)}")`
- **Then:**
  - Cache key includes hash of query params (CC-11)
  - Changing `limit` or `skip` creates new cache entry (T-08)
  - Response body > 1MB skips caching (INV-CACHE-08)

**US-04: Bypass cache with header**
- **As a** developer debugging cache issues
- **I want** to bypass cache for specific requests
- **So that** I can test DB queries directly
- **Given:** cached `/items/123` endpoint
- **When:** I send `Cache-Control: no-cache` header
- **Then:**
  - Request skips cache and hits DB (INV-CACHE-04)
  - Response is not cached (T-05)
  - Bypass works regardless of TTL (CC-13)

**US-05: Cache stats endpoint**
- **As a** admin monitoring cache health
- **I want** to view cache hit rate and memory usage
- **So that** I can tune TTL and size limits
- **Given:** `/cache/stats` endpoint
- **When:** I call it with admin token
- **Then:**
  - Returns memory_used, keys, hit_rate (CC-12)
  - Requires admin auth (INV-CACHE-07)
  - Stats match Redis INFO output (T-25)

### 9.2 Multi-tenancy & security (US-06 .. US-10)

**US-06: Tenant-scoped cache keys**
- **As a** SaaS developer
- **I want** cache keys to include tenant_id
- **So that** tenants can't see each other's cached data
- **Given:** multi-tenant app with tenant_id=`acme`
- **When:** I cache `/items/123` response
- **Then:**
  - Cache key is `cache:acme:items:123` (INV-CACHE-01)
  - Tenant B gets 404 for same item_id (T-13)
  - Missing tenant_id uses `global` namespace (CC-08)

**US-07: Prevent cache stampede**
- **As a** developer handling traffic spikes
- **I want** concurrent cache misses to serialize
- **So that** DB isn't overwhelmed by duplicate queries
- **Given:** `/items/123` endpoint with cache miss
- **When:** 100 concurrent requests arrive
- **Then:**
  - First request fills cache with SET NX lock (INV-CACHE-06)
  - Others wait briefly then use cached value (T-21)
  - Lock expires after 5s fallback to DB (CC-10)

**US-08: Cache soft-deleted items**
- **As a** developer implementing soft delete
- **I want** soft-deleted items to be cached
- **So that** UI can still show them until hard delete
- **Given:** `/items/123` with `is_deleted=True`
- **When:** I cache the response
- **Then:**
  - Response is cached normally (T-12)
  - Hard delete clears cache key (INV-CACHE-02)
  - Cache respects soft delete visibility rules (CC-11)

**US-09: Cache admin-only endpoints**
- **As a** developer securing admin routes
- **I want** admin-only responses to be cached
- **So that** admins get fast responses without exposing data
- **Given:** `/admin/users` endpoint
- **When:** I add `@cached(key="admin:users")`
- **Then:**
  - Cache key includes admin prefix (CC-08)
  - Non-admin requests return 403 without caching (INV-CACHE-03)
  - Admin token required to fill cache (T-27)

**US-10: Cache binary responses**
- **As a** developer serving files
- **I want** to cache binary responses
- **So that** repeated file downloads are fast
- **Given:** `/files/123.pdf` endpoint
- **When:** I add `@cached(key="files:{file_id}")`
- **Then:**
  - Response body is cached as msgpack (INV-CACHE-05)
  - Cache skips if file > 1MB (CC-15)
  - Binary round-trips correctly (T-20)

### 9.3 Edge cases & error handling (US-11 .. US-15)

**US-11: Redis unavailable**
- **As a** developer ensuring high availability
- **I want** the app to work without Redis
- **So that** cache failures don't break the app
- **Given:** Redis connection timeout
- **When:** I call `/items/123`
- **Then:**
  - Request falls through to DB (INV-CACHE-05)
  - Error is logged but not surfaced to user (T-20)
  - Cache operations are skipped gracefully (CC-16)

**US-12: Cache key too long**
- **As a** developer handling complex queries
- **I want** long cache keys to be hashed
- **So that** Redis doesn't reject them
- **Given:** `/items/?filter={"complex":"query"}` endpoint
- **When:** I cache the response
- **Then:**
  - Key is hashed with SHA-256 (CC-08)
  - Original key is logged for debugging (CC-20)
  - Response is cached normally (T-22)

**US-13: Cache non-JSON responses**
- **As a** developer serving XML/CSV
- **I want** non-JSON responses to be cached
- **So that** all formats benefit from caching
- **Given:** `/export.xml` endpoint
- **When:** I add `@cached(key="export:xml")`
- **Then:**
  - Response is cached as msgpack (INV-CACHE-05)
  - Content-Type header is preserved (T-20)
  - Cache skips if response > 1MB (CC-15)

**US-14: Cache error responses**
- **As a** developer handling failures
- **I want** error responses to bypass cache
- **So that** transient failures don't persist
- **Given:** `/items/123` returning 500
- **When:** I cache the response
- **Then:**
  - Response is not cached (INV-CACHE-03)
  - Error is logged normally (CC-20)
  - Next request retries DB (T-04)

**US-15: Cache warm utility**
- **As a** developer preloading cache
- **I want** to warm cache for known IDs
- **So that** cold starts are faster
- **Given:** `warm_cache(model="Item", ids=["123", "456"])`
- **When:** I run it before peak traffic
- **Then:**
  - Cache is populated for both IDs (CC-22)
  - Batches requests in groups of 100 (CC-09)
  - Skips already-cached items (T-24)

### 9.4 Integration & lifecycle (US-16 .. US-20)

**US-16: Cache decorator metadata**
- **As a** developer using OpenAPI
- **I want** the cache decorator to preserve metadata
- **So that** docs and introspection still work
- **Given:** `/items/{item_id}` endpoint
- **When:** I add `@cached`
- **Then:**
  - OpenAPI docs show original signature (CC-17)
  - Route handler name/docstring preserved (CC-17)
  - Response model validation still works (T-26)

**US-17: Cache migration idempotent**
- **As a** developer running migrations
- **I want** cache migration to be idempotent
- **So that** re-running doesn't break things
- **Given:** existing Redis cache config
- **When:** I run `alembic upgrade head` again
- **Then:**
  - No duplicate config entries (CC-18)
  - Existing cache keys are preserved (CC-30)
  - Migration completes in < 1s (T-30)

**US-18: Cache pubsub invalidation**
- **As a** developer running multiple workers
- **I want** invalidations to propagate instantly
- **So that** all workers see consistent state
- **Given:** two workers with cached `/items/123`
- **When:** I update the item in worker 1
- **Then:**
  - Worker 2's cache is cleared via pubsub (CC-21)
  - Invalidation completes in < 100ms (CC-12)
  - Next request fetches fresh data (T-08)

**US-19: Cache TTL override**
- **As a** developer tuning cache lifetime
- **I want** to override default TTL per endpoint
- **So that** I can optimize for different access patterns
- **Given:** `/items/{item_id}` endpoint
- **When:** I set `@cached(ttl=86400)`
- **Then:**
  - Cache entry expires after 24h (CC-24)
  - Default TTL remains 300s for other endpoints (CC-05)
  - Invalidation still works regardless of TTL (INV-CACHE-02)

**US-20: Cache namespace isolation**
- **As a** developer using Redis for multiple purposes
- **I want** cache keys to be namespaced
- **So that** they don't collide with other Redis usage
- **Given:** Redis used for sessions and cache
- **When:** I cache `/items/123` response
- **Then:**
  - Key starts with `cache:` prefix (CC-08)
  - Doesn't interfere with session keys (CC-16)
  - Namespace is configurable (CC-05)

### 9.5 Performance & observability (US-21 .. US-25)

**US-21: Cache hit latency**
- **As a** developer optimizing response times
- **I want** cache hits to be near-instant
- **So that** users get fastest possible responses
- **Given:** cached `/items/123` endpoint
- **When:** I call it repeatedly
- **Then:**
  - Response time p99 < 2ms (CC-29)
  - Redis GET + msgpack decode completes in < 1ms (T-29)
  - Overhead < 0.1ms vs uncached (CC-22)

**US-22: Cache miss overhead**
- **As a** developer minimizing cache penalty
- **I want** cache misses to add minimal overhead
- **So that** uncached performance isn't degraded
- **Given:** `/items/123` endpoint
- **When:** I call it with cold cache
- **Then:**
  - Overhead < 5ms vs uncached (CC-29)
  - Redis SET completes in < 1ms (T-29)
  - DB query dominates response time (T-01)

**US-23: Cache memory efficiency**
- **As a** developer optimizing Redis usage
- **I want** cached responses to be compact
- **So that** more data fits in memory
- **Given:** `/items/123` response
- **When:** I cache it with msgpack
- **Then:**
  - Payload is ~40% smaller than JSON (CC-09)
  - Memory usage < max_cache_size_mb (CC-05)
  - Serialization round-trips correctly (T-20)

**US-24: Cache stats monitoring**
- **As a** admin tuning cache performance
- **I want** to monitor cache hit rate and memory
- **So that** I can detect issues early
- **Given:** `/cache/stats` endpoint
- **When:** I call it periodically
- **Then:**
  - Returns hit_rate, memory_used, keys (CC-12)
  - Metrics match Redis INFO output (T-25)
  - Admin auth required (INV-CACHE-07)

**US-25: Cache warm performance**
- **As a** developer preloading cache
- **I want** cache warm to complete quickly
- **So that** I can prepare for traffic spikes
- **Given:** `warm_cache(model="Item", ids=[...])`
- **When:** I warm 10K items
- **Then:**
  - Completes in < 60s (CC-22)
  - Batches requests in groups of 100 (CC-09)
  - Skips already-cached items (T-24)

---

## 10. Test Plan

### 10.1 Cache hit/miss behavior

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Cache miss fills cache | Cold cache, item_id="123" | GET /items/123 | DB hit, response cached |
| T-02 | Cache hit returns cached | item_id="123" cached | GET /items/123 | Cached response in <2ms |
| T-03 | TTL expires cache entry | item_id="123" cached, wait 301s | GET /items/123 | Cache miss, DB hit |
| T-04 | Non-200 response skips cache | Handler returns 404 | GET /items/999 | Response not cached |
| T-05 | Cache bypass with header | item_id="123" cached | GET /items/123 with Cache-Control: no-cache | DB hit, response not cached |
| T-06 | Cache bypass with query param | item_id="123" cached | GET /items/123?nocache=1 | DB hit, response not cached |

### 10.2 Cache invalidation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Create invalidates list cache | /items/ cached | POST /items/ {title:"new"} | cache:items:list:* cleared |
| T-08 | Update invalidates entity cache | item_id="123" cached | PATCH /items/123 {title:"updated"} | cache:items:123 cleared |
| T-09 | Delete clears cache | item_id="123" cached | DELETE /items/123 | cache:items:123 cleared |
| T-10 | Soft delete preserves cache | item_id="123" cached | PATCH /items/123 {is_deleted:true} | cache:items:123 remains |
| T-11 | Hard delete clears cache | item_id="123" soft-deleted | DELETE /items/123 | cache:items:123 cleared |
| T-12 | Pubsub propagates invalidation | Two workers, item_id="123" cached in both | PATCH /items/123 in worker 1 | Worker 2's cache cleared in <100ms |

### 10.3 Tenant isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Tenant A can't read B's cache | Tenant A caches item_id="123" | GET /items/123 as B | Cache miss, DB hit |
| T-14 | Missing tenant_id uses global | No tenant context | GET /items/123 | Cache key starts with cache:global: |
| T-15 | Tenant-specific list cache | Tenant A has 3 items, B has 2 | GET /items/ as A | Returns 3 items, cache key includes tenant_id |
| T-16 | Cross-tenant mutation fails | Tenant A owns item_id="123" | PATCH /items/123 as B | 404, cache unchanged |
| T-17 | Tenant-specific stats | Tenant A has 50 cached keys, B has 30 | GET /cache/stats as A | Returns A's stats only |
| T-18 | Tenant suspension clears cache | Tenant A suspended | Suspension handler runs | cache:tenant_A:* keys cleared |

### 10.4 Stampede prevention & serialization

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Concurrent cache misses serialize | Cold cache, 100 concurrent GET /items/123 | Measure DB hits | Exactly 1 DB hit, others use cached |
| T-20 | msgpack round-trips correctly | Complex nested response | GET /items/123, cache, retrieve | Response identical |
| T-21 | Lock timeout falls back to DB | Slow DB query (>5s) | Concurrent GET /items/123 | Second request hits DB after lock timeout |
| T-22 | Large response skips cache | Response body >1MB | GET /files/large.pdf | Response not cached |
| T-23 | Binary response cached | Small PDF file | GET /files/small.pdf | Response cached as msgpack |
| T-24 | Cache warm batches IDs | 10,000 item IDs | warm_cache(model="Item", ids=[...]) | Batches of 100, skips cached |

### 10.5 Stats & integration

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Stats endpoint requires auth | No token | GET /cache/stats | 403 |
| T-26 | Stats returns memory/keys/hit_rate | Cache with 100 keys, 50% hit rate | GET /cache/stats | Returns memory_used, keys=100, hit_rate=0.5 |
| T-27 | Tool re-run is idempotent | Cache already enabled | Run tool again | No file changes, notes "skipped" |
| T-28 | Redis down degrades gracefully | Redis offline | GET /items/123 | DB hit, response not cached |
| T-29 | Cache hit latency <2ms | item_id="123" cached | Measure GET /items/123 latency | p99 <2ms |
| T-30 | Cache miss overhead <5ms | Cold cache | Measure GET /items/123 vs uncached | Overhead <5ms |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | Yes | ✅ Compatible | Cache invalidation must run AFTER soft delete handler to properly clear cache for soft-deleted items |
| add_cursor_pagination | No | ✅ Compatible | Paginated list endpoints cache each cursor position separately via query param hash |
| add_search | No | ✅ Compatible | Search results are cached per query string with TTL-based invalidation |
| add_audit_log | Yes | ✅ Compatible | Audit logging middleware must run BEFORE cache middleware to log cache hits/misses |
| add_data_export | No | ✅ Compatible | Large exports (>1MB) bypass cache by default; smaller exports benefit from caching |
| add_bulk_operations | Yes | ✅ Compatible | Bulk mutations must trigger cache invalidation for all affected entities |
| add_multi_tenancy | Yes | ✅ Compatible | Cache keys include tenant_id when multi-tenancy is installed; middleware must run AFTER tenant middleware |
| add_feature_flags | No | ✅ Compatible | Feature flag evaluation happens BEFORE cache check; different flags create separate cache keys |
| add_api_key_auth | Yes | ✅ Compatible | API key auth middleware must run BEFORE cache middleware to properly scope cache keys |
| add_oauth2_provider | Yes | ✅ Compatible | OAuth2 token validation must happen BEFORE cache check to ensure proper authorization |
| add_rbac | Yes | ✅ Compatible | RBAC checks must run BEFORE cache middleware to prevent unauthorized cache hits |
| add_mfa | Yes | ✅ Compatible | MFA verification must complete BEFORE cache check to ensure proper authentication |
| add_cache_layer | N/A | ✅ Compatible | N/A - self-reference |
| add_outbox_pattern | Yes | ⚠️ Caveat | Cache invalidation must happen AFTER outbox pattern commits to ensure consistency |
| add_sse | No | ✅ Compatible | Server-Sent Events bypass cache by default since they're real-time streams |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- app/cache/decorator.py
git checkout HEAD -- app/cache/core.py 
git checkout HEAD -- app/cache/invalidation.py
git checkout HEAD -- app/api/endpoints/cache.py
git checkout HEAD -- app/core/config.py
git checkout HEAD -- alembic/versions/0012_add_redis_cache_config.py
rm -rf app/cache/
rm -rf tests/test_cache.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the tool crashed mid-run and left an inconsistent tree (some files created, others not), restore to a clean state before re-running:
```bash
# 1. Identify what changed vs last clean HEAD
git status --short

# 2. Drop any staged/unstaged changes the tool made
git checkout HEAD -- app/ alembic/
git clean -fd app/cache/

# 3. Verify tree matches HEAD exactly before re-running
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: cache layer deployed but misbehaving
If the code shipped but the cache is returning stale/wrong data in production, disable the layer without reverting code:
```bash
# 1. Set CACHE_ENABLED=false in the env and roll the pods
kubectl set env deployment/api CACHE_ENABLED=false --record
kubectl rollout status deployment/api

# 2. Purge any corrupted keys (per tenant, never FLUSHALL)
redis-cli --scan --pattern 'cache:tenant_42:*' | xargs -L 100 redis-cli DEL

# 3. Re-enable after fix is verified in staging
kubectl set env deployment/api CACHE_ENABLED=true --record
```
The `@cached` decorator short-circuits to the underlying handler whenever `CACHE_ENABLED=false`, so this is a zero-downtime off switch.

### Emergency: Redis memory full (OOM risk)
When `used_memory` approaches `maxmemory` Redis starts evicting keys under the `allkeys-lru` policy — harmless but latency-impacting. Follow this sequence:
1. Check pressure: `redis-cli INFO memory | grep used_memory_human`
2. Inspect key distribution: `redis-cli --bigkeys` to find the offender prefix
3. Drop low-value prefixes selectively with `SCAN` + `DEL` (never `FLUSHDB` in prod)
4. Raise `maxmemory` temporarily via `CONFIG SET maxmemory 512mb` while you investigate
5. File an incident ticket linking `/cache/stats` snapshot + top-10 keys so the team can tune TTLs

### Emergency: Redis connection pool exhausted
If the app starts raising `ConnectionError: Too many connections`, the fast path is:
1. Check pool usage: `curl https://api.example.com/cache/stats | jq .pool`
2. Raise `REDIS_POOL_SIZE` from 20 → 50 in config and roll the deployment
3. Verify `redis-cli CLIENT LIST | wc -l` drops back under the new limit
4. If still exhausted, toggle `CACHE_ENABLED=false` (above) to remove all Redis traffic while you debug — the app returns to uncached DB reads within a single pod roll

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Redis connection timeout | Requests fall through to DB with warning logged |
| EC-2 | msgpack not installed | Tool falls back to JSON serialization with warning |
| EC-3 | Cache key exceeds 512 bytes | Key is hashed with SHA-256 and original key is logged |
| EC-4 | Tenant_id missing in context | Cache key uses "global" namespace with warning logged |
| EC-5 | Concurrent cache misses | Redis SET NX lock prevents duplicate cache fills |
| EC-6 | SET NX lock expires during slow DB query | Second worker also fills cache (idempotent operation) |
| EC-7 | Pubsub invalidation delayed | TTL expiration acts as safety net for stale data |
| EC-8 | Pagination params change | Each (skip, limit) combo generates separate cache key |
| EC-9 | Cache warm for 10K IDs | Batches requests in groups of 100 to avoid Redis pipeline overflow |
| EC-10 | Response body > 1 MB | Response bypasses cache with warning logged |
| EC-11 | Non-JSON response (binary file) | Response bypasses cache with warning logged |
| EC-12 | Route handler raises exception | Response is not cached (only 200s are cached) |
| EC-13 | Cache stats endpoint with no data | Returns zeroes for memory_used, keys, and hit_rate |
| EC-14 | Tool re-run idempotent | Decorator not duplicated; existing cache config preserved |
| EC-15 | Cache namespace collision | `cache:` prefix prevents collision with other Redis users |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified via checks in CC-01..CC-30  
✅ Cache hit/miss behavior validated by T-01..T-06  
✅ Invalidation logic tested by T-07..T-12  
✅ Tenant isolation confirmed by T-13..T-18  
✅ Stampede prevention verified by T-19..T-24  
✅ Stats endpoint secured and functional per T-25..T-30  
✅ Redis connection pool properly initialized and closed  
✅ Msgpack serialization round-trips correctly  
✅ Cache keys follow strict naming convention  
✅ Developer successfully caches and invalidates `/items/{item_id}` endpoint in production

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate Redis connection is available
- [ ] Detect existing cache decorator usage
- [ ] Verify FastAPI version >= 0.95.0
- [ ] Check for existing Redis configuration
- [ ] Validate msgpack is installed

### 15.2 Settings configuration
- [ ] Add REDIS_URL to app/core/config.py
- [ ] Add REDIS_CACHE_DB to config
- [ ] Add REDIS_CACHE_ENABLED flag
- [ ] Add CACHE_DEFAULT_TTL setting
- [ ] Add CACHE_MAX_SIZE_MB setting
- [ ] Add CACHE_STATS_ENABLED flag
- [ ] Add CACHE_STRATEGY setting

### 15.3 Cache module creation
- [ ] Create app/cache/__init__.py
- [ ] Create app/cache/decorator.py
- [ ] Create app/cache/core.py
- [ ] Create app/cache/invalidation.py
- [ ] Create app/cache/warm.py
- [ ] Create app/cache/exceptions.py
- [ ] Create app/cache/types.py

### 15.4 Decorator implementation
- [ ] Implement @cached decorator
- [ ] Add key pattern formatting
- [ ] Add vary_on parameter support
- [ ] Implement cache bypass logic
- [ ] Add response caching filter
- [ ] Implement Redis lock mechanism
- [ ] Add cache hit/miss logging

### 15.5 Cache backend
- [ ] Implement CacheBackend class
- [ ] Add msgpack serialization
- [ ] Implement Redis connection pool
- [ ] Add error handling wrapper
- [ ] Implement bulk delete operation
- [ ] Add pubsub invalidation channel
- [ ] Implement connection cleanup

### 15.6 Invalidation listener
- [ ] Register SQLAlchemy after_flush
- [ ] Detect model changes
- [ ] Generate cache keys for mutations
- [ ] Implement bulk key deletion
- [ ] Add pubsub invalidation
- [ ] Handle soft delete scenarios
- [ ] Add listener registration helper

### 15.7 Stats endpoint
- [ ] Create app/api/endpoints/cache.py
- [ ] Implement /cache/stats route
- [ ] Add Redis INFO metrics
- [ ] Implement admin auth requirement
- [ ] Add rate limiting
- [ ] Implement error handling
- [ ] Add OpenAPI documentation

### 15.8 Migration generation
- [ ] Create Redis config migration
- [ ] Add Redis settings to DB
- [ ] Implement upgrade()
- [ ] Implement downgrade()
- [ ] Add migration test
- [ ] Verify migration parses
- [ ] Add migration documentation

### 15.9 Test generation
- [ ] Create tests/test_cache.py
- [ ] Generate all 30 test cases
- [ ] Add Redis mock support
- [ ] Implement cache hit/miss tests
- [ ] Add invalidation tests
- [ ] Implement tenant isolation tests
- [ ] Add performance benchmarks

### 15.10 Atomicity
- [ ] Use temp-file + rename pattern
- [ ] Track modified files
- [ ] Implement rollback handler
- [ ] Verify files parse before commit
- [ ] Cleanup on failure
- [ ] Preserve existing cache keys
- [ ] Return detailed status report

### 15.11 Documentation
- [ ] Append cache section to KNOWLEDGE.md
- [ ] Add tool entry to manifest.yaml
- [ ] Update SKILL.md tools table
- [ ] Add OpenAPI cache docs
- [ ] Document cache warming
- [ ] Add troubleshooting guide
- [ ] Include performance tuning tips

### 15.12 Verification
- [ ] Run ast.parse on all modified files
- [ ] Run pytest tests/
- [ ] Verify benchmark metrics
- [ ] Check Redis connection pool
- [ ] Test cache hit/miss behavior
- [ ] Validate invalidation timing
- [ ] Verify stats endpoint security

### 15.13 Performance tuning
- [ ] Measure cache hit latency
- [ ] Test cache miss overhead
- [ ] Verify memory efficiency
- [ ] Check Redis connection usage
- [ ] Test pubsub invalidation speed
- [ ] Benchmark warm_cache utility
- [ ] Verify tool execution time

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/cache/__init__.py",
    "app/cache/decorator.py",
    "app/cache/core.py",
    "app/cache/invalidation.py",
    "app/cache/warm.py",
    "app/api/endpoints/cache.py",
    "tests/test_cache.py",
    "alembic/versions/0012_add_redis_cache_config.py"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/main.py",
    "app/api/main.py"
  ],
  "metrics": {
    "execution_time_ms": 3821,
    "files_changed": 11,
    "lines_added": 587,
    "lines_removed": 12,
    "cache_hit_latency_ms": 1.2,
    "cache_miss_overhead_ms": 4.8
  },
  "next_steps": [
    "Run: pytest tests/test_cache.py -v",
    "Test cache hit/miss behavior: GET /items/123",
    "Verify invalidation: PATCH /items/123 and check cache",
    "Monitor cache stats: GET /cache/stats",
    "Warm cache for known IDs: warm_cache(model='Item', ids=['123', '456'])"
  ],
  "warnings": [
    "msgpack not installed - falling back to JSON serialization (40% larger payloads)",
    "Redis maxmemory policy not configured - ensure cache namespace doesn't exceed max_cache_size_mb"
  ],
  "notes": [
    "Cache layer enabled with strategy=cache_aside, invalidation=both",
    "Default TTL set to 300 seconds (5 minutes)",
    "Cache keys include tenant_id when multi-tenancy is installed",
    "Stats endpoint available at /cache/stats (admin auth required)",
    "Cache warm utility available at app/cache/warm.py",
    "Existing tests still pass: 47/47"
  ]
}
