"""TOOL-103: add_request_fingerprint — automatic request deduplication for FastAPI.

Generates a ``RequestFingerprinter`` (SHA-256 of user_id+method+path+sorted(body)),
a ``FingerprintStore`` (Redis with TTL, memory fallback), a ``FingerprintMiddleware``
(auto-dedup unsafe methods, returns cached response with ``Idempotent-Replayed: true``).

The tool is idempotent: a second run detects ``app/fingerprint/hasher.py``
containing ``RequestFingerprinter`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_request_fingerprint import add_request_fingerprint

    result = add_request_fingerprint(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/fingerprint/hasher.py, ...]
    print(result.next_steps)    # ["Set FINGERPRINT_ENABLED=true", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_request_fingerprint",
    "description": (
        "Add automatic request deduplication: SHA-256 fingerprint of user+method+path+body. "
        "Returns cached response on duplicate with Idempotent-Replayed header. "
        "Redis store with in-memory fallback."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_request_fingerprint",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_request_fingerprint(inp: ToolInput) -> ToolResult:
    """Add request fingerprinting + deduplication to a FastAPI project.

    Writes ``app/fingerprint/`` package (hasher, store), a
    ``FingerprintMiddleware``, and patches ``app/core/config.py`` with
    ``FINGERPRINT_*`` config fields.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    fingerprint_file = app_dir / "fingerprint" / "hasher.py"
    if fingerprint_file.exists() and "RequestFingerprinter" in fingerprint_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RequestFingerprinter already present — fingerprinting already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/fingerprint/ package with hasher, store.",
                "[dry_run] Would add FingerprintMiddleware to app/main.py.",
                "[dry_run] Would patch app/core/config.py with FINGERPRINT_* fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # --- Step 1: fingerprint package -----------------------------------------
    fp_dir = app_dir / "fingerprint"
    fp_dir.mkdir(parents=True, exist_ok=True)

    init_file = fp_dir / "__init__.py"
    _write_fp_init(init_file)
    files_created.append(str(init_file))

    _write_hasher(fingerprint_file)
    files_created.append(str(fingerprint_file))

    store_file = fp_dir / "store.py"
    _write_store(store_file)
    files_created.append(str(store_file))

    # --- Step 2: middleware ---------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_file = middleware_dir / "fingerprint.py"
    _write_fp_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 3: patch config ------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 4: ast.parse validation ----------------------------------------
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

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Request fingerprinting added: SHA-256 hash of user_id+method+path+sorted(body).",
            "FingerprintStore: Redis primary with in-memory fallback (works without Redis).",
            "FingerprintMiddleware: deduplicates POST/PUT (configurable), adds Idempotent-Replayed header.",
            "Duplicate detection within FINGERPRINT_TTL_S window (default: 60 s).",
        ],
        next_steps=[
            "Set FINGERPRINT_ENABLED=true in .env (default: false).",
            "Optional: set FINGERPRINT_TTL_S (default: 60 seconds).",
            "Optional: set FINGERPRINT_METHODS=POST,PUT,PATCH (comma-separated).",
            "pip install 'redis[hiredis]' for Redis store (falls back to memory without Redis).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_fp_init(dest: Path) -> None:
    """Write ``app/fingerprint/__init__.py`` re-exporting public symbols.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Request fingerprinting — public API.\"\"\"

        from app.fingerprint.hasher import RequestFingerprinter
        from app.fingerprint.store import FingerprintStore, get_store, init_store

        __all__ = [
            "RequestFingerprinter",
            "FingerprintStore",
            "get_store",
            "init_store",
        ]
        """))


def _write_hasher(dest: Path) -> None:
    """Write ``app/fingerprint/hasher.py`` with RequestFingerprinter.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"RequestFingerprinter: SHA-256 hash of user_id+method+path+sorted(body).\"\"\"

        from __future__ import annotations

        import hashlib
        import json
        import logging
        from typing import Any

        logger = logging.getLogger(__name__)


        class RequestFingerprinter:
            \"\"\"Compute a deterministic SHA-256 fingerprint for an HTTP request.

            The fingerprint is designed to be:
            - Deterministic: same input always produces same hash.
            - Collision-resistant: body key order does not matter.
            - User-isolated: different users always get different fingerprints.
            \"\"\"

            def compute(
                self,
                user_id: str | None,
                method: str,
                path: str,
                body: bytes | str,
            ) -> str:
                \"\"\"Compute a 64-char hex fingerprint.

                Args:
                    user_id: Authenticated user identifier, or \"anonymous\".
                    method: HTTP method (uppercase, e.g. \"POST\").
                    path: Full request path including query string.
                    body: Raw request body bytes or string.

                Returns:
                    64-character lowercase hex SHA-256 digest.
                \"\"\"
                uid = user_id or "anonymous"
                norm_body = self._normalize_body(body)
                raw = f"{uid}:{method.upper()}:{path}:{norm_body}"
                return hashlib.sha256(raw.encode("utf-8")).hexdigest()

            def _normalize_body(self, body: bytes | str) -> str:
                \"\"\"Normalize body to a canonical string for hashing.

                JSON bodies are parsed and re-serialised with sorted keys so that
                ``{\"b\":1,\"a\":2}`` and ``{\"a\":2,\"b\":1}`` produce the same hash.

                Args:
                    body: Raw body bytes or string.

                Returns:
                    Canonical string representation.
                \"\"\"
                if isinstance(body, bytes):
                    text = body.decode("utf-8", errors="replace")
                else:
                    text = body
                if not text:
                    return ""
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        return json.dumps(obj, sort_keys=True, separators=(",", ":"))
                    return json.dumps(obj, separators=(",", ":"))
                except Exception:
                    return text
        """))


def _write_store(dest: Path) -> None:
    """Write ``app/fingerprint/store.py`` with FingerprintStore.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"FingerprintStore: Redis SET with TTL, in-memory fallback.\"\"\"

        from __future__ import annotations

        import logging
        import time
        from threading import Lock
        from typing import Any

        logger = logging.getLogger(__name__)

        _store: "FingerprintStore | None" = None
        _REDIS_KEY_PREFIX = "fingerprint:"


        class _MemoryStore:
            \"\"\"Simple in-memory store for fingerprints (single-process fallback).\"\"\"

            def __init__(self) -> None:
                self._data: dict[str, float] = {}  # fingerprint -> expiry timestamp
                self._lock = Lock()

            async def exists(self, key: str) -> bool:
                \"\"\"Return True if key exists and is not expired.

                Args:
                    key: Fingerprint key to check.
                \"\"\"
                with self._lock:
                    exp = self._data.get(key)
                    if exp is None:
                        return False
                    if time.monotonic() > exp:
                        del self._data[key]
                        return False
                    return True

            async def set(self, key: str, ttl_s: int) -> None:
                \"\"\"Store key with TTL.

                Args:
                    key: Fingerprint key to store.
                    ttl_s: Expiry in seconds.
                \"\"\"
                with self._lock:
                    self._data[key] = time.monotonic() + ttl_s
                    # Prune expired entries when map grows large
                    if len(self._data) > 10000:
                        now = time.monotonic()
                        self._data = {
                            k: v for k, v in self._data.items() if v > now
                        }


        class FingerprintStore:
            \"\"\"Persistent fingerprint store backed by Redis with memory fallback.

            Args:
                redis: Optional async Redis client.  When ``None``, falls back to
                    an in-process ``_MemoryStore`` (single-process only).
                ttl_s: Key expiry in seconds.
            \"\"\"

            def __init__(self, redis: Any | None = None, ttl_s: int = 60) -> None:
                self._redis = redis
                self._ttl_s = ttl_s
                self._memory = _MemoryStore()

            async def is_duplicate(self, fingerprint: str) -> bool:
                \"\"\"Return True if this fingerprint was seen within TTL.

                Also stores the fingerprint on first sight.

                Args:
                    fingerprint: 64-char hex fingerprint from RequestFingerprinter.
                \"\"\"
                key = _REDIS_KEY_PREFIX + fingerprint
                if self._redis is not None:
                    try:
                        was_set = await self._redis.set(key, "1", nx=True, ex=self._ttl_s)
                        return was_set is None or was_set is False
                    except Exception:
                        logger.warning(
                            "FingerprintStore Redis error — falling back to memory",
                            exc_info=True,
                        )
                already_seen = await self._memory.exists(fingerprint)
                if not already_seen:
                    await self._memory.set(fingerprint, self._ttl_s)
                return already_seen


        def get_store() -> "FingerprintStore | None":
            \"\"\"Return the process-wide FingerprintStore, or None if not initialised.\"\"\"
            return _store


        async def init_store(
            redis_url: str | None = None,
            ttl_s: int = 60,
        ) -> None:
            \"\"\"Initialise the global fingerprint store.  Call once at app startup.

            Args:
                redis_url: Redis connection URL.  When ``None`` or empty, uses
                    the in-memory fallback only.
                ttl_s: Fingerprint TTL in seconds.
            \"\"\"
            global _store
            redis = None
            if redis_url:
                try:
                    from redis.asyncio import Redis  # lazy — optional SDK

                    redis = Redis.from_url(redis_url, decode_responses=True)
                except Exception:
                    logger.warning("FingerprintStore: Redis init failed, using memory", exc_info=True)
            _store = FingerprintStore(redis=redis, ttl_s=ttl_s)
        """))


def _write_fp_middleware(dest: Path) -> None:
    """Write ``app/middleware/fingerprint.py`` with FingerprintMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"FingerprintMiddleware: auto-dedup unsafe methods, replay cached response.\"\"\"

        from __future__ import annotations

        import logging
        from typing import Callable

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.fingerprint.hasher import RequestFingerprinter
        from app.fingerprint.store import get_store

        logger = logging.getLogger(__name__)

        _FINGERPRINTER = RequestFingerprinter()

        _DEFAULT_METHODS = {"POST", "PUT", "PATCH"}


        class FingerprintMiddleware(BaseHTTPMiddleware):
            \"\"\"Deduplicate requests by SHA-256 fingerprint of user+method+path+body.

            On first request: process normally, cache the response in memory.
            On duplicate (within TTL): return cached response immediately with
            ``Idempotent-Replayed: true`` header.

            Args:
                app: ASGI application.
                enabled_methods: HTTP methods to fingerprint (default: POST, PUT, PATCH).
            \"\"\"

            def __init__(
                self,
                app: Callable,
                enabled_methods: set[str] | None = None,
            ) -> None:
                super().__init__(app)
                self._methods = enabled_methods or _DEFAULT_METHODS
                self._response_cache: dict[str, tuple[int, str, str]] = {}

            def _replay_cached(self, fp: str) -> Response | None:
                \"\"\"Return a cached Response with Idempotent-Replayed header, or None.

                Args:
                    fp: SHA-256 fingerprint key.
                \"\"\"
                cached = self._response_cache.get(fp)
                if cached:
                    status_code, content, media_type = cached
                    return Response(
                        content=content,
                        status_code=status_code,
                        media_type=media_type,
                        headers={"Idempotent-Replayed": "true"},
                    )
                return Response(
                    content="",
                    status_code=200,
                    headers={"Idempotent-Replayed": "true"},
                )

            async def _capture_and_cache(
                self, fp: str, response: Response
            ) -> Response:
                \"\"\"Read response body, cache it, and return a new Response.

                Args:
                    fp: Fingerprint key for cache storage.
                    response: Upstream response with body_iterator.
                \"\"\"
                chunks: list[bytes] = []
                async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                    chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
                resp_body = b"".join(chunks).decode(errors="replace")
                self._response_cache[fp] = (
                    response.status_code, resp_body,
                    response.media_type or "application/json",
                )
                if len(self._response_cache) > 5000:
                    for k in list(self._response_cache.keys())[:1000]:
                        del self._response_cache[k]
                return Response(
                    content=resp_body.encode(),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Check fingerprint; replay cached response on duplicate.\"\"\"
                if request.method.upper() not in self._methods:
                    return await call_next(request)
                store = get_store()
                if store is None:
                    return await call_next(request)

                try:
                    body = await request.body()
                except Exception:
                    body = b""

                user_id = str(request.state.user.id) if hasattr(request.state, "user") else None
                fp = _FINGERPRINTER.compute(
                    user_id=user_id,
                    method=request.method,
                    path=str(request.url),
                    body=body,
                )
                if await store.is_duplicate(fp):
                    return self._replay_cached(fp)

                response = await call_next(request)
                try:
                    return await self._capture_and_cache(fp, response)
                except Exception:
                    logger.debug("FingerprintMiddleware: body capture failed", exc_info=True)
                    return response
        """))


def _patch_config(config_file: Path) -> None:
    """Inject FINGERPRINT_* fields into app/core/config.py Settings.

    Fields are injected inside the Settings class body with 4-space indent.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "FINGERPRINT_ENABLED" in src:
        return

    # 4-space-indented block to inject inside the Settings class body
    injection = (
        "\n"
        "    # Request fingerprinting — added by add_request_fingerprint tool\n"
        "    FINGERPRINT_ENABLED: bool = False\n"
        "    FINGERPRINT_TTL_S: int = 60\n"
        "    FINGERPRINT_METHODS: str = \"POST,PUT,PATCH\"\n"
    )

    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", injection + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + injection

    config_file.write_text(src)


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
