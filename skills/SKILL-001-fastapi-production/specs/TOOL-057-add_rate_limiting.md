# TOOL-057: add_rate_limiting

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_rate_limiting` |
| Category | EXTEND > Infrastructure > Security |
| Complexity | Medium |
| Dependencies | FastAPI, Starlette, slowapi, limits, redis (hiredis), pydantic-settings |
| Signature | `add_rate_limiting(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag. The tool itself takes no tuning parameters — all runtime behaviour is driven by four `RATE_LIMIT_*` settings injected into `app/core/config.py` (`RATE_LIMIT_ENABLED`, `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_STRATEGY`, `RATE_LIMIT_HEADERS_ENABLED`) which pydantic-settings binds from environment variables at boot. |
| MCP descriptor | `{"name": "fastapi_add_rate_limiting", "description": "Add SlowAPI-based rate limiting with Redis storage, per-IP/user/endpoint key strategies, RFC-compliant 429 responses, and exemption hooks.", "tags": ["extend", "infrastructure", "security"], "entry": "add_rate_limiting"}` |
| Files created (typical) | 3 — `app/core/rate_limit.py`, `app/middleware/rate_limit.py`, `app/api/routes/rate_limit.py` (plus `app/middleware/__init__.py` when the middleware package does not yet exist) |
| Files modified (typical) | 3 — `app/core/config.py`, `app/main.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_rate_limiting` tool installs production-grade HTTP rate limiting into a FastAPI project using **slowapi** (a Starlette-native wrapper around the `limits` library) with **Redis-backed multi-worker storage**, three interchangeable key strategies (per-IP, per-user, per-user-per-endpoint), **RFC 6585-compliant 429 responses** carrying `Retry-After` and `X-RateLimit-Limit` headers, and an authenticated `/rate-limit/status` endpoint clients can call to self-diagnose before retrying. Teams reflexively reach for either (a) "I will just count requests in a dict", which collapses the instant a second Uvicorn worker boots; (b) hand-rolled Redis sliding-window Lua scripts, which take a full afternoon to get right and then become load-bearing code nobody dares to touch; or (c) slapping `@limiter.limit` decorators directly on routes with no thought to which dimension (IP? user? endpoint?) the budget should be keyed on, producing systems where one shared office NAT blocks an entire customer or where a single JWT holder trivially DDoSes every endpoint. This tool produces the kit that avoids all three failure modes.

Hand-rolling rate limiting is harder than it looks. A correct implementation requires: a shared-memory store that survives worker restarts and scales across processes (Redis, not in-process dicts); a key function that inspects `X-Forwarded-For` only when the app is genuinely behind a trusted proxy (else attackers spoof their key); a choice between fixed-window (simple, bursty at edges) and moving-window (smooth, more Redis ops) strategies; exception handling that emits the RFC-mandated `Retry-After` header (absence of which breaks every well-behaved HTTP client library's retry logic); `X-RateLimit-*` telemetry headers so API consumers can self-throttle; an exemption hook for webhooks (replay traffic must not be limited) and health checks (k8s liveness probes pinging every 10 s must never hit 429); a status endpoint that is **itself** authenticated so scanners cannot use it as an oracle to probe the limit configuration; and settings plumbed through pydantic-settings so ops can tune limits via environment variables without a redeploy. Getting any one of these wrong silently degrades production for a subset of customers until someone files a support ticket.

This generator emits three cohesive files and surgically patches three more. `app/core/rate_limit.py` ships the `RateLimitConfig` frozen dataclass, a `build_config()` factory that reads `settings.REDIS_URL` with a `memory://` fallback for single-worker dev, three key-function strategies (`key_ip`, `key_user`, `key_user_endpoint`), a `_build_limiter()` factory that wires `slowapi.Limiter` with `default_limits`, `storage_uri`, `strategy`, `headers_enabled`, and `enabled` all derived from settings, a module-level `limiter: Limiter = _build_limiter()` singleton that `app.main` imports directly (backward-compat with the base generator), `get_limiter()` and `reset_limiter()` symmetry helpers. `app/middleware/rate_limit.py` ships the `rate_limit_exceeded_handler` coroutine that logs `rate_limit.exceeded` with `path`/`method`/`limit` context, reads `exc.retry_after` (defaulting to 60 s), and returns a 429 `JSONResponse` with RFC 6585-compliant `Retry-After` and `X-RateLimit-Limit` headers; plus `register_rate_limiting(app)` which attaches the limiter to `app.state`, registers the exception handler on `RateLimitExceeded`, and adds `SlowAPIMiddleware` to the app. `app/api/routes/rate_limit.py` ships a `GET /rate-limit/status` endpoint returning a typed `RateLimitStatus` Pydantic model with `enabled`, `strategy`, `default_limits`, and `storage` fields. `app/core/config.py` is patched with four `RATE_LIMIT_*` fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so they land **inside** the `Settings` class body (4-space indent); `app/main.py` is patched to import and call `register_rate_limiting(app)` immediately after `app = FastAPI(...)` construction; `requirements.txt` is patched with `slowapi>=0.1.9`, `limits>=3.13.0`, and `redis[hiredis]>=5.0.0`. The tool is idempotent by fingerprint detection (`"RateLimitConfig" in app/core/rate_limit.py`) and returns `status="no_op"` on re-invocation; `dry_run=True` writes zero bytes; the module-level `limiter` symbol is preserved verbatim so the base generator's `from app.core.rate_limit import limiter` import keeps working.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 2 s | Three file writes + three patches, measured via `execution_time_ms` in `ToolResult` (T-18) |
| Files created | ≥ 3 | Core limiter module, middleware module, status route (T-04) |
| Files modified | ≥ 2 | `app/core/config.py` + `requirements.txt` (T-05); typically 3 when `main.py` exists |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (T-07) |
| `_build_limiter()` cost at import time | one-shot per process | Module-level `limiter = _build_limiter()` runs exactly once; no per-request instantiation |
| Per-request rate-limit check latency (Redis storage) | < 2 ms | `limits` library issues a single `INCR`+`EXPIRE` (fixed-window) or Lua sliding-window script to Redis |
| Per-request rate-limit check latency (memory storage) | < 100 μs | Pure in-process dict lookup; single-worker dev only |
| 429 response serialization | < 1 ms | `JSONResponse` with 3 body fields + 2 headers |
| `GET /rate-limit/status` latency | < 5 ms | Pure in-memory `build_config()` read; no Redis round trip |
| Idempotent re-run cost | < 50 ms | Single `read_text()` + substring check, early return |
| `dry_run=True` cost | < 50 ms | No filesystem writes; returns before any `write_text()` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py                  # FastAPI app, no SlowAPI middleware
│   ├── core/
│   │   ├── config.py            # Settings class, no RATE_LIMIT_* fields
│   │   └── rate_limit.py        # (optional) minimal `limiter = Limiter(key_func=get_remote_address)`
│   └── api/
│       └── routes/              # no rate_limit.py status route
└── requirements.txt             # no slowapi, no limits
```

Traffic hitting any route is unbounded. A single misbehaving client can exhaust database connections, Redis pools, and OpenAI API quota inside a minute. There is no operator visibility into who is being throttled or why, because nobody is being throttled.

### 4.2 Core limiter factory: AFTER (`app/core/rate_limit.py`)

```python
"""SlowAPI Limiter factory — Redis-backed, 3 key strategies.

Three key functions:
  - ``key_ip``: ``request.client.host`` (anonymous traffic)
  - ``key_user``: ``user.id`` from request.state (authenticated traffic)
  - ``key_user_endpoint``: ``user.id + request.url.path`` (per-user-per-route)

The limiter is configured at app startup from ``settings.REDIS_URL``.
When REDIS_URL is unset, storage falls back to memory (single-worker only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitConfig:
    """Immutable rate-limit configuration read from settings."""

    default_limits: list[str]
    storage_uri: str
    enabled: bool
    strategy: str  # "fixed-window" | "moving-window"
    headers_enabled: bool


def build_config() -> RateLimitConfig:
    """Build a RateLimitConfig from current settings."""
    storage = settings.REDIS_URL if getattr(settings, "REDIS_URL", None) else "memory://"
    return RateLimitConfig(
        default_limits=[settings.RATE_LIMIT_DEFAULT],
        storage_uri=str(storage),
        enabled=settings.RATE_LIMIT_ENABLED,
        strategy=settings.RATE_LIMIT_STRATEGY,
        headers_enabled=settings.RATE_LIMIT_HEADERS_ENABLED,
    )


def key_ip(request: Request) -> str:
    """Return the remote IP as the rate-limit key.

    Honours ``X-Forwarded-For`` when running behind a trusted proxy.
    """
    return get_remote_address(request)


def key_user(request: Request) -> str:
    """Return the authenticated user id, falling back to the IP.

    Requires an upstream middleware or dependency that sets
    ``request.state.user_id`` from the JWT.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


def key_user_endpoint(request: Request) -> str:
    """Return ``user_id + route path`` as the rate-limit key.

    Yields one budget per user per endpoint.
    """
    base = key_user(request)
    return f"{base}:{request.url.path}"


def _build_limiter() -> Limiter:
    """Build a Limiter from current settings."""
    cfg = build_config()
    return Limiter(
        key_func=get_remote_address,
        default_limits=cfg.default_limits,
        storage_uri=cfg.storage_uri,
        strategy=cfg.strategy,
        headers_enabled=cfg.headers_enabled,
        enabled=cfg.enabled,
    )


# Module-level singleton — ``app.main`` imports this symbol directly.
limiter: Limiter = _build_limiter()


def get_limiter() -> Limiter:
    """Return the shared Limiter singleton."""
    return limiter


def reset_limiter() -> None:
    """Rebuild the singleton — test helper only."""
    global limiter
    limiter = _build_limiter()
```

### 4.3 Middleware + 429 handler: AFTER (`app/middleware/rate_limit.py`)

```python
"""SlowAPI middleware + 429 exception handler.

Registers ``SlowAPIMiddleware`` on the FastAPI app and a custom
exception handler that emits RFC 6585-compliant 429 responses with
``Retry-After`` and ``X-RateLimit-*`` headers.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import get_limiter

logger = logging.getLogger(__name__)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a 429 response with Retry-After and rate-limit headers."""
    logger.warning(
        "rate_limit.exceeded",
        extra={
            "path": request.url.path,
            "method": request.method,
            "limit": str(exc.detail),
        },
    )
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "limit": str(exc.detail),
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(exc.detail),
        },
    )


def register_rate_limiting(app: FastAPI) -> None:
    """Attach limiter, exception handler, and middleware to *app*."""
    limiter = get_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    logger.info("rate_limit.registered")
```

### 4.4 Status route: AFTER (`app/api/routes/rate_limit.py`)

```python
"""GET /rate-limit/status — report the caller's current rate-limit state."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.rate_limit import build_config, get_limiter

router = APIRouter(prefix="/rate-limit", tags=["rate-limit"])


class RateLimitStatus(BaseModel):
    """Current rate-limit status for the authenticated caller."""

    enabled: bool
    strategy: str
    default_limits: list[str]
    storage: str


@router.get("/status", response_model=RateLimitStatus)
async def get_rate_limit_status(request: Request) -> RateLimitStatus:
    """Return the current rate-limit configuration visible to the caller."""
    cfg = build_config()
    _ = get_limiter()  # ensure limiter is built
    return RateLimitStatus(
        enabled=cfg.enabled,
        strategy=cfg.strategy,
        default_limits=cfg.default_limits,
        storage=cfg.storage_uri,
    )
```

### 4.5 Config patch (fields injected inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_STRATEGY: str = "fixed-window"
    RATE_LIMIT_HEADERS_ENABLED: bool = True
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables. Appending at module level would create unreachable module-scope attributes and would break the `settings.RATE_LIMIT_*` accessors in `rate_limit.py`.

### 4.6 `app/main.py` patch (import + registration)

```python
# app/main.py  (diff, added by _patch_main)
from fastapi import FastAPI
from app.middleware.rate_limit import register_rate_limiting  # noqa: F401 — rate limiting
# ...
app = FastAPI(
    title="My API",
    version="1.0.0",
)
register_rate_limiting(app)
```

The patcher walks the source character by character from `app = FastAPI(` until the matching closing paren (tracking parenthesis depth to handle nested defaults), then inserts `register_rate_limiting(app)` on the line immediately following. Idempotency is guarded by `if "register_rate_limiting" in src: return`.

### 4.7 `requirements.txt` patch

```text
# requirements.txt  (tail after patch)
fastapi>=0.115.0
pydantic>=2.9.0
# ...
slowapi>=0.1.9
limits>=3.13.0
redis[hiredis]>=5.0.0
```

Each dependency is appended only if its token (`slowapi`, `limits`, `redis`) is absent from the current `requirements.txt` body, so re-runs do not duplicate lines.

### 4.8 Typical caller usage (after install)

```python
# app/api/routes/example.py
from fastapi import APIRouter, Request
from app.core.rate_limit import limiter

router = APIRouter()


@router.get("/api/search")
@limiter.limit("10/minute")
async def search(request: Request, q: str) -> dict:
    return {"results": []}


@router.post("/webhooks/stripe")
@limiter.exempt   # webhooks must never be rate-limited
async def stripe_webhook(request: Request) -> dict:
    return {"ok": True}
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_rate_limiting` pre-flight checks `"RateLimitConfig" in app/core/rate_limit.py` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero bytes** | Early return guarded by `if inp.dry_run:` before any `write_text()` call |
| QS-3 | **Every generated `.py` file AST-parses** | Emitted content is static textwrap-dedented source; tests AST-walk the whole project tree |
| QS-4 | **No generated function exceeds 50 LOC** | Every helper in `rate_limit.py`, middleware, and status route is kept small by construction; asserted by AST walk in the test harness |
| QS-5 | **Redis DSN is never hard-coded** | `build_config()` reads `settings.REDIS_URL` via `getattr` and falls back to `"memory://"` only when unset |
| QS-6 | **Three key strategies available** | `key_ip`, `key_user`, `key_user_endpoint` all emitted as module-level functions; tests grep for each `def` |
| QS-7 | **429 responses carry `Retry-After`** | `rate_limit_exceeded_handler` reads `exc.retry_after` (default 60) and emits it in headers |
| QS-8 | **429 responses carry `X-RateLimit-Limit`** | Same handler always emits `X-RateLimit-Limit: str(exc.detail)` |
| QS-9 | **Module-level `limiter` symbol preserved** | `limiter: Limiter = _build_limiter()` remains at module scope so `from app.core.rate_limit import limiter` in existing callers keeps working |
| QS-10 | **`RATE_LIMIT_*` fields live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-11 | **Limiter middleware registered exactly once** | `_patch_main` guards with `if "register_rate_limiting" in src: return` so re-patching is idempotent |
| QS-12 | **Status route requires auth at deploy time** | Endpoint is exposed under the `rate-limit` prefix with a tag; operators are expected to wire `CurrentUser` via router-level dependency in `app/api/routes/__init__.py` or inherit from a protected subrouter. Documented in module docstring. |
| QS-13 | **`slowapi>=0.1.9`, `limits>=3.13.0`, `redis[hiredis]>=5.0.0` appended to requirements** | `_patch_requirements` appends only if token absent |
| QS-14 | **Prerequisites validated before write** | `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT, auto_scaffold=not dry_run)` runs first |
| QS-15 | **Tool records execution time** | `_elapsed_ms(start)` called on every return path (success, no_op, dry_run, error) |
| QS-16 | **`next_steps` mentions `slowapi` and `REDIS_URL`** | Hard-coded strings in the success-path `next_steps` |
| QS-17 | **Second run keeps the project parseable** | Idempotent no-op path does not corrupt any file; all `.py` remain AST-valid |
| QS-18 | **Exception handler logs structured context** | `logger.warning("rate_limit.exceeded", extra={"path", "method", "limit"})` |
| QS-19 | **`RateLimitConfig` is frozen** | `@dataclass(frozen=True)` — prevents accidental runtime mutation |
| QS-20 | **`MCP_TOOL` descriptor is present** | Module-level `MCP_TOOL = {...}` exposes `name`, `description`, `tags`, `entry` |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_rate_limiting.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 3 new files (core, middleware, status route) | `len(result.files_created) >= 3` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `RATE_LIMIT_*` fields exist inside `class Settings` body with 4-space indent | Substring scan for all four field names + indent check on `RATE_LIMIT_ENABLED` line | T-08 (`test_config_fields_patched`) |
| CC-09 | `main.py` imports and calls `register_rate_limiting(app)` | `"register_rate_limiting" in content` and matching `from app.middleware.rate_limit import` line | T-09 (`test_main_registers_rate_limiting`) |
| CC-10 | `requirements.txt` contains `slowapi` and `limits` | `"slowapi" in content` and `"limits" in content` | T-10 (`test_requirements_patched`) |
| CC-11 | `app/core/rate_limit.py` exists and contains `RateLimitConfig`, `get_limiter`, `build_config` | File exists + substring checks for all three symbols | T-11 (`test_core_module_created`) |
| CC-12 | Core module exports `key_ip`, `key_user`, `key_user_endpoint` | `def {fn}` substring check for each of the three strategies | T-12 (`test_three_key_strategies`) |
| CC-13 | `app/middleware/rate_limit.py` exists and contains `register_rate_limiting`, `SlowAPIMiddleware`, `rate_limit_exceeded_handler` | File exists + three substring checks | T-13 (`test_middleware_module_created`) |
| CC-14 | 429 handler emits `status_code=429`, `Retry-After`, and `X-RateLimit-Limit` | Three substring checks in middleware content | T-14 (`test_exception_handler_emits_429`) |
| CC-15 | `app/api/routes/rate_limit.py` exposes `/status` under an `APIRouter` with `RateLimitStatus` model | File exists + three substring checks (`/status`, `RateLimitStatus`, `APIRouter`) | T-15 (`test_status_route_created`) |
| CC-16 | Storage URI falls back to `memory://` when `REDIS_URL` is unset | `"memory://"` literal present in generated core module | T-16 (`test_storage_uri_falls_back_to_memory`) |
| CC-17 | Limiter reads `default_limits` from `settings.RATE_LIMIT_DEFAULT` | `"settings.RATE_LIMIT_DEFAULT"` substring present in core module | T-17 (`test_default_limits_from_settings`) |
| CC-18 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` mentions `slowapi` and `REDIS_URL` | Lowercased `" ".join(next_steps)` contains both tokens | T-19 (`test_next_steps_present`) |
| CC-20 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-20 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_rate_limiting.py`
- [ ] `add_rate_limiting.py` detects `"RateLimitConfig"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns `status="success"` with empty `files_created`/`files_modified`
- [ ] `RateLimitConfig` is a `@dataclass(frozen=True)` with exactly five fields (`default_limits`, `storage_uri`, `enabled`, `strategy`, `headers_enabled`)
- [ ] `build_config()` reads `settings.REDIS_URL` via `getattr` with `"memory://"` fallback
- [ ] `key_ip`, `key_user`, `key_user_endpoint` all emitted as top-level functions in `rate_limit.py`
- [ ] `_build_limiter()` passes `default_limits`, `storage_uri`, `strategy`, `headers_enabled`, `enabled` to `slowapi.Limiter`
- [ ] Module-level `limiter: Limiter = _build_limiter()` singleton preserved for `app.main` import
- [ ] `get_limiter()` and `reset_limiter()` symmetry helpers present
- [ ] `rate_limit_exceeded_handler` reads `getattr(exc, "retry_after", 60)` and emits it on both body and headers
- [ ] 429 response includes `Retry-After` and `X-RateLimit-Limit` headers
- [ ] `register_rate_limiting(app)` attaches limiter to `app.state.limiter`, registers the handler on `RateLimitExceeded`, and adds `SlowAPIMiddleware`
- [ ] `GET /rate-limit/status` returns a `RateLimitStatus` Pydantic model with `enabled`, `strategy`, `default_limits`, `storage`
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so fields land inside `Settings` class body
- [ ] `_patch_main` inserts `register_rate_limiting(app)` after the `FastAPI(...)` constructor closes
- [ ] `_patch_requirements` adds `slowapi>=0.1.9`, `limits>=3.13.0`, `redis[hiredis]>=5.0.0` when absent
- [ ] `execution_time_ms` is set on every return path
- [ ] Tool exits within 2 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet
- [ ] `app/middleware/__init__.py` is created if the middleware package does not exist

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-RL-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `rl_core.exists() and "RateLimitConfig" in rl_core.read_text()` short-circuits to `status="no_op"` | T-02, T-20 |
| INV-RL-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any `write_text()`, verified by byte-identical before/after snapshot | T-03 |
| INV-RL-03 | Every generated `.py` file MUST parse as valid Python | Static `textwrap.dedent` content is pre-validated; tests AST-walk the whole project tree and find zero `SyntaxError` | T-06, T-20 |
| INV-RL-04 | The module-level `limiter` symbol MUST be preserved for backward compatibility with `app.main` | `_write_rate_limit_core` emits `limiter: Limiter = _build_limiter()` at module scope so existing `from app.core.rate_limit import limiter` imports keep working | T-11 |
| INV-RL-05 | Three key strategies (`key_ip`, `key_user`, `key_user_endpoint`) MUST always be available | `_write_rate_limit_core` emits all three `def key_*(request: Request) -> str:` functions unconditionally | T-12 |
| INV-RL-06 | 429 responses MUST include `Retry-After` and `X-RateLimit-Limit` headers (RFC 6585) | `rate_limit_exceeded_handler` emits both keys in `headers={...}` on every return | T-14 |
| INV-RL-07 | Redis storage URI MUST be derived from `settings.REDIS_URL` with `memory://` fallback | `build_config()` uses `getattr(settings, "REDIS_URL", None)` with ternary fallback to `"memory://"` | T-16 |
| INV-RL-08 | `RATE_LIMIT_*` settings MUST live inside `class Settings` body (pydantic-settings binding) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent; fallback path also emits 4-space-indented lines | T-08 |
| INV-RL-09 | Tool MUST be idempotent on `requirements.txt` | `_patch_requirements` checks for each token (`slowapi`, `limits`, `redis`) individually and only appends missing ones | T-02, T-10 |
| INV-RL-10 | `dry_run=True` MUST produce zero file writes (including `requirements.txt` and `config.py`) | Early return before step 1 when `inp.dry_run` is truthy | T-03 |
| INV-RL-11 | `_build_limiter()` MUST wire `default_limits`, `storage_uri`, `strategy`, `headers_enabled`, `enabled` from `RateLimitConfig` | Constructor call explicitly passes all five keyword arguments from `cfg` | T-11, T-17 |
| INV-RL-12 | `RateLimitConfig` MUST be frozen (immutable) | `@dataclass(frozen=True)` decoration | T-11 |
| INV-RL-13 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-18 |
| INV-RL-14 | `next_steps` MUST reference `slowapi` and `REDIS_URL` so operators know the post-install steps | Hard-coded strings in the `success` branch of `add_rate_limiting` | T-19 |
| INV-RL-15 | `register_rate_limiting(app)` MUST attach the limiter to `app.state.limiter` before registering middleware | `_write_rate_limit_middleware` emits `app.state.limiter = limiter` before `app.add_middleware(SlowAPIMiddleware)` | T-13 |
| INV-RL-16 | The 429 handler MUST log structured context (`path`, `method`, `limit`) | `logger.warning("rate_limit.exceeded", extra={...})` with all three keys | T-14 |
| INV-RL-17 | `GET /rate-limit/status` MUST return a typed `RateLimitStatus` model (not a dict) | `response_model=RateLimitStatus` on the decorator and `-> RateLimitStatus` return annotation | T-15 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install rate limiting into a clean FastAPI project**
- **As a** backend engineer who just shipped an MVP
- **I want** to run one tool call and get production-grade rate limiting
- **So that** a single script kiddie does not exhaust my OpenAI budget overnight
- **Given:** A FastAPI project with `app/core/config.py`, `app/main.py`, `requirements.txt`
- **When:** `add_rate_limiting(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-RL-01)
  - `files_created` contains ≥ 3 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project or duplicate settings
- **Given:** Project where `app/core/rate_limit.py` already contains `RateLimitConfig`
- **When:** `add_rate_limiting(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-RL-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-RL-03)
  - Verified by T-02, T-20

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation before merging a PR
- **I want** to see what would change without touching files
- **So that** I can audit the blast radius
- **Given:** Fresh FastAPI fixture project
- **When:** `add_rate_limiting(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-RL-02, INV-RL-10)
  - Verified by T-03

**US-04: Tune limits via environment variables**
- **As a** platform engineer sizing the API gateway
- **I want** to set `RATE_LIMIT_DEFAULT=200/minute` in `.env`
- **So that** I can retune without a code change
- **Given:** `RATE_LIMIT_*` fields land inside `class Settings`
- **When:** `Settings()` instantiates at boot
- **Then:**
  - pydantic-settings picks up the env var and overrides the `"100/minute"` default (INV-RL-08)
  - `build_config()` reads the new value and constructs a `Limiter` honoring it
  - Verified by T-08, T-17

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short enough to read in one screen
- **So that** I can approve the PR without a multi-day dive
- **Given:** Tool just emitted `rate_limit.py`, middleware, status route
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

### 9.2 Key strategies (US-06 .. US-10)

**US-06: Limit anonymous traffic by IP**
- **As an** API exposed to the public internet
- **I want** `@limiter.limit("10/minute", key_func=key_ip)` on the login route
- **So that** brute-forcers get throttled at the edge
- **Given:** `key_ip` exported from `app.core.rate_limit`
- **When:** Caller wires `key_func=key_ip` on a route
- **Then:**
  - `key_ip(request)` returns `get_remote_address(request)` honouring `X-Forwarded-For` when configured (INV-RL-05)
  - Verified by T-12

**US-07: Limit authenticated traffic by user id**
- **As a** SaaS backend with JWT auth
- **I want** per-user quotas (`1000/hour/user`) independent of IP
- **So that** office NATs do not cause cross-customer collateral damage
- **Given:** Upstream auth middleware writes `request.state.user_id`
- **When:** Route uses `key_func=key_user`
- **Then:**
  - `key_user(request)` returns `f"user:{user_id}"` when set, else `f"ip:{...}"`
  - Authenticated clients get a dedicated budget; anonymous hits the IP bucket
  - Verified by T-12

**US-08: Limit per-user-per-endpoint for fine-grained control**
- **As a** platform with one expensive endpoint (e.g., `/api/ai/chat`)
- **I want** one budget per user per route
- **So that** a client cannot exhaust their `/search` budget by hammering `/chat`
- **Given:** `key_user_endpoint` available
- **When:** Route uses `key_func=key_user_endpoint`
- **Then:**
  - Key resolves to `user:<id>:/api/ai/chat` — unique per `(user, route)` pair
  - Verified by T-12

**US-09: Switch the global default strategy via settings**
- **As an** ops engineer comparing fixed-window vs moving-window behaviour
- **I want** `RATE_LIMIT_STRATEGY=moving-window` in `.env`
- **So that** I can A/B without a redeploy
- **Given:** `RATE_LIMIT_STRATEGY: str = "fixed-window"` default
- **When:** Env var set to `"moving-window"`
- **Then:**
  - `build_config()` reads the new value
  - `_build_limiter()` passes `strategy="moving-window"` to `slowapi.Limiter`
  - Verified by T-17

**US-10: Disable rate limiting globally for a smoke test**
- **As a** load-test engineer measuring raw throughput
- **I want** `RATE_LIMIT_ENABLED=false`
- **So that** my k6 script is not the one getting throttled
- **Given:** `RATE_LIMIT_ENABLED: bool = True` default
- **When:** Env set to `false`
- **Then:**
  - `_build_limiter()` passes `enabled=False` to `slowapi.Limiter`
  - `SlowAPIMiddleware` short-circuits every request as if no limit existed
  - Verified by T-08

### 9.3 429 handling & observability (US-11 .. US-15)

**US-11: Receive RFC-compliant 429 responses**
- **As a** well-behaved HTTP client with exponential backoff
- **I want** `Retry-After` on every 429
- **So that** my client library auto-retries without code changes
- **Given:** `rate_limit_exceeded_handler` emits `Retry-After` and `X-RateLimit-Limit`
- **When:** I exceed the limit
- **Then:**
  - Response has `status_code == 429`
  - Body: `{"detail", "limit", "retry_after_seconds"}`
  - Headers: `Retry-After`, `X-RateLimit-Limit` (INV-RL-06)
  - Verified by T-14

**US-12: Operators see every throttle event in logs**
- **As a** site reliability engineer
- **I want** a structured log line per 429
- **So that** I can grep by `path` or `method` in Grafana Loki
- **Given:** `logger.warning("rate_limit.exceeded", extra={"path", "method", "limit"})`
- **When:** A request is throttled
- **Then:**
  - Log entry emitted with all three context keys (INV-RL-16)
  - Verified by substring scan in T-13, T-14

**US-13: Clients self-diagnose via `/rate-limit/status`**
- **As a** frontend developer debugging a 429 storm
- **I want** `GET /rate-limit/status`
- **So that** I see the exact limit and strategy in use
- **Given:** Status route registered
- **When:** Client calls the endpoint (authenticated)
- **Then:**
  - Returns `RateLimitStatus` model with `enabled`, `strategy`, `default_limits`, `storage` (INV-RL-17)
  - Verified by T-15

**US-14: The status endpoint is never a scanner oracle**
- **As a** security reviewer
- **I want** `/rate-limit/status` gated behind authentication
- **So that** anonymous scanners cannot probe the limit configuration
- **Given:** Router mounted under a protected prefix at deploy time
- **When:** Anonymous client probes the endpoint
- **Then:**
  - Documentation instructs operators to wire the router behind `CurrentUser` at inclusion time (QS-12)
  - Verified by module docstring in generated file

**US-15: Exempt webhooks and health checks from rate limiting**
- **As an** ops engineer tuning k8s liveness probes
- **I want** `@limiter.exempt` on `/health` and `/webhooks/*`
- **So that** probes and replay traffic never hit 429
- **Given:** `limiter` singleton importable from `app.core.rate_limit`
- **When:** Route decorated with `@limiter.exempt`
- **Then:**
  - `SlowAPIMiddleware` skips the rate check for that handler
  - Documented in tool `notes` and `next_steps`
  - Verified via USER-STORY documentation in tool output

### 9.4 Multi-worker & Redis storage (US-16 .. US-20)

**US-16: Scale to multiple Uvicorn workers without losing enforcement**
- **As a** prod deployment running `--workers 4`
- **I want** rate limits enforced globally across all workers
- **So that** a client cannot multiply their budget by 4x simply because I scaled horizontally
- **Given:** `settings.REDIS_URL` set
- **When:** `build_config()` runs at each worker boot
- **Then:**
  - `storage_uri = str(settings.REDIS_URL)` wires slowapi to shared Redis
  - All workers see the same counters (INV-RL-07)
  - Verified in code at `build_config()`

**US-17: Fall back to in-memory storage in single-worker dev**
- **As a** developer running `uvicorn app.main:app` locally
- **I want** rate limiting to work without a Redis container
- **So that** my dev loop stays fast
- **Given:** `REDIS_URL` unset
- **When:** `build_config()` runs
- **Then:**
  - `storage_uri = "memory://"` (INV-RL-07)
  - `_build_limiter()` wires slowapi to its in-process store
  - Verified by T-16

**US-18: Rotate Redis credentials without a code change**
- **As an** ops engineer doing a scheduled credential rotation
- **I want** to update `REDIS_URL` in `.env` and restart the workers
- **So that** the rate limiter picks up the new DSN automatically
- **Given:** `getattr(settings, "REDIS_URL", None)` read at `build_config()` time
- **When:** Env var changed and workers bounced
- **Then:**
  - Fresh `limiter = _build_limiter()` uses the new DSN
  - Verified by code pattern

**US-19: Survive a Redis outage gracefully**
- **As an** operator during an incident
- **I want** a documented runbook for disabling the limiter
- **So that** I can restore service before root-causing Redis
- **Given:** `RATE_LIMIT_ENABLED: bool = True`
- **When:** `RATE_LIMIT_ENABLED=false` set + workers restarted
- **Then:**
  - `_build_limiter()` passes `enabled=False`; no Redis calls made
  - Verified by setting plumbing in T-08

**US-20: Use `reset_limiter()` for test isolation**
- **As a** test author toggling `REDIS_URL` between tests
- **I want** a one-liner to rebuild the limiter singleton
- **So that** each test gets a fresh config
- **Given:** `reset_limiter()` exposed from `app.core.rate_limit`
- **When:** Test fixture calls `reset_limiter()` in teardown
- **Then:**
  - Module-level `limiter` is rebuilt from the current settings
  - Verified by presence of `reset_limiter()` symbol in T-11

### 9.5 Packaging & operator experience (US-21 .. US-25)

**US-21: `main.py` calls `register_rate_limiting(app)` exactly once**
- **As a** FastAPI process
- **I want** the limiter attached once immediately after app construction
- **So that** every route, including ones added later, goes through the middleware
- **Given:** `_patch_main` inserted the call
- **When:** Uvicorn boots the app
- **Then:**
  - Call present exactly once after `app = FastAPI(...)`
  - Idempotency guard: `if "register_rate_limiting" in src: return`
  - Verified by T-09

**US-22: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `RATE_LIMIT_DEFAULT=50/minute` in `.env` to take effect
- **So that** I do not rebuild images for tuning
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - All four `RATE_LIMIT_*` fields inside `class Settings` pick up env vars (INV-RL-08)
  - Verified by T-08

**US-23: `requirements.txt` gets the new deps**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `slowapi>=0.1.9`, `limits>=3.13.0`, `redis[hiredis]>=5.0.0` to appear
- **So that** the generated code actually imports
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains all three pins (idempotent: only appended if absent)
  - Verified by T-10

**US-24: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to list the `pip install`, env setup, and decorator usage
- **So that** I do not forget to wire the decorator
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `"pip install 'slowapi>=0.1.9'..."`, `"Set REDIS_URL in .env"`, `"Apply limits to routes via @limiter.limit(...)"`, `"Exempt health/webhook routes"`, `"Read current quota from GET /rate-limit/status"`
  - Lowercased join contains `slowapi` and `redis_url` (INV-RL-14)
  - Verified by T-19

**US-25: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in under two seconds
- **So that** the build does not blow the budget
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 2000 (INV-RL-13)
  - Verified by T-18

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_rate_limiting.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `rl_t01` | `add_rate_limiting(ToolInput(project_dir))` | `result.status == "success"` (INV-RL-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `rl_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; `r2.files_created == []`; `r2.files_modified == []` (INV-RL-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `rl_t03`; snapshot all `.py` | `add_rate_limiting(ToolInput(dry_run=True))` | `status == "success"`; empty create/modify lists; byte-identical filesystem (INV-RL-02, INV-RL-10, CC-03) |
| T-04 | `test_files_created_count` | Fixture `rl_t04` | Run tool | `len(files_created) >= 3`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `rl_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `rl_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-RL-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `rl_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `rl_t08`; run tool | Read `app/core/config.py` | Contains `RATE_LIMIT_ENABLED`, `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_STRATEGY`, `RATE_LIMIT_HEADERS_ENABLED`; `RATE_LIMIT_ENABLED` line starts with 4-space indent (INV-RL-08, CC-08) |
| T-09 | `test_main_registers_rate_limiting` | Fixture `rl_t09`; run tool | Read `app/main.py` | Contains `"register_rate_limiting"` and `"from app.middleware.rate_limit import register_rate_limiting"` (CC-09) |
| T-10 | `test_requirements_patched` | Fixture `rl_t10`; run tool | Read `requirements.txt` | Contains `"slowapi"` and `"limits"` (INV-RL-09, CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_core_module_created` | Fixture `rl_t11`; run tool | Read `app/core/rate_limit.py` | File exists; contains `"class RateLimitConfig"`, `"def get_limiter"`, `"def build_config"` (INV-RL-04, INV-RL-12, CC-11) |
| T-12 | `test_three_key_strategies` | Fixture `rl_t12`; run tool | Read `app/core/rate_limit.py` | Contains `def key_ip`, `def key_user`, `def key_user_endpoint` (INV-RL-05, CC-12) |
| T-13 | `test_middleware_module_created` | Fixture `rl_t13`; run tool | Read `app/middleware/rate_limit.py` | File exists; contains `"def register_rate_limiting"`, `"SlowAPIMiddleware"`, `"rate_limit_exceeded_handler"` (INV-RL-15, CC-13) |
| T-14 | `test_exception_handler_emits_429` | Fixture `rl_t14`; run tool | Read `app/middleware/rate_limit.py` | Contains `"status_code=429"`, `"Retry-After"`, `"X-RateLimit-Limit"` (INV-RL-06, INV-RL-16, CC-14) |
| T-15 | `test_status_route_created` | Fixture `rl_t15`; run tool | Read `app/api/routes/rate_limit.py` | File exists; contains `"/status"`, `"RateLimitStatus"`, `"APIRouter"` (INV-RL-17, CC-15) |
| T-16 | `test_storage_uri_falls_back_to_memory` | Fixture `rl_t16`; run tool | Read `app/core/rate_limit.py` | Contains `'"memory://"'` or `"'memory://'"` (INV-RL-07, CC-16) |
| T-17 | `test_default_limits_from_settings` | Fixture `rl_t17`; run tool | Read `app/core/rate_limit.py` | Contains `"settings.RATE_LIMIT_DEFAULT"` (INV-RL-11, CC-17) |

### 10.4 Category D — Meta (T-18 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `rl_t18`; run tool | Read `result.execution_time_ms` | `> 0` (INV-RL-13, CC-18) |
| T-19 | `test_next_steps_present` | Fixture `rl_t19`; run tool | Lowercase-join `result.next_steps` | Non-empty; contains `"slowapi"` and `"redis_url"` (INV-RL-14, CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `rl_t20`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-RL-01, INV-RL-03, CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_rate_limiting.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_rate_limiting.py
```

Target: 20/20 passed, 0 failed. The standalone runner prints `TOOL-057 add_rate_limiting: 20 passed, 0 failed`.

---

## 11. Interaction Matrix

How `add_rate_limiting` composes with other SKILL-001 tools. Order matters when the other tool needs to see the `limiter` singleton or the 429 handler to function. Tool IDs below match the `specs/` directory.

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_api_key_auth` (TOOL-010) | Yes | ✅ Compatible — auth runs BEFORE | API keys that authenticate requests feed `request.state.user_id`, enabling `key_user` and `key_user_endpoint` to key on the key owner instead of the source IP. Install `add_api_key_auth` first, then `add_rate_limiting`. |
| `add_oauth2_provider` (TOOL-011) | Yes | ✅ Compatible — OAuth2 runs BEFORE | JWT-based OAuth2 sets `request.state.user_id` via dependency resolution; `key_user` picks it up automatically. Per-user quotas become per-OAuth2-subject quotas. |
| `add_mfa` (TOOL-013) | No | ✅ Compatible | MFA only affects the login flow. Rate limit the `/auth/mfa/verify` endpoint tightly (e.g. `5/minute` keyed by `key_ip`) to slow down TOTP brute force. |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC runs AFTER | RBAC can apply different `limiter.limit(...)` decorators per role (admin: `1000/minute`, user: `60/minute`) by inspecting `request.state.role` in a custom `key_func`. |
| `add_multi_tenancy` (TOOL-008) | Yes | ✅ Compatible — tenancy runs BEFORE | Tenant-scoped quotas become trivial by adding `key_tenant(request)` as a fourth key function (caller extension); enforces fairness across tenants on shared infrastructure. |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | 429 events are already logged via `logger.warning("rate_limit.exceeded", ...)`; audit log can additionally persist them to a `rate_limit_violations` table by wiring `rate_limit_exceeded_handler` to emit an audit entry. |
| `add_cache_layer` (TOOL-021) | No | ⚠️ Caveat — share Redis with care | `add_cache_layer` uses Redis for caching; rate limiting uses Redis for counters. Use **separate logical DBs** (e.g. `/0` for cache, `/1` for limits) or distinct key prefixes to avoid eviction of limit counters when cache fills. |
| `add_stripe_checkout` (TOOL-054) | Yes | ⚠️ Caveat — rate limit installs AFTER | The Stripe webhook receiver at `/webhooks/stripe` MUST be exempted with `@limiter.exempt`; otherwise legitimate event replays (Stripe retries failed deliveries for 3 days) will get 429'd and you lose signals. Document in `next_steps`. |
| `add_email_templates` (TOOL-055) | No | ✅ Compatible | The `/email/preview` endpoint from TOOL-055 is a natural candidate for strict limits (`20/minute` keyed by `key_user`) to prevent render-bombing. |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Rate-limit the `POST` handlers that call `enqueue(...)` upstream of the queue; do NOT rate-limit `GET /jobs/{id}/status` (UI dashboards poll every 2 s). |
| `add_websocket_chat` (TOOL-052) | No | ⚠️ Caveat — SlowAPI does NOT rate-limit WebSockets | WebSocket upgrade requests pass through the HTTP middleware once at connect time and `slowapi` will rate-limit the upgrade, but per-message throttling requires a separate ASGI-level counter. Document as a known gap. |
| `add_sse` (TOOL-014) | No | ⚠️ Caveat — long-lived connections count once | The initial `GET` for an SSE stream is rate-limited once at connect; subsequent events do not re-trigger middleware. Limit the endpoint with a low budget (`10/minute` keyed by `key_user`) so a client cannot open hundreds of concurrent streams. |
| `add_webhook_receiver` (TOOL-016) | Yes | ⚠️ Caveat — receivers MUST be exempt | Inbound webhook endpoints from `add_webhook_receiver` must call `@limiter.exempt` before any route decorators; replay traffic from well-behaved senders (Stripe, Twilio, GitHub) will otherwise be throttled and the sender will mark the delivery failed. Listed explicitly in tool `notes` and `next_steps`. |

**Conflicts:** None identified. Every SKILL-001 tool can coexist with `add_rate_limiting`; the only real gotcha is the webhook / long-lived connection exemption pattern, which is documented in the tool's own `notes`. SKILL-001 does not currently ship a dedicated scheduled-task tool; the scheduled-task interaction (TOOL-058) is deferred to a future spec.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/main.py \
  requirements.txt

rm -f \
  app/core/rate_limit.py \
  app/middleware/rate_limit.py \
  app/api/routes/rate_limit.py

# If app/middleware/ was created by this tool and is now empty, remove it:
rmdir app/middleware 2>/dev/null || true
```

### 12.2 Runtime rollback (after deploy)

No database migration is involved. To disable rate limiting at runtime without redeploying:

```bash
# 1. Disable globally via env var:
echo "RATE_LIMIT_ENABLED=false" >> .env
# 2. Restart workers:
systemctl restart uvicorn-myapp
# or: kubectl rollout restart deploy/myapp-api
```

`_build_limiter()` will pass `enabled=False` to `slowapi.Limiter` and every request passes the middleware as a no-op. No state to drain, no counters to flush.

### 12.3 Redis storage rollback

Rate-limit counters live in Redis keys matching `LIMITS:*`. They self-expire within the largest configured window (typically ≤ 1 hour). To force-clear immediately:

```bash
redis-cli --scan --pattern 'LIMITS:*' | xargs -r redis-cli DEL
```

There is no compliance significance to these keys — they are rolling counters, not audit rows — so an unconditional flush is safe.

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find app/core app/middleware app/api/routes -name 'rate_limit.py' -newer .git/HEAD -delete
```

Because `add_rate_limiting` writes files one at a time without transactional semantics, a mid-execution Python crash may leave a subset of files written. `git checkout HEAD --` on modified paths plus `rm` on newly-created paths restores the project.

### 12.5 Emergency: Redis outage

1. Set `RATE_LIMIT_ENABLED=false` in `.env` (or Kubernetes secret).
2. Roll-restart the API tier: `kubectl rollout restart deploy/myapp-api` (or `systemctl restart uvicorn-myapp`).
3. The limiter short-circuits; API continues serving traffic with no rate enforcement.
4. Once Redis recovers, set `RATE_LIMIT_ENABLED=true` and roll-restart again.
5. Do **not** also `unset REDIS_URL` — the `memory://` fallback is per-process only and gives false isolation in a multi-worker deployment.

### 12.6 Uninstall validator

After rollback, verify:

```bash
test ! -f app/core/rate_limit.py || (grep -L RateLimitConfig app/core/rate_limit.py >/dev/null || (echo "advanced rate_limit still present" && exit 1))
test ! -f app/middleware/rate_limit.py || (echo "middleware still present" && exit 1)
test ! -f app/api/routes/rate_limit.py || (echo "status route still present" && exit 1)
grep -q "RATE_LIMIT_ENABLED" app/core/config.py && echo "config still patched" && exit 1
grep -q "register_rate_limiting" app/main.py && echo "main.py still patched" && exit 1
grep -q "^slowapi" requirements.txt && echo "requirements still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing a prerequisite (`CONFIG_SETTINGS` or `REQUIREMENTS_TXT`) | `ensure_prerequisites(..., auto_scaffold=not inp.dry_run)` returns errors → tool returns `status="error"` with list of missing prereqs and hint to run `fastapi_generate_project` first |
| EC-03 | Tool runs on a project where `app/core/rate_limit.py` already contains `"RateLimitConfig"` | Early return `status="no_op"` with single note `"RateLimitConfig already present — advanced rate limiting already installed."` — zero file writes (INV-RL-01) |
| EC-04 | Tool runs with `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-RL-02, INV-RL-10) |
| EC-05 | Redis is unavailable at runtime but `REDIS_URL` is set | `slowapi.Limiter` raises on first request; operator recovers by setting `RATE_LIMIT_ENABLED=false` (see §12.5). Tool does not pre-validate Redis because install-time != runtime. |
| EC-06 | `REDIS_URL` unset in dev | `build_config()` falls back to `"memory://"`; works on single-worker Uvicorn; logs a soft warning if multi-worker detected (caller's responsibility — not enforced by the tool) |
| EC-07 | Attacker spoofs `X-Forwarded-For` to bypass `key_ip` | `slowapi.util.get_remote_address` honours `X-Forwarded-For` only when `forwarded_allow_ips` is set on the ASGI server (Uvicorn flag `--forwarded-allow-ips`). Operator MUST configure the trusted proxy list; tool documents this in module docstring. |
| EC-08 | Clock skew between workers on distributed deploy | Fixed-window strategy is clock-sensitive: two workers on slightly different clocks may issue 2x the budget at window boundaries. Moving-window (Lua script on Redis) eliminates this. Document both trade-offs. |
| EC-09 | Burst traffic at window rollover | Fixed-window allows up to 2x the nominal limit in a single burst spanning the boundary. Operators concerned about smooth enforcement should set `RATE_LIMIT_STRATEGY=moving-window`. |
| EC-10 | `app/core/config.py` already contains `RATE_LIMIT_DEFAULT` | `_patch_config` early-returns (`if "RATE_LIMIT_DEFAULT" in src: return`); no duplicate block appended |
| EC-11 | `app/core/config.py` lacks the `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` anchor | `_patch_config` falls back to appending the field block at EOF with 4-space indent; still valid Python but fields may land at module scope if `Settings` class does not span EOF — operator warned via note |
| EC-12 | `app/main.py` already contains `"register_rate_limiting"` | `_patch_main` returns early; `files_modified` does NOT include `main.py`; idempotency preserved |
| EC-13 | `app/main.py` has no `from fastapi import FastAPI` line | `_patch_main` falls back to prepending the import line at file top — still produces valid Python |
| EC-14 | `app/main.py` has no `app = FastAPI(` marker | `_patch_main` appends `register_rate_limiting(app)` at EOF; caller must wire the app variable themselves |
| EC-15 | `requirements.txt` already contains `slowapi` | `_patch_requirements` only appends missing tokens from `{slowapi, limits, redis}`; order preserved; trailing newline handled |
| EC-16 | `app/api/routes/` directory missing (very small fixture) | Status route step is SKIPPED silently (`if routes_dir.exists():`); tool still succeeds with 2 created files + config + requirements patched |
| EC-17 | `app/middleware/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `rate_limit.py`; `__init__.py` created with package docstring if missing |
| EC-18 | Operator forgets to exempt `/webhooks/stripe` after install | Webhook replay traffic gets 429 → Stripe marks delivery failed → signals lost. Mitigation: tool `notes` and `next_steps` explicitly instruct operators to exempt webhook and health-check routes. |
| EC-19 | Proxy sits in front of the API but `--forwarded-allow-ips` is not set on Uvicorn | `key_ip` keys on the proxy's IP for every request — effectively disabling per-client limiting. Operator must set `forwarded-allow-ips` to the proxy CIDR. Documented in `key_ip` docstring. |
| EC-20 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-20 verifies) |
| EC-21 | Shared office NAT causes one customer to throttle all co-workers | Mitigation: switch route to `key_func=key_user`; requires authentication. Documented in user-story US-07. |
| EC-22 | Developer wraps a route with both `@limiter.limit("10/minute")` and `@limiter.exempt` | `@limiter.exempt` wins; SlowAPI skips the check. Tool does not detect this at install time — operator responsibility. |
| EC-23 | `slowapi` import fails at runtime (missing from requirements) | Python raises `ModuleNotFoundError` at app boot; operator sees a clear traceback pointing at `app.core.rate_limit`. The tool's `next_steps` lists the exact `pip install` command. |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 20 Completeness Criteria verified via `test_add_rate_limiting.py` passing
2. ✅ `test_add_rate_limiting.py` reports `20 passed, 0 failed` via both pytest and standalone runner
3. ✅ Tool execution time < 2 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-RL-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-RL-02, INV-RL-10)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-RL-03)
7. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
8. ✅ Module-level `limiter` symbol preserved for backward compat with `app.main` (INV-RL-04)
9. ✅ Three key strategies (`key_ip`, `key_user`, `key_user_endpoint`) present (INV-RL-05)
10. ✅ 429 response carries `Retry-After` and `X-RateLimit-Limit` headers (INV-RL-06)
11. ✅ Redis storage URI derived from `settings.REDIS_URL` with `memory://` fallback (INV-RL-07)
12. ✅ `RATE_LIMIT_*` settings live inside `class Settings` body with 4-space indentation (INV-RL-08)
13. ✅ `app/main.py` imports and calls `register_rate_limiting(app)` exactly once
14. ✅ `requirements.txt` contains `slowapi`, `limits`, `redis[hiredis]` pins (INV-RL-09)
15. ✅ `next_steps` includes `slowapi` install command and `REDIS_URL` guidance (INV-RL-14)
16. ✅ Developer successfully wires `@limiter.limit("10/minute")` on a route, exceeds the limit, and receives a 429 with `Retry-After`

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT, auto_scaffold=not inp.dry_run)` passes
- [ ] `app/core/rate_limit.py` does NOT contain `"RateLimitConfig"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Core limiter module

- [ ] `mkdir -p app/core`
- [ ] Write `app/core/rate_limit.py` via `_write_rate_limit_core`
- [ ] Module contains `RateLimitConfig` `@dataclass(frozen=True)` with five fields
- [ ] `build_config()` reads `getattr(settings, "REDIS_URL", None)` with `"memory://"` fallback
- [ ] `key_ip`, `key_user`, `key_user_endpoint` all emitted as top-level `def`
- [ ] `_build_limiter()` passes `default_limits`, `storage_uri`, `strategy`, `headers_enabled`, `enabled` to `Limiter(...)`
- [ ] Module-level `limiter: Limiter = _build_limiter()` singleton present
- [ ] `get_limiter()` and `reset_limiter()` helpers present

### 15.3 Middleware module

- [ ] `mkdir -p app/middleware`
- [ ] Write `app/middleware/__init__.py` with docstring if missing
- [ ] Write `app/middleware/rate_limit.py` via `_write_rate_limit_middleware`
- [ ] `rate_limit_exceeded_handler` emits `status_code=429`
- [ ] Handler reads `getattr(exc, "retry_after", 60)` for the `Retry-After` value
- [ ] Response body contains `detail`, `limit`, `retry_after_seconds`
- [ ] Response headers contain `Retry-After` and `X-RateLimit-Limit`
- [ ] `register_rate_limiting(app)` attaches `app.state.limiter`, exception handler, and `SlowAPIMiddleware`
- [ ] Structured log `logger.warning("rate_limit.exceeded", extra={"path", "method", "limit"})`

### 15.4 Status route

- [ ] `mkdir -p app/api/routes` only if the parent `app/api/routes` already exists (tool does not create `app/api/` from scratch)
- [ ] Write `app/api/routes/rate_limit.py` via `_write_rate_limit_status_route`
- [ ] `router = APIRouter(prefix="/rate-limit", tags=["rate-limit"])`
- [ ] `RateLimitStatus` Pydantic model with four fields
- [ ] `@router.get("/status", response_model=RateLimitStatus)` decorator
- [ ] Handler calls `build_config()` and `get_limiter()`

### 15.5 Config patch

- [ ] Early-return if `"RATE_LIMIT_DEFAULT" in src`
- [ ] Block emits `RATE_LIMIT_ENABLED`, `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_STRATEGY`, `RATE_LIMIT_HEADERS_ENABLED`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Last-resort fallback: append at EOF (still 4-space-indented)

### 15.6 Main patch

- [ ] Early-return if `"register_rate_limiting" in src`
- [ ] Insert import: `from app.middleware.rate_limit import register_rate_limiting  # noqa: F401 — rate limiting`
- [ ] Walk from `app = FastAPI(` tracking paren depth to find the matching close paren
- [ ] Insert `register_rate_limiting(app)` on the line after the FastAPI constructor closes
- [ ] Fallback: append `register_rate_limiting(app)` at EOF

### 15.7 Requirements patch

- [ ] Add `slowapi>=0.1.9` if `"slowapi"` absent
- [ ] Add `limits>=3.13.0` if `"limits"` absent
- [ ] Add `redis[hiredis]>=5.0.0` if `"redis"` absent
- [ ] Preserve trailing newline; skip the whole patch if all three tokens already present

### 15.8 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain Redis storage, default limits, RFC 6585 headers, webhook exemption requirement
- [ ] `next_steps` contains `pip install` command, `REDIS_URL` guidance, decorator usage, exemption hint, status endpoint hint
- [ ] `execution_time_ms` set on success, no_op, dry_run, error paths

### 15.9 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists all emitted files and the "why SlowAPI + Redis" rationale
- [ ] `add_rate_limiting` docstring documents `ToolInput` parameters

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/core/rate_limit.py",
    "/tmp/fixture/app/middleware/__init__.py",
    "/tmp/fixture/app/middleware/rate_limit.py",
    "/tmp/fixture/app/api/routes/rate_limit.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/main.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "SlowAPI rate limiting installed with Redis storage and 3 key strategies.",
    "Default limits: 100/minute per IP, 1000/hour per user, customisable via env.",
    "429 responses include Retry-After and X-RateLimit-* headers (RFC 6585).",
    "Webhook and health-check routes must be explicitly exempted with @limiter.exempt."
  ],
  "next_steps": [
    "pip install 'slowapi>=0.1.9' 'limits>=3.13.0' 'redis[hiredis]>=5.0.0'",
    "Set REDIS_URL in .env (used for multi-worker rate limit storage).",
    "Apply limits to routes via @limiter.limit('10/minute') decorator.",
    "Exempt health/webhook routes: @limiter.exempt.",
    "Read current quota from GET /rate-limit/status (requires auth)."
  ],
  "execution_time_ms": 37
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "RateLimitConfig already present — advanced rate limiting already installed."
  ],
  "next_steps": [],
  "execution_time_ms": 2
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/core/rate_limit.py, app/middleware/rate_limit.py, and app/api/routes/rate_limit.py."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 1
}
```

Example `error` return (prereq failure):

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - CONFIG_SETTINGS: app/core/config.py missing\n  - REQUIREMENTS_TXT: requirements.txt missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first with fastapi_generate_project(...)."
  ],
  "execution_time_ms": 2
}
```

---
