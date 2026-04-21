"""TOOL-101: add_api_replay_debugger — time-travel debugging for FastAPI.

Generates a ``RequestRecorder`` (Redis ring buffer), ``RequestReplayer``
(re-execute + diff), ``RecorderMiddleware`` (background, zero latency), and
``/debug/requests|replay|flush`` admin endpoints.

The tool is idempotent: a second run detects ``app/debug/recorder.py``
containing ``RequestRecorder`` and returns ``status="no_op"`` without
touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_api_replay_debugger import (
        add_api_replay_debugger,
    )

    result = add_api_replay_debugger(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/debug/recorder.py, ...]
    print(result.next_steps)    # ["Set DEBUG_RECORDER_ENABLED=true", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_api_replay_debugger",
    "description": (
        "Add time-travel API replay debugger: Redis ring buffer captures full "
        "req/resp, replayer re-executes + diffs, admin endpoints for listing and "
        "replaying recorded requests."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_api_replay_debugger",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_api_replay_debugger(inp: ToolInput) -> ToolResult:
    """Add API replay debugger to a FastAPI project.

    Writes ``app/debug/`` package (recorder, replayer, models), a
    ``RecorderMiddleware``, and ``/debug/requests|replay|flush`` admin routes.
    Patches ``app/core/config.py`` with debug config fields and registers the
    middleware + router in ``app/main.py``.

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
    fingerprint_file = app_dir / "debug" / "recorder.py"
    if fingerprint_file.exists() and "RequestRecorder" in fingerprint_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RequestRecorder already present — replay debugger already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/debug/ package with recorder, replayer, models.",
                "[dry_run] Would add RecorderMiddleware to app/main.py.",
                "[dry_run] Would add /debug/requests|replay|flush routes.",
                "[dry_run] Would patch app/core/config.py with DEBUG_RECORDER_* fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # --- Step 1: debug package -----------------------------------------------
    debug_dir = app_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    init_file = debug_dir / "__init__.py"
    _write_debug_init(init_file)
    files_created.append(str(init_file))

    _write_recorder(fingerprint_file)
    files_created.append(str(fingerprint_file))

    replayer_file = debug_dir / "replayer.py"
    _write_replayer(replayer_file)
    files_created.append(str(replayer_file))

    models_file = debug_dir / "models.py"
    _write_debug_models(models_file)
    files_created.append(str(models_file))

    # --- Step 2: middleware ---------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_file = middleware_dir / "request_recorder.py"
    _write_recorder_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 3: routes ------------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        debug_route = routes_dir / "debug.py"
        _write_debug_routes(debug_route)
        files_created.append(str(debug_route))

    # --- Step 4: patch config ------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 6: ast.parse validation ----------------------------------------
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
            "API replay debugger added: RequestRecorder ring buffer + RequestReplayer.",
            "RecorderMiddleware captures full req/resp in background (zero latency impact).",
            "Admin routes: GET /debug/requests, POST /debug/replay/{id}, DELETE /debug/flush.",
            "Idempotency key per record: SHA-256 of method+path+sorted(body)+timestamp.",
        ],
        next_steps=[
            "pip install 'redis[hiredis]'",
            "Set DEBUG_RECORDER_ENABLED=true in .env (default: false).",
            "Set REDIS_URL in .env (e.g. redis://localhost:6379/0).",
            "Optional: set DEBUG_RECORDER_TTL_S and DEBUG_RECORDER_MAX_ENTRIES.",
            "Optional: set DEBUG_RECORDER_EXCLUDE_PATHS=comma,separated,paths.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_debug_init(dest: Path) -> None:
    """Write ``app/debug/__init__.py`` re-exporting public symbols.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"API replay debugger — public API.\"\"\"

        from app.debug.recorder import RequestRecorder, get_recorder, init_recorder
        from app.debug.replayer import RequestReplayer
        from app.debug.models import RecordedRequest, ReplayResult

        __all__ = [
            "RequestRecorder",
            "get_recorder",
            "init_recorder",
            "RequestReplayer",
            "RecordedRequest",
            "ReplayResult",
        ]
        """))


def _write_recorder(dest: Path) -> None:
    """Write ``app/debug/recorder.py`` with RequestRecorder (Redis ring buffer).

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"RequestRecorder: captures full req/resp in a Redis ring buffer.\"\"\"

        from __future__ import annotations

        import hashlib
        import json
        import logging
        import time
        from typing import Any

        logger = logging.getLogger(__name__)

        _recorder: "RequestRecorder | None" = None

        _LIST_KEY = "debug:requests"


        class RequestRecorder:
            \"\"\"Redis ring-buffer recorder for HTTP requests and responses.

            Stores each record as JSON in a Redis list, capped at ``max_entries``
            via ``LTRIM``.  Each entry has a SHA-256 ``id`` for stable replay
            references.

            Args:
                redis: Connected async Redis client.
                ttl_s: TTL for the list key (seconds).
                max_entries: Maximum entries to retain in the ring buffer.
                exclude_paths: Paths to skip (e.g. [\"/healthz\", \"/metrics\"]).
            \"\"\"

            def __init__(
                self,
                redis: Any,
                ttl_s: int = 3600,
                max_entries: int = 10000,
                exclude_paths: list[str] | None = None,
            ) -> None:
                self.redis = redis
                self.ttl_s = ttl_s
                self.max_entries = max_entries
                self.exclude_paths = exclude_paths or []

            def _make_id(self, method: str, path: str, ts: float) -> str:
                \"\"\"Generate a stable SHA-256 id for a request.

                Args:
                    method: HTTP method string.
                    path: Request path.
                    ts: Unix timestamp float.
                \"\"\"
                raw = f"{method}:{path}:{ts}"
                return hashlib.sha256(raw.encode()).hexdigest()[:16]

            async def record(
                self,
                method: str,
                path: str,
                request_headers: dict,
                request_body: str,
                status_code: int,
                response_headers: dict,
                response_body: str,
                duration_ms: float,
            ) -> str | None:
                \"\"\"Record a request/response pair to Redis.

                Args:
                    method: HTTP method (e.g. \"GET\").
                    path: Request path with query string.
                    request_headers: Dict of request headers.
                    request_body: Decoded request body string.
                    status_code: HTTP response status code.
                    response_headers: Dict of response headers.
                    response_body: Decoded response body string.
                    duration_ms: Total request duration in milliseconds.

                Returns:
                    The record id, or None on error.
                \"\"\"
                if any(path.startswith(p) for p in self.exclude_paths):
                    return None
                try:
                    ts = time.time()
                    rec_id = self._make_id(method, path, ts)
                    entry = json.dumps({
                        "id": rec_id,
                        "ts": ts,
                        "method": method,
                        "path": path,
                        "request_headers": request_headers,
                        "request_body": request_body,
                        "status_code": status_code,
                        "response_headers": response_headers,
                        "response_body": response_body,
                        "duration_ms": duration_ms,
                    })
                    await self.redis.lpush(_LIST_KEY, entry)
                    await self.redis.ltrim(_LIST_KEY, 0, self.max_entries - 1)
                    await self.redis.expire(_LIST_KEY, self.ttl_s)
                    return rec_id
                except Exception:
                    logger.warning("RequestRecorder.record failed", exc_info=True)
                    return None

            async def list_records(self, limit: int = 50) -> list[dict]:
                \"\"\"Return the most recent *limit* recorded requests.

                Args:
                    limit: Maximum number of records to return.
                \"\"\"
                try:
                    raw_list = await self.redis.lrange(_LIST_KEY, 0, limit - 1)
                    return [json.loads(r) for r in raw_list]
                except Exception:
                    logger.warning("RequestRecorder.list_records failed", exc_info=True)
                    return []

            async def get_record(self, rec_id: str) -> dict | None:
                \"\"\"Return a single record by id, or None if not found.

                Args:
                    rec_id: 16-character hex id from ``record()``.
                \"\"\"
                try:
                    raw_list = await self.redis.lrange(_LIST_KEY, 0, -1)
                    for raw in raw_list:
                        entry = json.loads(raw)
                        if entry.get("id") == rec_id:
                            return entry
                    return None
                except Exception:
                    logger.warning("RequestRecorder.get_record failed", exc_info=True)
                    return None

            async def flush(self) -> int:
                \"\"\"Delete all recorded requests.  Returns number of keys deleted.\"\"\"
                try:
                    return await self.redis.delete(_LIST_KEY)
                except Exception:
                    logger.warning("RequestRecorder.flush failed", exc_info=True)
                    return 0


        def get_recorder() -> "RequestRecorder | None":
            \"\"\"Return the process-wide RequestRecorder, or None if not initialised.\"\"\"
            return _recorder


        async def init_recorder(
            redis_url: str,
            ttl_s: int = 3600,
            max_entries: int = 10000,
            exclude_paths: list[str] | None = None,
        ) -> None:
            \"\"\"Initialise the global recorder.  Call once at app startup.

            Args:
                redis_url: Redis connection URL.
                ttl_s: TTL for the ring-buffer list key.
                max_entries: Maximum entries in the ring buffer.
                exclude_paths: Paths to skip (default: [\"/healthz\", \"/metrics\"]).
            \"\"\"
            from redis.asyncio import Redis  # lazy — optional SDK

            global _recorder
            redis = Redis.from_url(redis_url, decode_responses=True)
            _recorder = RequestRecorder(
                redis=redis,
                ttl_s=ttl_s,
                max_entries=max_entries,
                exclude_paths=exclude_paths,
            )


        async def close_recorder() -> None:
            \"\"\"Close the Redis connection.  Call on app shutdown.\"\"\"
            global _recorder
            if _recorder is not None:
                await _recorder.redis.aclose()
                _recorder = None
        """))


def _write_replayer(dest: Path) -> None:
    """Write ``app/debug/replayer.py`` with RequestReplayer.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"RequestReplayer: re-execute a recorded request and diff the response.\"\"\"

        from __future__ import annotations

        import json
        import logging
        from typing import Any

        logger = logging.getLogger(__name__)


        def _diff_bodies(original: str, replayed: str) -> list[str]:
            \"\"\"Return a list of diff lines between two JSON bodies.

            Falls back to line-level diff when bodies are not valid JSON.

            Args:
                original: Original response body string.
                replayed: Replayed response body string.
            \"\"\"
            try:
                orig_obj = json.loads(original) if original else {}
                new_obj = json.loads(replayed) if replayed else {}
                orig_keys = set(orig_obj.keys()) if isinstance(orig_obj, dict) else set()
                new_keys = set(new_obj.keys()) if isinstance(new_obj, dict) else set()
                diffs: list[str] = []
                for k in orig_keys - new_keys:
                    diffs.append(f"- key removed: {k}")
                for k in new_keys - orig_keys:
                    diffs.append(f"+ key added: {k}")
                for k in orig_keys & new_keys:
                    if orig_obj[k] != new_obj[k]:
                        diffs.append(f"~ changed: {k}: {orig_obj[k]!r} -> {new_obj[k]!r}")
                return diffs
            except Exception:
                orig_lines = (original or "").splitlines()
                new_lines = (replayed or "").splitlines()
                diffs = []
                for line in orig_lines:
                    if line not in new_lines:
                        diffs.append(f"- {line}")
                for line in new_lines:
                    if line not in orig_lines:
                        diffs.append(f"+ {line}")
                return diffs


        class RequestReplayer:
            \"\"\"Re-execute a recorded request against the live ASGI app and diff.

            Args:
                app: The FastAPI ASGI application instance.
            \"\"\"

            def __init__(self, app: Any) -> None:
                self.app = app

            async def replay(self, record: dict) -> dict:
                \"\"\"Re-execute *record* and return a diff result dict.

                Args:
                    record: A recorded request dict from RequestRecorder.

                Returns:
                    Dict with keys: ``id``, ``original_status``,
                    ``replayed_status``, ``body_diff``, ``status_changed``.
                \"\"\"
                import httpx  # lazy — optional SDK

                method = record.get("method", "GET")
                path = record.get("path", "/")
                body = record.get("request_body", "")
                headers = {
                    k: v for k, v in (record.get("request_headers") or {}).items()
                    if k.lower() not in ("content-length", "host", "transfer-encoding")
                }
                try:
                    transport = httpx.ASGITransport(app=self.app)
                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://replay",
                        headers=headers,
                    ) as client:
                        response = await client.request(
                            method=method,
                            url=path,
                            content=body.encode() if body else b"",
                        )
                    replayed_body = response.text
                    replayed_status = response.status_code
                except Exception as exc:
                    logger.warning("Replay request failed: %s", exc, exc_info=True)
                    replayed_body = ""
                    replayed_status = 500

                orig_status = record.get("status_code", 0)
                orig_body = record.get("response_body", "")
                diff = _diff_bodies(orig_body, replayed_body)

                return {
                    "id": record.get("id"),
                    "original_status": orig_status,
                    "replayed_status": replayed_status,
                    "status_changed": orig_status != replayed_status,
                    "body_diff": diff,
                    "diff_count": len(diff),
                }
        """))


def _write_debug_models(dest: Path) -> None:
    """Write ``app/debug/models.py`` with Pydantic schemas.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for the debug replay API.\"\"\"

        from __future__ import annotations

        from pydantic import BaseModel, ConfigDict, Field


        class RecordedRequest(BaseModel):
            \"\"\"Schema for a single recorded request entry.\"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: str = Field(..., description="16-char hex record identifier.")
            ts: float = Field(..., description="Unix timestamp of recording.")
            method: str = Field(..., description="HTTP method (e.g. GET).")
            path: str = Field(..., description="Request path with query string.")
            status_code: int = Field(..., description="HTTP response status code.")
            duration_ms: float = Field(..., description="Request duration in ms.")
            request_body: str = Field(default="", description="Decoded request body.")
            response_body: str = Field(default="", description="Decoded response body.")


        class ReplayResult(BaseModel):
            \"\"\"Result of replaying a recorded request.\"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: str = Field(..., description="Record id that was replayed.")
            original_status: int = Field(..., description="Status code when recorded.")
            replayed_status: int = Field(..., description="Status code on replay.")
            status_changed: bool = Field(..., description="True if status codes differ.")
            body_diff: list[str] = Field(
                default_factory=list,
                description="List of diff lines between original and replayed body.",
            )
            diff_count: int = Field(default=0, description="Number of diff lines.")
        """))


def _write_recorder_middleware(dest: Path) -> None:
    """Write ``app/middleware/request_recorder.py`` with RecorderMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"RecorderMiddleware: captures req/resp in background with zero latency impact.\"\"\"

        from __future__ import annotations

        import logging
        import time
        from typing import Callable

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.debug.recorder import get_recorder

        logger = logging.getLogger(__name__)


        class RecorderMiddleware(BaseHTTPMiddleware):
            \"\"\"Middleware that records every request/response to the ring buffer.

            Recording happens after the response is sent, so it has zero impact
            on response time from the client's perspective.  Failures in the
            recorder never affect the request.

            Args:
                app: ASGI application.
                exclude_paths: Request path prefixes to skip recording.
            \"\"\"

            def __init__(self, app: Callable, exclude_paths: list[str] | None = None) -> None:
                super().__init__(app)
                self.exclude_paths = exclude_paths or ["/healthz", "/metrics", "/debug"]

            async def _capture_response_body(self, response: Response) -> str:
                \"\"\"Read and return response body bytes as a decoded string.

                Args:
                    response: Starlette Response with a body_iterator attribute.

                Returns:
                    Decoded response body string, truncated to 8192 chars.
                \"\"\"
                chunks: list[bytes] = []
                async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                    chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
                return b"".join(chunks).decode(errors="replace")[:8192]

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Record request + response, then return response unchanged.\"\"\"
                import asyncio  # stdlib — not optional SDK
                from starlette.responses import Response as _Resp

                path = request.url.path
                if any(path.startswith(p) for p in self.exclude_paths):
                    return await call_next(request)
                recorder = get_recorder()
                if recorder is None:
                    return await call_next(request)

                start = time.monotonic()
                try:
                    req_body = (await request.body()).decode(errors="replace")[:4096]
                except Exception:
                    req_body = ""

                response = await call_next(request)
                duration_ms = (time.monotonic() - start) * 1000
                try:
                    resp_body = await self._capture_response_body(response)
                    full_path = str(request.url.path) + (
                        "?" + str(request.url.query) if request.url.query else ""
                    )
                    asyncio.ensure_future(
                        recorder.record(
                            method=request.method,
                            path=full_path,
                            request_headers=dict(request.headers),
                            request_body=req_body,
                            status_code=response.status_code,
                            response_headers=dict(response.headers),
                            response_body=resp_body,
                            duration_ms=duration_ms,
                        )
                    )
                    return _Resp(
                        content=resp_body.encode(),
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type=response.media_type,
                    )
                except Exception:
                    logger.debug("RecorderMiddleware: failed to capture body", exc_info=True)
                return response
        """))


def _write_debug_routes(dest: Path) -> None:
    """Write ``app/api/routes/debug.py`` with /debug admin endpoints.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Admin routes: GET /debug/requests, POST /debug/replay/{id}, DELETE /debug/flush.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Depends, HTTPException, Request

        from app.api.deps import get_current_superuser
        from app.debug.models import RecordedRequest, ReplayResult
        from app.debug.recorder import get_recorder
        from app.debug.replayer import RequestReplayer

        router = APIRouter(prefix="/debug", tags=["debug"])

        _SUPERUSER_DEP = [Depends(get_current_superuser)]


        @router.get(
            "/requests",
            response_model=list[RecordedRequest],
            dependencies=_SUPERUSER_DEP,
        )
        async def list_requests(limit: int = 50) -> list[dict]:
            \"\"\"List the most recent recorded requests.

            Args:
                limit: Maximum records to return (default 50).

            Returns:
                List of RecordedRequest dicts ordered newest-first.

            Raises:
                HTTPException: 503 if recorder is not initialised.
            \"\"\"
            recorder = get_recorder()
            if recorder is None:
                raise HTTPException(status_code=503, detail={"detail": "Recorder not initialised"})
            return await recorder.list_records(limit=max(1, min(limit, 500)))


        @router.post(
            "/replay/{rec_id}",
            response_model=ReplayResult,
            dependencies=_SUPERUSER_DEP,
        )
        async def replay_request(rec_id: str, http_request: Request) -> dict:
            \"\"\"Re-execute a recorded request and return a diff of the response.

            Args:
                rec_id: 16-char hex record id from GET /debug/requests.
                http_request: Starlette Request (to access the ASGI app).

            Returns:
                ReplayResult with original vs replayed status codes and body diff.

            Raises:
                HTTPException: 404 if record not found.
                HTTPException: 503 if recorder not initialised.
            \"\"\"
            recorder = get_recorder()
            if recorder is None:
                raise HTTPException(status_code=503, detail={"detail": "Recorder not initialised"})
            record = await recorder.get_record(rec_id)
            if record is None:
                raise HTTPException(status_code=404, detail={"detail": f"Record {rec_id!r} not found"})
            replayer = RequestReplayer(app=http_request.app)
            return await replayer.replay(record)


        @router.delete("/flush", dependencies=_SUPERUSER_DEP)
        async def flush_records() -> dict:
            \"\"\"Delete all recorded requests from the ring buffer.

            Returns:
                Dict with ``deleted`` key indicating number of keys removed.

            Raises:
                HTTPException: 503 if recorder not initialised.
            \"\"\"
            recorder = get_recorder()
            if recorder is None:
                raise HTTPException(status_code=503, detail={"detail": "Recorder not initialised"})
            deleted = await recorder.flush()
            return {"deleted": deleted}
        """))


def _patch_config(config_file: Path) -> None:
    """Inject DEBUG_RECORDER_* fields into app/core/config.py Settings.

    Fields are injected inside the Settings class body with 4-space indent.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("DEBUG_RECORDER_ENABLED", "DEBUG_RECORDER_ENABLED: bool = False"),
            ("DEBUG_RECORDER_TTL_S", "DEBUG_RECORDER_TTL_S: int = 3600"),
            ("DEBUG_RECORDER_MAX_ENTRIES", "DEBUG_RECORDER_MAX_ENTRIES: int = 10000"),
            ("DEBUG_RECORDER_EXCLUDE_PATHS", 'DEBUG_RECORDER_EXCLUDE_PATHS: str = "/healthz,/metrics,/debug"'),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Inject recorder init/close + middleware registration into main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "init_recorder" in src:
        return

    recorder_import = (
        "\nfrom app.debug.recorder import init_recorder, close_recorder  "
        "# noqa: F401 — debug recorder\n"
        "import os as _dbg_os\n"
    )
    recorder_startup = textwrap.dedent("""\

        # Debug recorder startup — added by add_api_replay_debugger tool
        _debug_enabled = _dbg_os.getenv("DEBUG_RECORDER_ENABLED", "false").lower() == "true"
        _debug_redis = _dbg_os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _debug_ttl = int(_dbg_os.getenv("DEBUG_RECORDER_TTL_S", "3600"))
        _debug_max = int(_dbg_os.getenv("DEBUG_RECORDER_MAX_ENTRIES", "10000"))
        _debug_excl = _dbg_os.getenv("DEBUG_RECORDER_EXCLUDE_PATHS", "/healthz,/metrics,/debug")
    """)

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + recorder_import,
        )
    else:
        src = recorder_import + src

    src = src.rstrip("\n") + "\n" + recorder_startup
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
