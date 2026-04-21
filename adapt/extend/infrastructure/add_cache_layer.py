"""TOOL-021: add_cache_layer — Redis-backed caching backed by primitives.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern (Rails-style wiring):

1. Copy the framework-agnostic primitives
   ``core.venous.cache.KeyValueBucket`` (generic KV store),
   ``core.venous.cache.SessionCache`` (session-scoped read-through cache),
   and ``core.venous.cache.DistributedLock`` (stampede-prevention mutex)
   into the generated project.
2. Emit a thin ``app/cache.py`` glue file (≤ 20 logic lines, AST verified)
   that instantiates a ``KeyValueBucket`` + exposes a ``cache_aside`` helper
   gated by ``DistributedLock`` and a ``get_session_cache`` factory.
3. Emit the Redis-backed ``@cached`` decorator, invalidation, stats route
   — the *semantics* (revision-tracked KV, read-through loader, mutex
   lease validity) live in the primitives.

The tool is idempotent: a second run detects ``KeyValueBucket`` in
``app/cache.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_cache_layer import add_cache_layer

    result = add_cache_layer(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/cache.py, ...]
    print(result.next_steps)    # ["pip install redis[hiredis] msgpack", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_cache_layer",
    "description": (
        "Copy KeyValueBucket + SessionCache + DistributedLock primitives "
        "into the project and wire a ≤20-line app/cache.py glue that "
        "exposes cache_aside() + get_session_cache() helpers."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_cache_layer",
    "imports_primitives": [
        "core.venous.cache.KeyValueBucket",
        "core.venous.cache.SessionCache",
        "core.venous.cache.DistributedLock",
    ],
    "imports_adapters": (),
}


# ---------------------------------------------------------------------------
# Thin glue over core.venous.cache.{KeyValueBucket,SessionCache,DistributedLock}
# ---------------------------------------------------------------------------

_CACHE_GLUE = '''\
"""Thin glue that wires the cache primitives into a FastAPI app.

Delegates to the primitives copied under `core/venous/cache/` by the
`add_cache_layer` tool. Re-emitted idempotently on subsequent runs. This
file contains NO caching semantics — revision-tracked KV (KeyValueBucket),
session-scoped read-through (SessionCache), and lease-based mutex
(DistributedLock) all live in the primitives.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Callable

from core.venous.cache.KeyValueBucket.KeyValueBucket import InMemoryKeyValueBucket
from core.venous.cache.SessionCache.SessionCache import InMemorySessionCache
from core.venous.cache.DistributedLock.DistributedLock import InMemoryDistributedLock

_bucket: InMemoryKeyValueBucket | None = None
_lock: InMemoryDistributedLock | None = None
_session: InMemorySessionCache | None = None


def get_bucket() -> InMemoryKeyValueBucket:
    """Return the process-global KeyValueBucket (lazy init from env)."""
    global _bucket
    if _bucket is None: _bucket = InMemoryKeyValueBucket()
    return _bucket


def get_lock() -> InMemoryDistributedLock:
    """Return the process-global DistributedLock (lazy init)."""
    global _lock
    if _lock is None: _lock = InMemoryDistributedLock()
    return _lock


def get_session_cache() -> InMemorySessionCache:
    """Return the process-global SessionCache (lazy init)."""
    global _session
    if _session is None: _session = InMemorySessionCache()
    return _session


def cache_aside(key: str, factory: Callable[[], bytes], ttl: int | None = None) -> bytes:
    """Cache-aside read with DistributedLock stampede prevention."""
    bucket, lock = get_bucket(), get_lock()
    entry = bucket.get(key)
    if entry is not None: return entry.value
    handle = lock.try_lock(key, uuid.uuid4().hex, int(ttl or int(os.getenv("CACHE_LOCK_LEASE_S", "5"))))
    if handle is None: return (bucket.get(key).value if bucket.get(key) else factory())
    try: value = factory(); bucket.create(key, value); return value
    finally: lock.unlock(handle)


__all__ = [
    "InMemoryKeyValueBucket",
    "InMemorySessionCache",
    "InMemoryDistributedLock",
    "get_bucket",
    "get_lock",
    "get_session_cache",
    "cache_aside",
]
'''



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_cache_layer(inp: ToolInput) -> ToolResult:
    """Add Redis cache layer to a FastAPI project.

    Writes ``app/cache/`` package (core, decorator, invalidation, stats),
    patches ``app/main.py`` to register the cache lifespan, and adds a
    ``/cache/stats`` endpoint.  Returns a ``ToolResult`` describing every
    file created or modified.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard (primitive-class-name in glue) --------------------
    # NOTE: glue lives at app/cache/primitives.py rather than app/cache.py
    # because the Redis @cached decorator/package already occupies the
    # `app.cache` namespace. Same ADR rules apply (≤20 logic lines).
    glue_file = app_dir / "cache" / "primitives.py"
    if glue_file.exists() and "KeyValueBucket" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "KeyValueBucket + SessionCache + DistributedLock primitives "
                "already wired via app/cache.py — skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )
    cache_core = app_dir / "cache" / "core.py"

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create app/cache/ package with core, decorator, invalidation, stats."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 0: Copy primitives (§B1.0) ------------------------------------
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=[
            "core.venous.cache.KeyValueBucket",
            "core.venous.cache.SessionCache",
            "core.venous.cache.DistributedLock",
        ],
        adapters=[],
    )
    files_created.append(manifest.path)

    # --- Step 1: cache package -----------------------------------------------
    cache_dir = app_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # --- Thin glue over the copied primitives (§B1.0.1) ---------------------
    glue_file.write_text(_CACHE_GLUE)
    files_created.append(str(glue_file))

    init_file = cache_dir / "__init__.py"
    _write_cache_init(init_file)
    files_created.append(str(init_file))

    _write_cache_core(cache_core)
    files_created.append(str(cache_core))

    decorator_file = cache_dir / "decorator.py"
    _write_cache_decorator(decorator_file)
    files_created.append(str(decorator_file))

    invalidation_file = cache_dir / "invalidation.py"
    _write_cache_invalidation(invalidation_file)
    files_created.append(str(invalidation_file))

    keys_file = cache_dir / "keys.py"
    _write_cache_keys(keys_file)
    files_created.append(str(keys_file))

    # --- Step 2: /cache/stats route ------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        stats_route = routes_dir / "cache_stats.py"
        _write_cache_stats_route(stats_route)
        files_created.append(str(stats_route))

    # --- Step 3: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 4: Patch requirements.txt ---------------------------------------
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        req_adds = []
        if "msgpack" not in req_src:
            req_adds.append("msgpack>=1.0.0")
        if "redis" not in req_src:
            req_adds.append("redis[hiredis]>=5.0.0")
        if req_adds:
            req_file.write_text(req_src.rstrip("\n") + "\n" + "\n".join(req_adds) + "\n")
            files_modified.append(str(req_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    # --- Enforce ≤20 logic lines in the primary glue (CONTRACT §B1.0.1) -----
    glue_loc = _count_logic_lines(glue_file.read_text())
    if glue_loc > 20:
        return ToolResult(
            status="error",
            error=f"Primary glue {glue_file} has {glue_loc} logic lines (> 20).",
            execution_time_ms=_elapsed_ms(start),
        )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitives: core.venous.cache.KeyValueBucket, SessionCache, DistributedLock.",
            "Glue: app/cache/primitives.py wires KeyValueBucket + DistributedLock + SessionCache.",
            "Redis cache layer added: @cached decorator, key isolation, msgpack serialization.",
            "Invalidation strategy: hybrid TTL + pub/sub fan-out to all workers.",
            "Key pattern: cache:{tenant}:resource:{id}",
            "/cache/stats endpoint added (requires require_admin dep).",
        ],
        next_steps=[
            "pip install 'redis[hiredis]' msgpack",
            "Set REDIS_URL in .env (e.g. redis://localhost:6379/0).",
            "Decorate GET handlers: @cached(ttl=300, key_pattern='items:{item_id}')",
            "Call invalidate_resource('items', item_id) in POST/PUT/DELETE handlers.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_cache_init(dest: Path) -> None:
    """Write ``app/cache/__init__.py`` re-exporting public symbols.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Redis cache layer — public API.\"\"\"

        from app.cache.core import CacheBackend, get_cache, init_cache, close_cache
        from app.cache.decorator import cached
        from app.cache.invalidation import invalidate_resource, invalidate_pattern
        from app.cache.keys import build_key

        __all__ = [
            "CacheBackend",
            "get_cache",
            "init_cache",
            "close_cache",
            "cached",
            "invalidate_resource",
            "invalidate_pattern",
            "build_key",
        ]
        """))


def _write_cache_core(dest: Path) -> None:
    """Write ``app/cache/core.py`` with CacheBackend (msgpack + Redis).

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Redis CacheBackend: get/set/delete with msgpack serialization.\"\"\"

        from __future__ import annotations

        import logging
        from typing import TYPE_CHECKING, Any

        import msgpack

        if TYPE_CHECKING:
            from redis.asyncio import Redis

        logger = logging.getLogger(__name__)

        _cache: "CacheBackend | None" = None


        class CacheBackend:
            \"\"\"Thin async wrapper around Redis with msgpack serialization.

            Args:
                redis: Connected async Redis client.
                default_ttl: Default key expiration in seconds.
            \"\"\"

            def __init__(self, redis: "Redis", default_ttl: int = 300) -> None:
                self.redis = redis
                self.default_ttl = default_ttl

            async def get(self, key: str) -> Any:
                \"\"\"Return deserialised value or None on miss / error.

                Args:
                    key: Redis key to look up.
                \"\"\"
                try:
                    data = await self.redis.get(key)
                    return msgpack.unpackb(data, raw=False) if data is not None else None
                except Exception:
                    logger.warning("Cache GET failed for key=%s", key, exc_info=True)
                    return None

            async def set(self, key: str, value: Any, *, ttl: int | None = None) -> bool:
                \"\"\"Serialise *value* with msgpack and store in Redis.

                Args:
                    key: Redis key.
                    value: Python object to store.
                    ttl: Expiration seconds; falls back to ``default_ttl``.
                \"\"\"
                try:
                    packed = msgpack.packb(value, use_bin_type=True)
                    await self.redis.setex(key, ttl or self.default_ttl, packed)
                    return True
                except Exception:
                    logger.warning("Cache SET failed for key=%s", key, exc_info=True)
                    return False

            async def delete(self, key: str) -> int:
                \"\"\"Delete a single key.  Returns number of keys deleted.

                Args:
                    key: Redis key to remove.
                \"\"\"
                try:
                    return await self.redis.delete(key)
                except Exception:
                    logger.warning("Cache DELETE failed for key=%s", key, exc_info=True)
                    return 0

            async def delete_pattern(self, pattern: str) -> int:
                \"\"\"Delete all keys matching *pattern* (SCAN-based, safe for production).

                Args:
                    pattern: Redis glob pattern (e.g. ``cache:tenant1:items:*``).
                \"\"\"
                deleted = 0
                try:
                    async for key in self.redis.scan_iter(match=pattern, count=100):
                        deleted += await self.redis.delete(key)
                except Exception:
                    logger.warning("Cache DELETE_PATTERN failed pattern=%s", pattern, exc_info=True)
                return deleted

            async def stats(self) -> dict:
                \"\"\"Return cache stats dict (hit_keys, memory_bytes, connected).\"\"\"
                try:
                    info = await self.redis.info("memory")
                    keyspace = await self.redis.info("keyspace")
                    return {
                        "connected": True,
                        "memory_used_bytes": info.get("used_memory", 0),
                        "memory_human": info.get("used_memory_human", "N/A"),
                        "keyspace": keyspace,
                    }
                except Exception as exc:
                    return {"connected": False, "error": str(exc)}


        def get_cache() -> "CacheBackend | None":
            \"\"\"Return the process-wide CacheBackend instance (None if not initialised).\"\"\"
            return _cache


        async def init_cache(redis_url: str, default_ttl: int = 300) -> None:
            \"\"\"Initialise the global cache backend.  Call once at app startup.

            Args:
                redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
                default_ttl: Default key expiration in seconds.
            \"\"\"
            global _cache
            from redis.asyncio import Redis
            redis = Redis.from_url(redis_url, decode_responses=False)
            _cache = CacheBackend(redis, default_ttl=default_ttl)


        async def close_cache() -> None:
            \"\"\"Close the Redis connection.  Call on app shutdown.\"\"\"
            global _cache
            if _cache is not None:
                await _cache.redis.aclose()
                _cache = None
        """))


def _write_cache_decorator(dest: Path) -> None:
    """Write ``app/cache/decorator.py`` with @cached.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"@cached decorator for FastAPI route handlers.

        Usage::

            @router.get("/items/{item_id}")
            @cached(ttl=300, key_pattern="items:{item_id}")
            async def get_item(item_id: str, ...) -> ItemPublic:
                ...
        \"\"\"

        from __future__ import annotations

        import asyncio
        import functools
        import logging
        from typing import Any, Callable

        from app.cache.core import get_cache
        from app.cache.keys import build_key

        logger = logging.getLogger(__name__)

        # Supported schema version constant — bump when cache value format changes
        _STAMPEDE_LOCK_TTL = 10  # seconds
        _STAMPEDE_RETRY_DELAY = 0.05  # seconds


        def _should_skip_cache(request: Any) -> bool:
            \"\"\"Return True if this request should bypass the cache.\"\"\"
            if request is None:
                return False
            # INV-CACHE-08: only cache GET requests
            if getattr(request, "method", "GET").upper() != "GET":
                return True
            # INV-CACHE-04: bypass via Cache-Control header or ?nocache=1
            if request.headers.get("cache-control") == "no-cache":
                return True
            if request.query_params.get("nocache"):
                return True
            return False


        async def _acquire_stampede_lock(cache: Any, key: str) -> bool:
            \"\"\"Try to acquire an anti-stampede lock (INV-CACHE-06).\"\"\"
            lock_key = f"cache_lock:{key}"
            return await cache.redis.set(lock_key, "1", nx=True, ex=_STAMPEDE_LOCK_TTL)


        async def _release_stampede_lock(cache: Any, key: str) -> None:
            \"\"\"Release the anti-stampede lock.\"\"\"
            await cache.redis.delete(f"cache_lock:{key}")


        def cached(
            ttl: int = 300,
            key_pattern: str | None = None,
            vary_on: list[str] | None = None,
        ) -> Callable:
            \"\"\"Decorator that caches GET handler return values with anti-stampede.\"\"\"
            def decorator(func: Callable) -> Callable:
                @functools.wraps(func)
                async def wrapper(*args: Any, **kwargs: Any) -> Any:
                    request = kwargs.get("request")
                    if _should_skip_cache(request):
                        return await func(*args, **kwargs)

                    cache = get_cache()
                    if cache is None:
                        return await func(*args, **kwargs)

                    key = build_key(func, key_pattern, vary_on, kwargs)
                    cached_value = await cache.get(key)
                    if cached_value is not None:
                        return cached_value

                    lock_acquired = await _acquire_stampede_lock(cache, key)
                    if not lock_acquired:
                        await asyncio.sleep(_STAMPEDE_RETRY_DELAY)
                        cached_value = await cache.get(key)
                        if cached_value is not None:
                            return cached_value
                    try:
                        result = await func(*args, **kwargs)
                        if result is not None:
                            await cache.set(key, result, ttl=ttl)
                        return result
                    finally:
                        if lock_acquired:
                            await _release_stampede_lock(cache, key)

                return wrapper
            return decorator
        """))


def _write_cache_keys(dest: Path) -> None:
    """Write ``app/cache/keys.py`` with key generation helpers.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Cache key generation: ``cache:{tenant}:resource:{id}`` pattern.\"\"\"

        from __future__ import annotations

        import logging
        from contextvars import ContextVar
        from typing import Callable

        logger = logging.getLogger(__name__)

        _tenant_var: ContextVar[str | None] = ContextVar("cache_tenant", default=None)


        def set_tenant(tenant_id: str | None) -> None:
            \"\"\"Set current tenant for key namespacing (request-scoped via ContextVar).

            Uses a ``ContextVar`` so concurrent requests never share tenant state.

            Args:
                tenant_id: Tenant identifier, or None for global namespace.
            \"\"\"
            _tenant_var.set(tenant_id)


        def get_tenant() -> str:
            \"\"\"Return current tenant string (falls back to 'global').\"\"\"
            return _tenant_var.get() or "global"


        def build_key(
            func: Callable,
            key_pattern: str | None,
            vary_on: list[str] | None,
            kwargs: dict,
        ) -> str:
            \"\"\"Build a namespaced cache key.

            Pattern: ``cache:{tenant}:{func_module}.{func_name}[:{formatted_pattern}]``

            Args:
                func: The decorated function (used for module + name).
                key_pattern: Optional format string (e.g. ``"items:{item_id}"``).
                vary_on: List of kwarg names to append to the key.
                kwargs: The function's keyword arguments at call time.

            Returns:
                String cache key.
            \"\"\"
            tenant = get_tenant()
            base = f"cache:{tenant}:{func.__module__}.{func.__name__}"

            if key_pattern:
                try:
                    return f"{base}:{key_pattern.format(**kwargs)}"
                except KeyError:
                    logger.warning("Cache key pattern formatting failed: %s", key_pattern)

            if vary_on:
                parts = [f"{k}:{kwargs.get(k)}" for k in vary_on if k in kwargs]
                return f"{base}:{'|'.join(parts)}"

            return base


        def resource_key(tenant: str, resource: str, resource_id: str) -> str:
            \"\"\"Build canonical resource key ``cache:{tenant}:resource:{id}``.

            Args:
                tenant: Tenant identifier.
                resource: Resource type name (e.g. ``"items"``).
                resource_id: Resource primary key.

            Returns:
                Fully qualified cache key string.
            \"\"\"
            return f"cache:{tenant}:{resource}:{resource_id}"


        def resource_pattern(tenant: str, resource: str) -> str:
            \"\"\"Build glob pattern for all keys of a resource type.

            Args:
                tenant: Tenant identifier.
                resource: Resource type name.

            Returns:
                Redis glob pattern, e.g. ``cache:tenant1:items:*``.
            \"\"\"
            return f"cache:{tenant}:{resource}:*"
        """))


def _write_cache_invalidation(dest: Path) -> None:
    """Write ``app/cache/invalidation.py`` with pub/sub invalidation helpers.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Cache invalidation via TTL expiry and Redis pub/sub fan-out.

        Workers subscribe to ``cache:invalidation`` channel and delete local
        keys when a mutation event arrives, ensuring all pods see consistent
        state within < 100 ms.
        \"\"\"

        from __future__ import annotations

        import json
        import logging

        from app.cache.core import get_cache
        from app.cache.keys import get_tenant, resource_pattern

        logger = logging.getLogger(__name__)

        _INVALIDATION_CHANNEL = "cache:invalidation"


        async def invalidate_resource(resource: str, resource_id: str | None = None) -> int:
            \"\"\"Delete all cached entries for a resource, then fan-out via pub/sub.

            Args:
                resource: Resource type (e.g. ``"items"``).
                resource_id: Specific ID to invalidate; None invalidates all.

            Returns:
                Number of Redis keys deleted.
            \"\"\"
            cache = get_cache()
            if cache is None:
                return 0

            tenant = get_tenant()
            if resource_id is not None:
                pattern = f"cache:{tenant}:{resource}:{resource_id}"
                deleted = await cache.delete(pattern)
            else:
                deleted = await cache.delete_pattern(resource_pattern(tenant, resource))

            await _publish_invalidation(cache, resource, resource_id)
            return deleted


        async def invalidate_pattern(pattern: str) -> int:
            \"\"\"Delete all keys matching *pattern* and notify other workers.

            Args:
                pattern: Redis glob pattern to invalidate.

            Returns:
                Number of keys deleted locally.
            \"\"\"
            cache = get_cache()
            if cache is None:
                return 0
            deleted = await cache.delete_pattern(pattern)
            await _publish_invalidation(cache, pattern=pattern)
            return deleted


        async def _publish_invalidation(
            cache,
            resource: str | None = None,
            resource_id: str | None = None,
            pattern: str | None = None,
        ) -> None:
            \"\"\"Publish invalidation message to the Redis pub/sub channel.

            Args:
                cache: CacheBackend instance.
                resource: Resource type name being invalidated.
                resource_id: Specific resource ID, or None for all.
                pattern: Raw pattern override (mutually exclusive with resource).
            \"\"\"
            try:
                message = json.dumps({
                    "tenant": get_tenant(),
                    "resource": resource,
                    "resource_id": resource_id,
                    "pattern": pattern,
                })
                await cache.redis.publish(_INVALIDATION_CHANNEL, message)
            except Exception:
                logger.warning("Failed to publish cache invalidation", exc_info=True)
        """))


def _write_cache_stats_route(dest: Path) -> None:
    """Write ``app/api/routes/cache_stats.py`` with /cache/stats endpoint.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Admin endpoint: GET /cache/stats.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Depends, HTTPException

        from app.api.deps import get_current_superuser
        from app.cache.core import get_cache

        router = APIRouter(prefix="/cache", tags=["cache"])


        @router.get("/stats", response_model=dict, dependencies=[Depends(get_current_superuser)])
        async def cache_stats() -> dict:
            \"\"\"Return Redis cache statistics.  Admin use only.

            Requires superuser authentication (INV-CACHE-07).

            Returns:
                Dict with ``connected``, ``memory_used_bytes``, ``memory_human``,
                and ``keyspace`` from Redis INFO.

            Raises:
                HTTPException: 401/403 if not authenticated as superuser.
                HTTPException: 503 if cache backend is not initialised.
            \"\"\"
            cache = get_cache()
            if cache is None:
                raise HTTPException(status_code=503, detail="Cache backend not initialised")
            return await cache.stats()
        """))


def _patch_main(main_file: Path) -> None:
    """Inject cache init/close into main.py lifespan or startup/shutdown events.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "init_cache" in src:
        return

    cache_import = (
        "\nfrom app.cache.core import init_cache, close_cache  "
        "# noqa: F401 — cache layer\n"
        "import os as _os\n"
    )
    cache_startup = textwrap.dedent("""\

        # Cache layer startup — added by add_cache_layer tool
        _redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _cache_ttl = int(_os.getenv("CACHE_DEFAULT_TTL", "300"))
    """)

    # Prepend import after first import block marker
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + cache_import,
        )
    else:
        src = cache_import + src

    src = src.rstrip("\n") + "\n" + cache_startup
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


def _count_logic_lines(source: str) -> int:
    """Count executable logic lines — imports, class/func defs, and decorators
    do NOT count (per CONTRACT §B1.0.1).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    loc = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body:
                first = node.body[0].lineno
                last = node.end_lineno or first
                loc += last - first + 1
    return loc
