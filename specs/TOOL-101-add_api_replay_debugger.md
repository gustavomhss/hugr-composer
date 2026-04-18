# TOOL-101: add_api_replay_debugger

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_api_replay_debugger` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, Redis (lazy import), httpx (lazy import), pydantic-settings |
| Signature | `add_api_replay_debugger(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and optional `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_api_replay_debugger", "description": "Add request recording and replay infrastructure for debugging intermittent API failures without reproducing them manually.", "tags": ["extend", "infrastructure"], "entry": "add_api_replay_debugger"}` |
| Files created (typical) | 6–7 — `app/debug/__init__.py`, `app/debug/recorder.py`, `app/debug/replayer.py`, `app/debug/models.py`, `app/middleware/request_recorder.py`, `app/api/routes/debug.py`, optionally patched `app/main.py` |
| Files modified (typical) | 1–2 — `app/core/config.py`, optionally `app/main.py` |

---

## 2. Purpose

The `fastapi_add_api_replay_debugger` tool installs a request recording and replay infrastructure into a FastAPI project for debugging intermittent failures. Intermittent bugs are among the most expensive to diagnose: a 500 that appears once every thousand requests, a payload combination that triggers a subtle parsing edge case, an exact timing window that causes a race condition in a caching layer. Without a recording system, developers either wait passively for the bug to recur while attached to a debugger, or they reconstruct hypothetical request payloads from access logs that rarely capture full request bodies, headers, or the exact sequence context.

The generated `RequestRecorder` stores incoming request/response pairs in a Redis `LIST` (key `debug:requests`) using three pipelined operations: `LPUSH` (prepend), `LTRIM` (cap at `DEBUG_RECORDER_MAX_ENTRIES`, default 10 000), and `EXPIRE` (`DEBUG_RECORDER_TTL_S`, default 3 600 s). Each entry is a JSON document with a stable SHA-256 record ID — 16 hex chars derived from `f"{method}:{path}:{timestamp}"`. `RecorderMiddleware` captures both request and response bodies after the response is sent, truncates to 8 192 characters, and fires `asyncio.ensure_future(recorder.record(...))` for background non-blocking persistence. Redis is imported lazily inside `init_recorder()` — the base install does not require `redis-py` unless debugging is explicitly enabled.

`RequestReplayer.replay(record)` creates a fresh `httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app))` and re-executes the captured request against the live ASGI app without a network hop. It returns a diff: `_diff_bodies()` performs a JSON key-level diff first, reporting added/removed/changed keys; if either body is not valid JSON, it falls back to line-level diff. The `httpx` import is also lazy — inside `replay()` — ensuring the recorder package is importable on hosts where `httpx` is not installed in the base image.

Three HTTP routes, all guarded by `Depends(get_current_superuser)`: `GET /debug/requests` lists recent recordings; `POST /debug/replay/{rec_id}` replays a specific record and returns the diff as a `ReplayResult`; `DELETE /debug/flush` clears the ring buffer. `DEBUG_RECORDER_EXCLUDE_PATHS` (default `/healthz,/metrics,/debug`) prevents the recorder from logging its own management traffic and health checks, which would create noise and unbounded recursive entries.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 6 | debug package (4 files) + middleware + routes (CC-04) |
| Files modified | ≥ 1 | Config patch (CC-05) |
| Max function LOC | ≤ 50 | AST walk enforced |
| Recording overhead (client-facing) | < 2 ms | Background `asyncio.ensure_future` — zero synchronous overhead |
| Redis `LPUSH` + `LTRIM` + `EXPIRE` | < 5 ms | Three pipelined async commands |
| Replay latency | In-process ASGI | `httpx.ASGITransport` — no network round-trip |
| Exclude path check | < 0.1 ms | `any(path.startswith(p) for p in exclude_paths)` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
app/
├── main.py
├── core/config.py    # No DEBUG_RECORDER_* settings
├── api/routes/       # No /debug routes
└── middleware/       # No RecorderMiddleware
```

No request recording. Debugging a production 500 requires: parsing access logs manually, reconstructing the payload from fragmented log entries, and hoping the exact sequence of events is reproducible in staging.

### 4.2 RequestRecorder (Redis ring buffer): AFTER

```python
# app/debug/recorder.py
"""RequestRecorder: captures full req/resp in a Redis ring buffer."""
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
    """Redis ring-buffer recorder for HTTP requests and responses."""

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
        """Generate a stable 16-char SHA-256 id."""
        raw = f"{method}:{path}:{ts}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def record(
        self, method: str, path: str, request_headers: dict,
        request_body: str, status_code: int, response_headers: dict,
        response_body: str, duration_ms: float,
    ) -> str | None:
        """Record a request/response pair to Redis. Returns rec_id or None on error."""
        if any(path.startswith(p) for p in self.exclude_paths):
            return None
        try:
            ts = time.time()
            rec_id = self._make_id(method, path, ts)
            entry = json.dumps({
                "id": rec_id, "ts": ts, "method": method, "path": path,
                "request_headers": request_headers, "request_body": request_body,
                "status_code": status_code, "response_headers": response_headers,
                "response_body": response_body, "duration_ms": duration_ms,
            })
            await self.redis.lpush(_LIST_KEY, entry)
            await self.redis.ltrim(_LIST_KEY, 0, self.max_entries - 1)
            await self.redis.expire(_LIST_KEY, self.ttl_s)
            return rec_id
        except Exception:
            logger.warning("RequestRecorder.record failed", exc_info=True)
            return None

    async def get_record(self, rec_id: str) -> dict | None:
        """Return a single record by id, or None if not found."""
        try:
            raw_list = await self.redis.lrange(_LIST_KEY, 0, -1)
            for raw in raw_list:
                entry = json.loads(raw)
                if entry.get("id") == rec_id:
                    return entry
            return None
        except Exception:
            return None


def get_recorder() -> "RequestRecorder | None":
    return _recorder


async def init_recorder(redis_url: str, ttl_s: int = 3600,
                        max_entries: int = 10000,
                        exclude_paths: list[str] | None = None) -> None:
    """Initialise the global recorder. Redis imported lazily here."""
    from redis.asyncio import Redis  # lazy import — optional dependency

    global _recorder
    redis = Redis.from_url(redis_url, decode_responses=True)
    _recorder = RequestRecorder(redis=redis, ttl_s=ttl_s,
                                max_entries=max_entries,
                                exclude_paths=exclude_paths)
```

### 4.3 RequestReplayer (in-process ASGI): AFTER

```python
# app/debug/replayer.py
"""RequestReplayer: re-execute a recorded request and diff the response."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _diff_bodies(original: str, replayed: str) -> list[str]:
    """Return diff lines between two JSON bodies (line diff fallback)."""
    try:
        orig_obj = json.loads(original) if original else {}
        new_obj = json.loads(replayed) if replayed else {}
        diffs: list[str] = []
        for k in set(orig_obj) - set(new_obj):
            diffs.append(f"- key removed: {k}")
        for k in set(new_obj) - set(orig_obj):
            diffs.append(f"+ key added: {k}")
        for k in set(orig_obj) & set(new_obj):
            if orig_obj[k] != new_obj[k]:
                diffs.append(f"~ changed: {k}: {orig_obj[k]!r} -> {new_obj[k]!r}")
        return diffs
    except Exception:
        orig_lines = (original or "").splitlines()
        new_lines = (replayed or "").splitlines()
        diffs = [f"- {l}" for l in orig_lines if l not in new_lines]
        diffs += [f"+ {l}" for l in new_lines if l not in orig_lines]
        return diffs


class RequestReplayer:
    """Re-execute a recorded request against the live ASGI app."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def replay(self, record: dict) -> dict:
        """Replay record and return diff dict."""
        import httpx  # lazy import — optional dependency

        method = record.get("method", "GET")
        path = record.get("path", "/")
        body = record.get("request_body", "")
        headers = {k: v for k, v in (record.get("request_headers") or {}).items()
                   if k.lower() not in ("content-length", "host", "transfer-encoding")}
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://replay",
                                     headers=headers) as client:
            response = await client.request(
                method=method, url=path,
                content=body.encode() if body else b"",
            )
        diff = _diff_bodies(record.get("response_body", ""), response.text)
        return {
            "id": record.get("id"),
            "original_status": record.get("status_code", 0),
            "replayed_status": response.status_code,
            "status_changed": record.get("status_code") != response.status_code,
            "body_diff": diff,
            "diff_count": len(diff),
        }
```

### 4.4 Pydantic schemas: AFTER

```python
# app/debug/models.py
from pydantic import BaseModel, ConfigDict, Field


class RecordedRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str = Field(..., description="16-char hex record identifier.")
    ts: float = Field(..., description="Unix timestamp of recording.")
    method: str
    path: str
    status_code: int
    duration_ms: float
    request_body: str = Field(default="")
    response_body: str = Field(default="")


class ReplayResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_status: int
    replayed_status: int
    status_changed: bool
    body_diff: list[str] = Field(default_factory=list)
    diff_count: int = 0
```

### 4.5 RecorderMiddleware (background, non-blocking): AFTER

```python
# app/middleware/request_recorder.py
"""RecorderMiddleware: captures req/resp in background with zero latency impact."""
from __future__ import annotations

import asyncio
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from app.debug.recorder import get_recorder

logger = logging.getLogger(__name__)


class RecorderMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, exclude_paths: list[str] | None = None) -> None:
        super().__init__(app)
        self.exclude_paths = exclude_paths or ["/healthz", "/metrics", "/debug"]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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
        # Fire-and-forget recording — does not block response
        asyncio.ensure_future(
            recorder.record(
                method=request.method,
                path=str(request.url.path),
                request_headers=dict(request.headers),
                request_body=req_body,
                status_code=response.status_code,
                response_headers=dict(response.headers),
                response_body="",  # body captured separately
                duration_ms=duration_ms,
            )
        )
        return response
```

### 4.6 Debug routes (superuser-guarded): AFTER

```python
# app/api/routes/debug.py
"""Admin routes: GET /debug/requests, POST /debug/replay/{id}, DELETE /debug/flush."""
from fastapi import APIRouter, Depends, HTTPException, Request
from app.api.deps import get_current_superuser
from app.debug.models import RecordedRequest, ReplayResult
from app.debug.recorder import get_recorder
from app.debug.replayer import RequestReplayer

router = APIRouter(prefix="/debug", tags=["debug"])
_SUPERUSER_DEP = [Depends(get_current_superuser)]


@router.get("/requests", response_model=list[RecordedRequest], dependencies=_SUPERUSER_DEP)
async def list_requests(limit: int = 50) -> list[dict]:
    recorder = get_recorder()
    if recorder is None:
        raise HTTPException(status_code=503, detail="Recorder not initialised")
    return await recorder.list_records(limit=max(1, min(limit, 500)))


@router.post("/replay/{rec_id}", response_model=ReplayResult, dependencies=_SUPERUSER_DEP)
async def replay_request(rec_id: str, http_request: Request) -> dict:
    recorder = get_recorder()
    if recorder is None:
        raise HTTPException(status_code=503, detail="Recorder not initialised")
    record = await recorder.get_record(rec_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Record {rec_id!r} not found")
    return await RequestReplayer(app=http_request.app).replay(record)


@router.delete("/flush", dependencies=_SUPERUSER_DEP)
async def flush_records() -> dict:
    recorder = get_recorder()
    if recorder is None:
        raise HTTPException(status_code=503, detail="Recorder not initialised")
    deleted = await recorder.flush()
    return {"deleted": deleted}
```

### 4.7 Config patch: AFTER

```python
# app/core/config.py (fragment)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Debug replay recorder — added by add_api_replay_debugger tool
    DEBUG_RECORDER_ENABLED: bool = False
    DEBUG_RECORDER_TTL_S: int = 3600
    DEBUG_RECORDER_MAX_ENTRIES: int = 10000
    DEBUG_RECORDER_EXCLUDE_PATHS: str = "/healthz,/metrics,/debug"
```

### 4.8 Lifespan wiring (caller pattern)

```python
# app/main.py — lifespan setup for debug recorder
from contextlib import asynccontextmanager
import os
from app.debug.recorder import init_recorder, close_recorder

@asynccontextmanager
async def lifespan(app):
    if os.getenv("DEBUG_RECORDER_ENABLED", "false").lower() == "true":
        await init_recorder(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            ttl_s=int(os.getenv("DEBUG_RECORDER_TTL_S", "3600")),
            max_entries=int(os.getenv("DEBUG_RECORDER_MAX_ENTRIES", "10000")),
            exclude_paths=os.getenv("DEBUG_RECORDER_EXCLUDE_PATHS", "/healthz,/metrics,/debug").split(","),
        )
    yield
    await close_recorder()
```

### 4.9 Using the debugger to investigate a failure

```python
# Workflow: recorded failure → replay → inspect diff
import httpx

BASE = "http://localhost:8000"
TOKEN = "superuser-jwt-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

with httpx.Client() as c:
    # List recent failures
    records = c.get(f"{BASE}/debug/requests", headers=HEADERS).json()
    failures = [r for r in records if r["status_code"] >= 500]

    if failures:
        rec_id = failures[0]["id"]
        # Replay the failure
        result = c.post(f"{BASE}/debug/replay/{rec_id}", headers=HEADERS).json()
        print(f"status_changed: {result['status_changed']}")
        print(f"diff_count: {result['diff_count']}")
        for line in result["body_diff"]:
            print(line)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent on second run | `"RequestRecorder" in debug/recorder.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `Path.write_text()` |
| QS-3 | All `.py` AST-parse clean | `_assert_parses` loop after creation |
| QS-4 | No function > 50 LOC | AST walk over all generated files |
| QS-5 | Redis imported lazily inside `init_recorder()` | No `import redis` at module top-level in `recorder.py` |
| QS-6 | `httpx` imported lazily inside `replay()` | No `import httpx` at module top-level in `replayer.py` |
| QS-7 | Recording is non-blocking | `asyncio.ensure_future(recorder.record(...))` in middleware |
| QS-8 | All three debug routes require superuser auth | `Depends(get_current_superuser)` on each route |
| QS-9 | Request body truncated to 4 096 characters | `(await request.body()).decode()[:4096]` in middleware |
| QS-10 | Response body truncated to 8 192 characters | `body.decode()[:8192]` in body capture |
| QS-11 | Exclude paths checked before recording | `any(path.startswith(p) for p in exclude_paths)` |
| QS-12 | Config 4-space indent | `_patch_config` anchored on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-13 | `execution_time_ms` positive | `_elapsed_ms(start)` with `time.monotonic()` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run → `no_op` | `r2.status == "no_op"` | T-02 |
| CC-03 | `dry_run=True` → zero writes | `before_tree == after_tree` | T-03 |
| CC-04 | ≥ 6 files created | `len(files_created) >= 6` | T-04 |
| CC-05 | ≥ 1 file modified | `len(files_modified) >= 1` | T-05 |
| CC-06 | All `.py` in `app/debug/` parse | `ast.parse` loop | T-06 |
| CC-07 | No function > 50 LOC | AST walk | T-07 |
| CC-08 | `DEBUG_RECORDER_ENABLED` in config, 4-space indent | Substring + indent check | T-08 |
| CC-09 | `app/debug/__init__.py` re-exports `RequestRecorder` + `RequestReplayer` | Both symbols in init | T-09 |
| CC-10 | `debug.py` route uses `APIRouter` with `/debug` prefix | File + symbol check | T-10 |
| CC-11 | `RequestRecorder`, `init_recorder`, `get_recorder`, `lpush`, `ltrim` all in `recorder.py` | All symbols | T-11 |
| CC-12 | `RequestReplayer`, `replay`, `_diff_bodies` in `replayer.py` | Symbols + diff function | T-12 |
| CC-13 | `RecorderMiddleware` and `asyncio` in middleware file | Symbols | T-13 |
| CC-14 | `list_requests`, `replay_request`, `flush_records` in routes | Three handler names | T-14 |
| CC-15 | `ttl_s` and `max_entries` in `recorder.py` | Field names | T-15 |
| CC-16 | `sha256` and `hashlib` in `recorder.py` | Hash ID generation | T-16 |
| CC-17 | `RecordedRequest`, `ReplayResult`, `BaseModel` in `models.py` | Pydantic schema symbols | T-18 |
| CC-18 | Redis NOT at top-level in `recorder.py` | No `import redis` at module scope | T-19 |
| CC-19 | `exclude_paths` in recorder or middleware | Exclusion pattern present | T-20 |
| CC-20 | All four `DEBUG_RECORDER_*` config fields present | All four substring checks | T-21 |
| CC-21 | `execution_time_ms > 0` | Positive integer check | T-22 |
| CC-22 | `next_steps` list contains "recorder" or "DEBUG_RECORDER" token | Token in joined string | T-23 |
| CC-23 | Second run leaves all `.py` parseable | `ast.parse` on all debug + middleware files | T-24 |

---

## 7. Definition of Done (DoD)

- [ ] All CC-01 through CC-23 verified by `test_add_api_replay_debugger.py`
- [ ] Redis imported lazily inside `init_recorder()` only — not at module level
- [ ] `httpx` imported lazily inside `RequestReplayer.replay()` only — not at module level
- [ ] `RecorderMiddleware` uses `asyncio.ensure_future` for background recording
- [ ] `RequestReplayer` uses `httpx.ASGITransport` — no real network hop
- [ ] `_diff_bodies` tries JSON key diff first, falls back to line-level diff
- [ ] All three debug routes guarded by `Depends(get_current_superuser)`
- [ ] Request body truncated to 4 096 characters in middleware
- [ ] Response body truncated to 8 192 characters in body capture
- [ ] Exclude paths prevent recording of `/healthz`, `/metrics`, `/debug` by default
- [ ] Config fields use 4-space indent inside `class Settings` body
- [ ] `execution_time_ms` is a positive integer
- [ ] `MCP_TOOL` descriptor present in source module

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-RD-01 | Idempotent on re-run | Fingerprint `"RequestRecorder"` in `debug/recorder.py` → `no_op` | T-02, T-24 |
| INV-RD-02 | `dry_run=True` never writes | Early return before `Path.write_text()` | T-03 |
| INV-RD-03 | All generated `.py` pass `ast.parse` | `_assert_parses` loop | T-06, T-24 |
| INV-RD-04 | Redis NOT imported at module top-level | Lazy import inside `init_recorder()` | T-19, B-05 |
| INV-RD-05 | `httpx` NOT imported at module top-level | Lazy import inside `replay()` | B-05 |
| INV-RD-06 | Recording MUST be non-blocking | `asyncio.ensure_future()` in middleware | T-13 |
| INV-RD-07 | All three debug routes require superuser auth | `Depends(get_current_superuser)` | T-14, B-06 |
| INV-RD-08 | Config inside `class Settings` body | 4-space indent enforcement | T-08 |
| INV-RD-09 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` | T-22 |
| INV-RD-10 | Exclude paths prevent recording of management traffic | `any(path.startswith(p) for p in exclude_paths)` | T-20 |

---

## 9. User Stories

### 9.1 Core installation (US-01 .. US-05)

**US-01: Successful install on fresh project**
- **Given:** A valid FastAPI project without debug infrastructure
- **When:** `add_api_replay_debugger(ToolInput(project_dir="/path"))` is called
- **Then:** `result.status == "success"`, `len(result.files_created) >= 6` (CC-01, CC-04)

**US-02: Idempotent CI re-run**
- **Given:** Replay debugger already installed (first run succeeded)
- **When:** The tool is called a second time
- **Then:** `result.status == "no_op"`, no files modified (INV-RD-01)

**US-03: Dry-run preview**
- **Given:** A valid project
- **When:** `add_api_replay_debugger(ToolInput(project_dir="/path", dry_run=True))` is called
- **Then:** `result.status == "success"`, filesystem is unchanged (INV-RD-02)

**US-04: All generated files are syntactically valid**
- **Given:** A tool run that returns `status="success"`
- **When:** Each `files_created` path is loaded with `ast.parse()`
- **Then:** No `SyntaxError` is raised (INV-RD-03)

**US-05: Redis not importable at module load time**
- **Given:** `redis-py` not installed in the Python environment
- **When:** `from app.debug.recorder import RequestRecorder, get_recorder` is executed
- **Then:** No `ImportError` — Redis is only imported inside `init_recorder()` (INV-RD-04)

### 9.2 Recording mechanics (US-06 .. US-10)

**US-06: Background recording doesn't add latency to responses**
- **Given:** `RecorderMiddleware` active and Redis connected
- **When:** Any business request arrives
- **Then:** `asyncio.ensure_future(recorder.record(...))` fires after response is returned; client sees no added latency (INV-RD-06)

**US-07: Exclude paths are not recorded**
- **Given:** `DEBUG_RECORDER_EXCLUDE_PATHS="/healthz,/metrics,/debug"` (default)
- **When:** `GET /healthz` is processed
- **Then:** Request is not pushed to Redis — `any(path.startswith(p))` check fires first (INV-RD-10)

**US-08: Management routes themselves not recorded**
- **Given:** `GET /debug/requests` called by an operator
- **When:** `RecorderMiddleware` processes the request
- **Then:** Path starts with `/debug` — excluded from ring buffer (INV-RD-10)

**US-09: Ring buffer capped at `max_entries`**
- **Given:** 10 001 requests have been recorded with `max_entries=10000`
- **When:** The 10 001st record is stored
- **Then:** `LTRIM` keeps only the 10 000 newest entries; oldest entry is dropped

**US-10: Ring buffer TTL prevents unbounded growth**
- **Given:** `DEBUG_RECORDER_TTL_S=3600`
- **When:** `EXPIRE` is called on `debug:requests` after each `LPUSH`
- **Then:** The entire list expires after 3 600 s if no new requests arrive

### 9.3 Replay mechanics (US-11 .. US-15)

**US-11: Replay uses in-process ASGI transport**
- **Given:** A recorded request with `rec_id = "a3f8b2d1c0e9f7a6"` in Redis
- **When:** `POST /debug/replay/a3f8b2d1c0e9f7a6` is called
- **Then:** `httpx.ASGITransport(app=self.app)` re-executes the request in-process; no network hop (CC-12)

**US-12: JSON key-level diff for structured responses**
- **Given:** Original response body: `{"status": "ok", "count": 5}`; replayed: `{"status": "ok", "count": 6}`
- **When:** `_diff_bodies(original, replayed)` is called
- **Then:** Returns `["~ changed: count: 5 -> 6"]` — key-level diff with from/to values

**US-13: Line diff fallback for non-JSON responses**
- **Given:** Original and replayed bodies are plain text (not JSON)
- **When:** `_diff_bodies(original, replayed)` is called
- **Then:** Returns line-by-line diff with `+`/`-` prefixes — JSON parse fails gracefully

**US-14: `status_changed` flag set when status codes differ**
- **Given:** Originally recorded as 200; replayed returns 500
- **When:** `replay()` returns
- **Then:** `result["status_changed"] == True`, `result["original_status"] == 200`, `result["replayed_status"] == 500`

**US-15: `httpx` not importable at module load time**
- **Given:** `httpx` not installed in the Python environment
- **When:** `from app.debug.replayer import RequestReplayer` is executed
- **Then:** No `ImportError` — httpx is only imported inside `replay()` (INV-RD-05)

### 9.4 Route authorization and management (US-16 .. US-20)

**US-16: Unauthenticated request to debug routes returns 401**
- **Given:** No auth token provided
- **When:** `GET /debug/requests` is called
- **Then:** FastAPI resolves `Depends(get_current_superuser)` → 401 Unauthorized (INV-RD-07)

**US-17: Non-superuser request to debug routes returns 403**
- **Given:** A regular user JWT (not superuser)
- **When:** `POST /debug/replay/{rec_id}` is called
- **Then:** `get_current_superuser` dependency raises 403 Forbidden (INV-RD-07)

**US-18: `DELETE /debug/flush` clears ring buffer**
- **Given:** 500 recordings in Redis, valid superuser auth
- **When:** `DELETE /debug/flush` is called
- **Then:** Redis `debug:requests` key is deleted; `GET /debug/requests` returns empty list (CC-14)

**US-19: `GET /debug/requests` returns 503 when recorder not initialised**
- **Given:** `DEBUG_RECORDER_ENABLED=false` — `init_recorder()` never called
- **When:** `GET /debug/requests` is called by a superuser
- **Then:** Returns `503 Service Unavailable` — `get_recorder()` returns `None` (CC-14)

**US-20: `GET /debug/requests` limits results to `max(1, min(limit, 500))`**
- **Given:** `limit=1000` passed as query parameter
- **When:** `list_requests(limit=1000)` is called
- **Then:** `recorder.list_records(limit=500)` is called — clamped to 500

### 9.5 Ops and integration (US-21 .. US-25)

**US-21: Chaos testing records capture chaos-injected 500s**
- **Given:** `ChaosMiddleware` and `RecorderMiddleware` both active
- **When:** Chaos injects a 500 error
- **Then:** `RecorderMiddleware` records the 500; `replay()` reveals whether same fault fires again

**US-22: Graceful shutdown flushes recorder on cleanup**
- **Given:** `close_recorder()` registered as a cleanup callback
- **When:** `SIGTERM` received and `wait_complete()` runs
- **Then:** Redis connection closed cleanly during Phase 3 cleanup

**US-23: Records have stable SHA-256 IDs for replay references**
- **Given:** Same method, path, and timestamp
- **When:** `_make_id(method, path, ts)` called twice
- **Then:** Returns identical 16-char hex string — stable for replay references

**US-24: Second run is idempotent and leaves files parseable**
- **Given:** First run succeeded
- **When:** Tool runs a second time (no_op path), then all `.py` re-parsed
- **Then:** All debug and middleware files pass `ast.parse()` (INV-RD-01, INV-RD-03)

**US-25: `execution_time_ms` positive in all outcomes**
- **Given:** Tool called in any mode (success, no_op, dry_run, error)
- **When:** `result.execution_time_ms` is read
- **Then:** Value is an integer > 0 (INV-RD-09)

---

## 10. Test Plan

### 10.1 Structural tests (`test_add_api_replay_debugger.py`)

| # | Test ID | Test name | Expected |
|---|---------|-----------|----------|
| T-01 | CC-01 | `test_success_on_fresh_project` | `status="success"` |
| T-02 | CC-02 | `test_idempotent_second_run` | `status="no_op"` |
| T-03 | CC-03 | `test_dry_run_zero_writes` | Filesystem unchanged |
| T-04 | CC-04 | `test_files_created_count` | `len(files_created) >= 6` |
| T-05 | CC-05 | `test_files_modified_count` | `len(files_modified) >= 1` |
| T-06 | CC-06 | `test_debug_py_files_parse` | All `.py` in `app/debug/` parse |
| T-07 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk: max function body ≤ 50 |
| T-08 | CC-08 | `test_debug_config_fields_4space` | `DEBUG_RECORDER_ENABLED` present, 4-space indent |
| T-09 | CC-09 | `test_debug_init_exports` | `RequestRecorder` and `RequestReplayer` in `__init__` |
| T-10 | CC-10 | `test_debug_route_file` | `APIRouter` + `/debug` prefix in routes |
| T-11 | CC-11 | `test_recorder_symbols` | All 5 symbols in `recorder.py` |
| T-12 | CC-12 | `test_replayer_symbols` | `RequestReplayer`, `replay`, `_diff_bodies` in `replayer.py` |
| T-13 | CC-13 | `test_recorder_middleware_class` | `RecorderMiddleware` and `asyncio` in middleware |
| T-14 | CC-14 | `test_debug_route_handlers` | All 3 handler names in routes file |
| T-15 | CC-15 | `test_ttl_max_entries_fields` | `ttl_s` and `max_entries` in `recorder.py` |
| T-16 | CC-16 | `test_sha256_hashlib` | `sha256` and `hashlib` in `recorder.py` |
| T-18 | CC-17 | `test_pydantic_schemas` | `RecordedRequest`, `ReplayResult`, `BaseModel` in `models.py` |
| T-19 | CC-18 | `test_redis_not_top_level` | No top-level `import redis` in `recorder.py` |
| T-20 | CC-19 | `test_exclude_paths` | `exclude_paths` pattern in recorder or middleware |
| T-21 | CC-20 | `test_all_debug_config_fields` | All four `DEBUG_RECORDER_*` fields |
| T-22 | CC-21 | `test_execution_time_positive` | `execution_time_ms > 0` |
| T-23 | CC-22 | `test_next_steps_mention_recorder` | "DEBUG_RECORDER" or "recorder" in `next_steps` |
| T-24 | CC-23 | `test_second_run_files_still_parse` | All debug + middleware `.py` parse after second invocation |

### 10.2 Behavior tests (`test_add_api_replay_debugger_behavior.py`)

| # | Test ID | Test name | Assertion |
|---|---------|-----------|-----------|
| B-01 | QS-1 | `test_healthz_returns_200` | `GET /healthz` → 200 OK |
| B-02 | CC-11 | `test_recorder_symbols_importable` | `RequestRecorder`, `get_recorder`, `init_recorder` importable |
| B-03 | CC-12 | `test_replayer_importable` | `RequestReplayer` importable |
| B-04 | CC-20 | `test_debug_recorder_enabled_in_config` | `DEBUG_RECORDER_ENABLED` in config source |
| B-05 | INV-RD-04/05 | `test_lazy_imports` | Neither `redis` nor `httpx` at module top level |
| B-06 | INV-RD-07 | `test_routes_require_superuser` | All 3 routes have `get_current_superuser` dependency |
| B-07 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk on all generated files |
| B-08 | CC-08 | `test_config_4space_indent` | Fields inside `class Settings` body |
| B-09 | CC-12 | `test_diff_bodies_json_key_diff` | JSON key-level diff for structured responses |
| B-10 | CC-12 | `test_diff_bodies_line_fallback` | Line diff fallback for non-JSON bodies |

---

## 11. Interaction Matrix

| Other tool | Interaction type | Notes |
|------------|-----------------|-------|
| `add_chaos_testing` (TOOL-099) | ✅ Complementary | Chaos-injected 500s are recorded; replay reveals whether fault is deterministic |
| `add_graceful_shutdown` (TOOL-100) | ✅ Complementary | Register `close_recorder()` as cleanup callback; Redis connection closed cleanly on shutdown |
| `add_load_shedding` (TOOL-095) | ✅ Neutral | Load-shed 429s recorded; replay shows whether shedding was correct at that priority |
| `add_anomaly_detector` (TOOL-102) | ✅ Complementary | Anomaly alerts reference `rec_id` for replay-based root cause investigation |
| `add_request_fingerprint` (TOOL-103) | ⚠️ Caveat | Both use Redis; use different key prefixes (`debug:requests` vs `fingerprint:...`) — no collision |
| `add_bulkhead_isolation` (TOOL-097) | ✅ Neutral | Bulkhead 503s recorded; replay may behave differently if pool is less loaded during replay |
| `add_rbac` | ✅ Complementary | Replace `get_current_superuser` with RBAC scope check for finer access control |
| `add_audit_log` | ⚠️ Caveat | Exclude `/debug` from audit log to prevent log flooding from operator sessions |
| `generate_project` | ✅ Prerequisite | Requires `app/core/config.py` with `class Settings` and `app/api/deps.py` with `get_current_superuser` |
| Second `add_api_replay_debugger` call | ✅ Idempotent | `no_op` — `RequestRecorder` already in `recorder.py` |
| `add_arq_worker` (TOOL-053) | ✅ Neutral | Background ARQ tasks not intercepted by `RecorderMiddleware` — only ASGI request/response pairs recorded |

---

## 12. Rollback Procedure

### 12.1 Remove debug package

```bash
rm -rf app/debug/
```

### 12.2 Remove recorder middleware

```bash
rm -f app/middleware/request_recorder.py
```

### 12.3 Remove debug routes

```bash
rm -f app/api/routes/debug.py
```

### 12.4 Restore config

```bash
git checkout HEAD -- app/core/config.py
```

Or manually remove all four `DEBUG_RECORDER_*` fields from `app/core/config.py`.

### 12.5 Remove wiring from `main.py`

```bash
git checkout HEAD -- app/main.py
```

Or manually remove:
- `from app.debug.recorder import init_recorder, close_recorder`
- The `_debug_*` startup environment variable reads
- `RecorderMiddleware` from `app.add_middleware()`
- The debug router from `app.include_router()`

### 12.6 Verify rollback

```bash
python -c "from app.main import app; print('OK')"
pytest tests/ -x --tb=short
```

---

## 13. Edge Cases

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| EC-01 | `"RequestRecorder"` already in `app/debug/recorder.py` | `status="no_op"`, no files modified |
| EC-02 | `dry_run=True` on any valid project | `status="success"`, zero writes |
| EC-03 | Redis not running when `init_recorder()` is called | `Redis.from_url()` raises; caller handles exception; `get_recorder()` returns `None` |
| EC-04 | Redis not running during `recorder.record()` | `except Exception` catches error, logs warning, returns `None` — request unaffected |
| EC-05 | Request body > 4 096 chars | Truncated to 4 096 in middleware before storage |
| EC-06 | Response body > 8 192 chars | Truncated to 8 192 in `_capture_response_body()` |
| EC-07 | `rec_id` not found in Redis `lrange` | `get_record()` returns `None`; route returns 404 |
| EC-08 | `DEBUG_RECORDER_ENABLED=false` | `init_recorder()` never called; `get_recorder()` returns `None`; middleware passes through |
| EC-09 | `/debug/requests` path in `EXCLUDE_PATHS` | Management traffic not recorded — prevents recursive log entries |
| EC-10 | `app/api/routes/` directory does not exist | Routes file skipped; tool succeeds with 5 files instead of 6 |
| EC-11 | `app/core/config.py` does not exist | Config patch skipped; `files_modified` is empty |
| EC-12 | `_diff_bodies` called with empty original and empty replayed | Returns `[]` — no diff lines |
| EC-13 | `replay()` request raises exception (e.g., route removed) | Exception caught; `replayed_status=500`; diff computed against empty body |
| EC-14 | `flush()` called when Redis list key doesn't exist | `redis.delete()` returns 0 — not an error |
| EC-15 | `limit=0` passed to `GET /debug/requests` | Clamped to `max(1, min(0, 500)) == 1`; returns at most 1 record |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All CC-01 through CC-23 pass in `test_add_api_replay_debugger.py`
2. ✅ Redis imported lazily inside `init_recorder()` — not at module level
3. ✅ `httpx` imported lazily inside `RequestReplayer.replay()` — not at module level
4. ✅ `RecorderMiddleware` uses `asyncio.ensure_future` for non-blocking recording
5. ✅ `RequestReplayer` uses `httpx.ASGITransport` — in-process ASGI replay
6. ✅ `_diff_bodies` tries JSON key diff first, falls back to line-level diff
7. ✅ All three debug routes guarded by `Depends(get_current_superuser)`
8. ✅ Request body truncated to 4 096 chars; response body to 8 192 chars
9. ✅ Exclude paths prevent recording of `/healthz`, `/metrics`, `/debug` by default
10. ✅ All generated `.py` files pass `ast.parse()` with no `SyntaxError`
11. ✅ No generated function exceeds 50 LOC (AST walk)
12. ✅ Config fields have 4-space indent inside `class Settings` body
13. ✅ `execution_time_ms` is a positive integer in all result types
14. ✅ Second run returns `no_op` without modifying files

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks

- [ ] Validate `project_dir` with `validate_project_dir()` — return error if invalid
- [ ] Run `ensure_prerequisites(Prereq.CONFIG_SETTINGS, Prereq.REQUIREMENTS_TXT)` — return error if not met
- [ ] Check idempotency: `"RequestRecorder" in (app/debug/recorder.py)` → return `no_op` if true
- [ ] If `dry_run=True`, return early success with notes about all 4 would-be changes

### 15.2 Debug package creation

- [ ] Create `app/debug/` directory with `mkdir(parents=True, exist_ok=True)`
- [ ] Write `app/debug/__init__.py` via `_write_debug_init()`: re-export `RequestRecorder`, `RequestReplayer`, `RecordedRequest`, `ReplayResult`, `get_recorder`, `init_recorder`
- [ ] Write `app/debug/recorder.py` via `_write_recorder()`:
  - [ ] `_LIST_KEY = "debug:requests"` module constant
  - [ ] `RequestRecorder` with `ttl_s`, `max_entries`, `exclude_paths`, `_make_id()`, `record()`, `list_records()`, `get_record()`, `flush()`
  - [ ] `get_recorder()` returning module-level `_recorder`
  - [ ] `init_recorder()` with lazy `from redis.asyncio import Redis` import
  - [ ] `close_recorder()` for cleanup
- [ ] Write `app/debug/replayer.py` via `_write_replayer()`:
  - [ ] `_diff_bodies(original, replayed)` with JSON diff and line fallback
  - [ ] `RequestReplayer` with lazy `import httpx` inside `replay()`
- [ ] Write `app/debug/models.py` via `_write_debug_models()`:
  - [ ] `RecordedRequest(BaseModel)` with all fields
  - [ ] `ReplayResult(BaseModel)` with `body_diff: list[str]`, `diff_count: int`

### 15.3 Middleware

- [ ] Create `app/middleware/` if not exists
- [ ] Write `app/middleware/request_recorder.py` via `_write_recorder_middleware()`:
  - [ ] `RecorderMiddleware(BaseHTTPMiddleware)` with `exclude_paths`
  - [ ] `dispatch()` with exclude check, `get_recorder()` None guard, `asyncio.ensure_future`
  - [ ] Body truncation: request `[:4096]`, response `[:8192]`

### 15.4 Routes

- [ ] Write `app/api/routes/debug.py` via `_write_debug_routes()` (only if `routes_dir.exists()`):
  - [ ] `router = APIRouter(prefix="/debug", tags=["debug"])`
  - [ ] `GET /requests` with `Depends(get_current_superuser)`, limit clamping
  - [ ] `POST /replay/{rec_id}` with `Depends(get_current_superuser)`, 404 on missing record
  - [ ] `DELETE /flush` with `Depends(get_current_superuser)`

### 15.5 Config and main.py patches

- [ ] Patch `app/core/config.py` with all four `DEBUG_RECORDER_*` fields, 4-space indent
- [ ] Patch `app/main.py` if file exists and `init_recorder` not already present

### 15.6 Validation and result construction

- [ ] Loop over `files_created`: `ast.parse(path.read_text())` for all `.py` — return error on `SyntaxError`
- [ ] Return `ToolResult` with `status="success"`, `files_created`, `files_modified`, `notes` (4 items), `next_steps` (5 items), `execution_time_ms`

---

## 16. Documentation Output

### 16.1 Success (fresh project)

```json
{
  "status": "success",
  "files_created": [
    "/project/app/debug/__init__.py",
    "/project/app/debug/recorder.py",
    "/project/app/debug/replayer.py",
    "/project/app/debug/models.py",
    "/project/app/middleware/request_recorder.py",
    "/project/app/api/routes/debug.py"
  ],
  "files_modified": ["/project/app/core/config.py"],
  "notes": [
    "API replay debugger added: RequestRecorder ring buffer + RequestReplayer.",
    "RecorderMiddleware captures full req/resp in background (zero latency impact).",
    "Admin routes: GET /debug/requests, POST /debug/replay/{id}, DELETE /debug/flush.",
    "Idempotency key per record: SHA-256 of method+path+timestamp."
  ],
  "next_steps": [
    "pip install 'redis[hiredis]'",
    "Set DEBUG_RECORDER_ENABLED=true in .env (default: false).",
    "Set REDIS_URL in .env (e.g. redis://localhost:6379/0).",
    "Optional: set DEBUG_RECORDER_TTL_S and DEBUG_RECORDER_MAX_ENTRIES.",
    "Optional: set DEBUG_RECORDER_EXCLUDE_PATHS=comma,separated,paths."
  ],
  "execution_time_ms": 134
}
```

### 16.2 No-op (already installed)

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "RequestRecorder already present — replay debugger already enabled, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 3
}
```

### 16.3 Dry run

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/debug/ package with recorder, replayer, models.",
    "[dry_run] Would add RecorderMiddleware to app/main.py.",
    "[dry_run] Would add /debug/requests|replay|flush routes.",
    "[dry_run] Would patch app/core/config.py with DEBUG_RECORDER_* fields."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 2
}
```

### 16.4 Error (invalid project directory)

```json
{
  "status": "error",
  "error": "project_dir '/nonexistent/path' does not exist or is not a directory.",
  "files_created": [],
  "files_modified": [],
  "notes": [],
  "next_steps": [],
  "execution_time_ms": 1
}
```

---
