# TOOL-099: add_chaos_testing

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_chaos_testing` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, pydantic-settings, starlette |
| Signature | `add_chaos_testing(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and optional `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_chaos_testing", "description": "Add chaos engineering infrastructure with latency, error, and timeout injection for resilience testing.", "tags": ["extend", "infrastructure"], "entry": "add_chaos_testing"}` |
| Files created (typical) | 5 — `app/chaos/__init__.py`, `app/chaos/injectors.py`, `app/chaos/middleware.py`, `app/api/routes/chaos.py`, and patched `app/core/config.py` |
| Files modified (typical) | 1–2 — `app/core/config.py`, optionally `app/main.py` |

---

## 2. Purpose

The `fastapi_add_chaos_testing` tool installs a full chaos engineering infrastructure into a FastAPI project, enabling controlled fault injection during load and resilience testing. Testing resilience mechanisms in isolation — circuit breakers with mocked errors, retry budgets with synthetic exceptions, graceful shutdown with manual signals — gives incomplete confidence. Until a service actually experiences the faults those mechanisms are designed to handle under realistic ASGI request flow, engineers cannot know whether the mechanisms fire at the right thresholds, whether alerting is calibrated to production noise levels, or whether on-call engineers can distinguish a chaos-triggered anomaly from a real outage. Chaos testing makes the invisible visible before it appears in production.

The core design decision is the **hardcoded production guard**. `ChaosEngine.enable()` checks `os.getenv("ENVIRONMENT")` and silently refuses to activate when the value equals `"production"`. This is intentional — the guard cannot be disabled via environment variables or configuration files. Engineers who need chaos in a production canary must explicitly remove the guard at the source level and document the decision in a change record. The same guard is duplicated in `is_enabled()`, so even if a caller constructs a `ChaosEngine` directly and bypasses `enable()`, the chaos remains inert in production. The route `POST /chaos/enable` adds a third layer: it returns `403 Forbidden` when `ENVIRONMENT=production` before even calling the engine. Three independent guards make accidental activation in production statistically impossible.

`ChaosMiddleware` intercepts every request that is not on the pass-through list (`/healthz`, `/chaos/status`, `/chaos/enable`, `/chaos/disable`). When the engine is enabled, it runs three injectors in sequence. `LatencyInjector.inject()` performs an `asyncio.sleep(latency_ms / 1000)` adding configurable extra delay. `ErrorInjector.inject()` evaluates `random.random() < error_rate` and raises `HTTPException(500)` — when `error_rate=1.0`, every request fails; at `0.1`, one in ten fails. `TimeoutInjector.inject()` sleeps for `hang_seconds` (default 35 s) at the configured `timeout_rate` — enough to exhaust any reasonable upstream timeout setting. The injectors run in that order: latency first (simulates slow backend), error second (simulates backend error), timeout last (simulates backend hang). All three are importable from `app.chaos.injectors` as independent classes, making unit-testing each injector in isolation straightforward.

Three management routes (`POST /chaos/enable`, `POST /chaos/disable`, `GET /chaos/status`) allow test orchestrators to remote-control the chaos state during automated load runs without restarting the server. `get_chaos_engine()` returns a process-wide singleton seeded from environment variables at first access — `CHAOS_LATENCY_MS`, `CHAOS_ERROR_RATE`, `CHAOS_TIMEOUT_RATE` — and optionally auto-enables if `CHAOS_ENABLED=true` is set. The singleton pattern ensures all middleware and route handlers share the same state reference.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 5 | chaos package, injectors, middleware, routes, patched files (CC-04) |
| Files modified | ≥ 1 | Config patch (CC-05) |
| Max function LOC | ≤ 50 | AST walk enforced |
| Middleware overhead when chaos disabled | < 0.1 ms | Single `is_enabled()` boolean check |
| Production guard block rate | 100% | `os.getenv("ENVIRONMENT") == "production"` in engine, route, and `is_enabled()` |
| `CHAOS_ENABLED` default | `False` | No chaos active in fresh installs |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
app/
├── main.py
├── core/
│   └── config.py       # No CHAOS_* settings
├── api/
│   └── routes/         # No /chaos routes
└── middleware/         # No ChaosMiddleware
```

No fault injection capability. Resilience mechanisms (circuit breaker, retry budget, bulkhead) have never been exercised under realistic faults in staging. Engineers cannot trigger controlled latency or error scenarios without restarting the server with mocks.

### 4.2 ChaosEngine with production guard: AFTER

```python
# app/chaos/__init__.py
"""Chaos engineering engine — fault injection for dev/staging.

PRODUCTION GUARD: chaos is physically blocked when
``ENVIRONMENT == "production"``. The guard is hardcoded and cannot
be bypassed via configuration.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_engine: "ChaosEngine | None" = None


class ChaosEngine:
    """Central registry for chaos injectors."""

    def __init__(
        self,
        latency_ms: int = 0,
        error_rate: float = 0.0,
        timeout_rate: float = 0.0,
    ) -> None:
        self.latency_ms = latency_ms
        self.error_rate = error_rate
        self.timeout_rate = timeout_rate
        self._enabled = False

    def enable(self) -> None:
        """Enable fault injection (blocked in production)."""
        env = os.getenv("ENVIRONMENT", "local")
        if env == "production":
            logger.error(
                "CHAOS BLOCKED: cannot enable chaos in production environment."
            )
            return  # silent no-op — production guard hardcoded
        self._enabled = True

    def disable(self) -> None:
        """Disable all fault injection."""
        self._enabled = False

    def is_enabled(self) -> bool:
        """Return True if chaos is active and environment is not production."""
        if os.getenv("ENVIRONMENT", "local") == "production":
            return False  # second production guard
        return self._enabled

    def status(self) -> dict:
        """Return current chaos configuration."""
        return {
            "enabled": self.is_enabled(),
            "environment": os.getenv("ENVIRONMENT", "local"),
            "latency_ms": self.latency_ms,
            "error_rate": self.error_rate,
            "timeout_rate": self.timeout_rate,
        }


def get_chaos_engine() -> ChaosEngine:
    """Return the global ChaosEngine singleton."""
    global _engine
    if _engine is None:
        _engine = ChaosEngine(
            latency_ms=int(os.getenv("CHAOS_LATENCY_MS", "0")),
            error_rate=float(os.getenv("CHAOS_ERROR_RATE", "0.0")),
            timeout_rate=float(os.getenv("CHAOS_TIMEOUT_RATE", "0.0")),
        )
        if os.getenv("CHAOS_ENABLED", "false").lower() == "true":
            _engine.enable()
    return _engine
```

### 4.3 Three injectors: AFTER

```python
# app/chaos/injectors.py
"""Fault injector implementations: latency, error, timeout."""
from __future__ import annotations

import asyncio
import random

from fastapi import HTTPException


class LatencyInjector:
    """Inject artificial latency (asyncio.sleep)."""

    def __init__(self, latency_ms: int = 200) -> None:
        self.latency_ms = latency_ms

    async def inject(self) -> None:
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0)


class ErrorInjector:
    """Randomly raise HTTP 500 at the configured rate."""

    def __init__(self, error_rate: float = 0.1) -> None:
        self.error_rate = error_rate

    def inject(self) -> None:
        """Raise HTTPException(500) at self.error_rate probability."""
        if random.random() < self.error_rate:
            raise HTTPException(
                status_code=500,
                detail="Chaos fault injection — simulated server error",
            )


class TimeoutInjector:
    """Sleep long enough to trigger upstream timeouts."""

    def __init__(self, timeout_rate: float = 0.05, hang_seconds: float = 35.0) -> None:
        self.timeout_rate = timeout_rate
        self.hang_seconds = hang_seconds

    async def inject(self) -> None:
        if random.random() < self.timeout_rate:
            await asyncio.sleep(self.hang_seconds)
```

### 4.4 ChaosMiddleware: AFTER

```python
# app/chaos/middleware.py
"""ASGI middleware that applies chaos fault injection to every request
except health and chaos management endpoints."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.chaos import get_chaos_engine
from app.chaos.injectors import ErrorInjector, LatencyInjector, TimeoutInjector

_PASS_THROUGH: frozenset[str] = frozenset({
    "/healthz",
    "/chaos/status",
    "/chaos/enable",
    "/chaos/disable",
})


class ChaosMiddleware(BaseHTTPMiddleware):
    """Apply chaos faults to incoming requests.

    Skips /healthz and /chaos/* management paths.
    Completely inert when ChaosEngine.is_enabled() == False.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        engine = get_chaos_engine()
        if not engine.is_enabled() or request.url.path in _PASS_THROUGH:
            return await call_next(request)

        await LatencyInjector(latency_ms=engine.latency_ms).inject()
        ErrorInjector(error_rate=engine.error_rate).inject()
        await TimeoutInjector(timeout_rate=engine.timeout_rate).inject()

        return await call_next(request)
```

### 4.5 Management routes: AFTER

```python
# app/api/routes/chaos.py
"""Chaos engineering control endpoints."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from app.chaos import get_chaos_engine

router = APIRouter(prefix="/chaos", tags=["chaos"])


@router.post("/enable", response_model=dict)
async def enable_chaos() -> dict:
    """Enable chaos fault injection (blocked in production → 403)."""
    if os.getenv("ENVIRONMENT", "local") == "production":
        raise HTTPException(
            status_code=403,
            detail="Chaos testing cannot be enabled in production.",
        )
    engine = get_chaos_engine()
    engine.enable()
    return engine.status()


@router.post("/disable", response_model=dict)
async def disable_chaos() -> dict:
    """Disable chaos fault injection."""
    engine = get_chaos_engine()
    engine.disable()
    return engine.status()


@router.get("/status", response_model=dict)
async def chaos_status() -> dict:
    """Return current chaos engine configuration."""
    return get_chaos_engine().status()
```

### 4.6 Config patch: AFTER

```python
# app/core/config.py (fragment — injected by tool)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Chaos testing (TOOL-099) — NEVER enable in production
    CHAOS_ENABLED: bool = False
    CHAOS_LATENCY_MS: int = 0
    CHAOS_ERROR_RATE: float = 0.0
    CHAOS_TIMEOUT_RATE: float = 0.0
```

### 4.7 main.py registration (caller pattern)

```python
# app/main.py (after tool runs)
from app.chaos.middleware import ChaosMiddleware
from app.api.routes.chaos import router as _chaos_router

app = FastAPI(...)
app.add_middleware(ChaosMiddleware)   # add BEFORE other middleware
app.include_router(_chaos_router)
```

### 4.8 Using chaos in a staging load test

```python
# test_load_resilience.py — orchestrator controlling chaos
import httpx

BASE = "http://localhost:8000"

# Enable chaos: 150ms latency + 5% errors + 2% timeouts
with httpx.Client() as c:
    r = c.post(f"{BASE}/chaos/enable")
    assert r.status_code == 200

# Run load
run_locust(...)

# Disable chaos
with httpx.Client() as c:
    r = c.post(f"{BASE}/chaos/disable")
    assert r.json()["enabled"] is False
```

### 4.9 Verifying each injector in unit tests

```python
import asyncio
import pytest
from app.chaos.injectors import LatencyInjector, ErrorInjector, TimeoutInjector
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_latency_injector_sleeps():
    import time
    inj = LatencyInjector(latency_ms=50)
    start = time.monotonic()
    await inj.inject()
    elapsed = (time.monotonic() - start) * 1000
    assert elapsed >= 40  # allow 10ms tolerance


def test_error_injector_at_100_percent():
    inj = ErrorInjector(error_rate=1.0)
    with pytest.raises(HTTPException) as exc:
        inj.inject()
    assert exc.value.status_code == 500


def test_error_injector_at_0_percent():
    inj = ErrorInjector(error_rate=0.0)
    inj.inject()  # must not raise


@pytest.mark.asyncio
async def test_timeout_injector_at_0_percent():
    inj = TimeoutInjector(timeout_rate=0.0)
    await inj.inject()  # must not sleep
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent on second run | `"ChaosEngine" in chaos/__init__.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `Path.write_text()` |
| QS-3 | All `.py` AST-parse clean | `_assert_parses` loop after creation |
| QS-4 | No function > 50 LOC | AST walk over all generated files |
| QS-5 | Production guard hardcoded in `enable()` | `os.getenv("ENVIRONMENT") == "production"` literal in source |
| QS-6 | Production guard in `is_enabled()` | Second independent check in same class |
| QS-7 | Route returns 403 in production | `POST /chaos/enable` guard check (CC-09) |
| QS-8 | Chaos disabled by default | `CHAOS_ENABLED: bool = False` in config |
| QS-9 | `ChaosMiddleware` skips management routes | `_PASS_THROUGH` frozenset in middleware |
| QS-10 | Config 4-space indent | `_patch_config` anchored on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-11 | `execution_time_ms` positive | `_elapsed_ms(start)` with `time.monotonic()` |
| QS-12 | `GET /chaos/status` returns `enabled` + `environment` | Response shape verified (B-02) |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run → `no_op` | `r2.status == "no_op"` | T-02 |
| CC-03 | `dry_run=True` → zero writes | `before_tree == after_tree` | T-03 |
| CC-04 | ≥ 5 files created | `len(files_created) >= 5` | T-04 |
| CC-05 | ≥ 1 file modified | `len(files_modified) >= 1` | T-05 |
| CC-06 | All `.py` in `app/chaos/` parse | `ast.parse` loop | T-06 |
| CC-07 | No function > 50 LOC | AST walk | T-07 |
| CC-08 | `CHAOS_ENABLED` in config, 4-space indent | Substring + indent check | T-08 |
| CC-09 | `chaos.py` route uses `APIRouter` with `/chaos` prefix | File + symbol check | T-10 |
| CC-10 | `class ChaosEngine` defined in `__init__.py` | Symbol search | T-11 |
| CC-11 | `LatencyInjector`, `ErrorInjector`, `TimeoutInjector` all present | All three in injectors file | T-12 |
| CC-12 | `"production"` string in `ChaosEngine.enable()` | Substring in source | T-13 |
| CC-13 | `ChaosMiddleware` defined in `middleware.py` | Symbol search | T-14 |
| CC-14 | `enable_chaos` function or `/enable` route in routes file | Enable path present | T-15 |
| CC-15 | `disable` and `status` routes present | Both paths in source | T-16 |
| CC-16 | `CHAOS_ENABLED` defaults to `False` | `False` literal in config | T-17 |
| CC-17 | `models/__init__.py` still parseable after run | `ast.parse` on models | T-09 |
| CC-18 | `execution_time_ms > 0` | Positive integer check | T-23 |
| CC-19 | `next_steps` list contains "chaos" token | Token in joined string | T-24 |
| CC-20 | Second run leaves all `.py` parseable | `ast.parse` on all chaos files | T-25 |

---

## 7. Definition of Done (DoD)

- [ ] All CC-01 through CC-20 verified by `test_add_chaos_testing.py`
- [ ] `ChaosEngine.enable()` silently no-ops when `ENVIRONMENT=production`
- [ ] `ChaosEngine.is_enabled()` returns `False` when `ENVIRONMENT=production` even if `_enabled=True`
- [ ] `ChaosMiddleware` skips `/healthz`, `/chaos/status`, `/chaos/enable`, `/chaos/disable`
- [ ] `LatencyInjector`, `ErrorInjector`, `TimeoutInjector` importable from `app.chaos.injectors`
- [ ] `GET /chaos/status` returns dict with `enabled` and `environment` keys
- [ ] `POST /chaos/enable` returns `403 Forbidden` when `ENVIRONMENT=production`
- [ ] `CHAOS_ENABLED` defaults to `False` in `app/core/config.py`
- [ ] Config fields use 4-space indent
- [ ] `execution_time_ms` is a positive integer
- [ ] `MCP_TOOL` descriptor present in source module

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CT-01 | Idempotent on re-run | Fingerprint `"ChaosEngine"` in `chaos/__init__.py` → `no_op` | T-02, T-25 |
| INV-CT-02 | `dry_run=True` never writes to filesystem | Early return before `Path.write_text()` | T-03 |
| INV-CT-03 | All generated `.py` files pass `ast.parse` | `_assert_parses` loop | T-06, T-25 |
| INV-CT-04 | Production guard MUST block `enable()` regardless of config | `os.getenv("ENVIRONMENT") == "production"` hardcoded in `enable()` | T-13, B-04 |
| INV-CT-05 | `is_enabled()` returns `False` in production even if `_enabled=True` | Second guard in `is_enabled()` | B-04 |
| INV-CT-06 | Chaos MUST be disabled by default | `CHAOS_ENABLED: bool = False` | T-17, B-03 |
| INV-CT-07 | `ChaosMiddleware` MUST skip management routes | `_PASS_THROUGH` frozenset | T-14, B-01 |
| INV-CT-08 | Config fields MUST be inside `class Settings` body | 4-space indent enforcement | T-08 |
| INV-CT-09 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` | T-23 |
| INV-CT-10 | POST /chaos/enable returns 403 in production | Route-level guard | B-05, B-06 |

---

## 9. User Stories

### 9.1 Core installation (US-01 .. US-05)

**US-01: Successful install on fresh project**
- **Given:** A valid FastAPI project without chaos infrastructure
- **When:** `add_chaos_testing(ToolInput(project_dir="/path"))` is called
- **Then:** `result.status == "success"`, `len(result.files_created) >= 5` (CC-01, CC-04)

**US-02: Idempotent CI re-run**
- **Given:** Chaos testing already installed (first run succeeded)
- **When:** The tool is called a second time
- **Then:** `result.status == "no_op"`, no files are modified (INV-CT-01)

**US-03: Dry-run preview**
- **Given:** A valid project
- **When:** `add_chaos_testing(ToolInput(project_dir="/path", dry_run=True))` is called
- **Then:** `result.status == "success"`, filesystem is unchanged before and after (INV-CT-02)

**US-04: All generated files are syntactically valid**
- **Given:** A tool run that returns `status="success"`
- **When:** Each `files_created` path is loaded with `ast.parse()`
- **Then:** No `SyntaxError` is raised for any file (INV-CT-03)

**US-05: Config fields are properly indented**
- **Given:** Tool run succeeds
- **When:** `app/core/config.py` is read
- **Then:** `CHAOS_ENABLED: bool = False` is present with 4-space indent inside `class Settings` body (CC-08)

### 9.2 Production guard mechanics (US-06 .. US-10)

**US-06: `enable()` silently ignores production environment**
- **Given:** `ENVIRONMENT=production` is set in the OS environment
- **When:** `engine.enable()` is called
- **Then:** `engine.is_enabled()` returns `False`; no exception is raised (INV-CT-04)

**US-07: `is_enabled()` returns False in production regardless of `_enabled` state**
- **Given:** Engine `_enabled` attribute is manually set to `True` (bypassing `enable()`)
- **When:** `engine.is_enabled()` is called with `ENVIRONMENT=production`
- **Then:** Returns `False` due to second guard in `is_enabled()` (INV-CT-05)

**US-08: `POST /chaos/enable` returns 403 in production**
- **Given:** `ENVIRONMENT=production`
- **When:** `POST /chaos/enable` is called via the API
- **Then:** Response is `403 Forbidden` (INV-CT-10)

**US-09: Chaos disabled by default after install**
- **Given:** Fresh install, `CHAOS_ENABLED` not set or set to `false`
- **When:** `GET /chaos/status`
- **Then:** `{"enabled": false, "environment": "local"}` (INV-CT-06)

**US-10: Engine auto-enables from environment on first access**
- **Given:** `CHAOS_ENABLED=true` and `ENVIRONMENT=staging` set in environment
- **When:** `get_chaos_engine()` is called for the first time
- **Then:** Engine is enabled, seeded with `CHAOS_LATENCY_MS`, `CHAOS_ERROR_RATE`, `CHAOS_TIMEOUT_RATE` values

### 9.3 Fault injection behaviour (US-11 .. US-15)

**US-11: Latency injector adds configurable delay**
- **Given:** `CHAOS_LATENCY_MS=200` and chaos enabled
- **When:** A request hits `ChaosMiddleware`
- **Then:** `LatencyInjector(latency_ms=200).inject()` is called, adding ≈200 ms (CC-11)

**US-12: Error injector returns 500 at `error_rate=1.0`**
- **Given:** `CHAOS_ERROR_RATE=1.0` and chaos enabled
- **When:** A request hits `ChaosMiddleware`
- **Then:** Every request receives `HTTP 500` (CC-11)

**US-13: Timeout injector hangs for 35 s at `timeout_rate=1.0`**
- **Given:** `CHAOS_TIMEOUT_RATE=1.0` and chaos enabled
- **When:** A request hits `ChaosMiddleware`
- **Then:** `asyncio.sleep(35)` is called, simulating a hung backend

**US-14: All three injectors importable from `app.chaos.injectors`**
- **Given:** Tool installed
- **When:** `from app.chaos.injectors import LatencyInjector, ErrorInjector, TimeoutInjector`
- **Then:** All three names are available with no `ImportError` (CC-11)

**US-15: Injectors execute in order: latency → error → timeout**
- **Given:** All three injectors configured with non-zero values
- **When:** `ChaosMiddleware.dispatch()` runs
- **Then:** Latency sleep happens first, then error check, then timeout sleep — documented order

### 9.4 Health-check and pass-through (US-16 .. US-20)

**US-16: `/healthz` excluded from chaos injection**
- **Given:** Chaos fully enabled with `error_rate=1.0`
- **When:** `GET /healthz`
- **Then:** Response is `200 OK` — health probe bypasses all injectors (INV-CT-07)

**US-17: `/chaos/status` excluded from chaos injection**
- **Given:** Chaos enabled
- **When:** `GET /chaos/status`
- **Then:** Route returns `200 OK` with current status — not affected by error injector

**US-18: `/chaos/enable` and `/chaos/disable` excluded from chaos**
- **Given:** Chaos enabled with error_rate=1.0
- **When:** `POST /chaos/disable` is called
- **Then:** Route executes and returns current status — not blocked by error injector

**US-19: Business routes ARE subject to chaos injection**
- **Given:** Chaos enabled with error_rate=1.0
- **When:** `GET /api/v1/items`
- **Then:** Returns `500` from chaos injection (not from actual route logic)

**US-20: Middleware is completely inert when chaos is disabled**
- **Given:** `CHAOS_ENABLED=false` (default)
- **When:** Any request hits `ChaosMiddleware`
- **Then:** `is_enabled()` returns `False` and the request passes through unchanged in < 0.1 ms

### 9.5 Ops and integration (US-21 .. US-25)

**US-21: `GET /chaos/status` response includes `environment` key**
- **Given:** Tool installed on staging environment
- **When:** `GET /chaos/status`
- **Then:** Response JSON contains both `enabled` and `environment` keys (CC-09, B-02)

**US-22: `POST /chaos/disable` turns off injection immediately**
- **Given:** Chaos currently enabled
- **When:** `POST /chaos/disable`
- **Then:** `GET /chaos/status` → `{"enabled": false}` (CC-15)

**US-23: Chaos compatible with load shedding middleware**
- **Given:** Both `ChaosMiddleware` and `LoadSheddingMiddleware` registered
- **When:** Chaos latency is enabled, load is high
- **Then:** Load shedding triggers at its threshold — both middleware operate independently

**US-24: Second run after tool is idempotent and leaves files parseable**
- **Given:** First run succeeded
- **When:** Tool runs a second time (idempotency), then all `.py` in `app/chaos/` are re-parsed
- **Then:** All files still pass `ast.parse()` (INV-CT-01, INV-CT-03)

**US-25: `execution_time_ms` is a positive integer in all outcomes**
- **Given:** Tool called in any mode (success, no_op, dry_run, error)
- **When:** `result.execution_time_ms` is read
- **Then:** Value is an integer > 0 (INV-CT-09)

---

## 10. Test Plan

### 10.1 Structural tests (`test_add_chaos_testing.py`)

| # | Test ID | Test name | Expected |
|---|---------|-----------|----------|
| T-01 | CC-01 | `test_success_on_fresh_project` | `status="success"` |
| T-02 | CC-02 | `test_idempotent_second_run` | `status="no_op"` |
| T-03 | CC-03 | `test_dry_run_zero_writes` | Filesystem unchanged |
| T-04 | CC-04 | `test_files_created_count` | `len(files_created) >= 5` |
| T-05 | CC-05 | `test_files_modified_count` | `len(files_modified) >= 1` |
| T-06 | CC-06 | `test_chaos_py_files_parse` | All `.py` in `app/chaos/` parse |
| T-07 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk: max function body ≤ 50 |
| T-08 | CC-08 | `test_chaos_config_fields_4space` | `CHAOS_ENABLED` present, 4-space indent |
| T-09 | CC-17 | `test_models_init_not_broken` | `app/models/__init__.py` still parseable |
| T-10 | CC-09 | `test_chaos_route_file` | `APIRouter` + `/chaos` prefix in routes file |
| T-11 | CC-10 | `test_chaos_engine_class` | `class ChaosEngine` in `__init__.py` |
| T-12 | CC-11 | `test_three_injectors_present` | All three injector class names in `injectors.py` |
| T-13 | CC-12 | `test_production_guard_in_source` | `"production"` literal in `enable()` source |
| T-14 | CC-13 | `test_chaos_middleware_class` | `ChaosMiddleware` in `middleware.py` |
| T-15 | CC-14 | `test_enable_route_present` | `enable_chaos` or `"/enable"` in routes |
| T-16 | CC-15 | `test_disable_and_status_routes` | Both `disable` and `status` paths in routes |
| T-17 | CC-16 | `test_chaos_enabled_default_false` | `False` as default in `CHAOS_ENABLED` field |
| T-23 | CC-18 | `test_execution_time_positive` | `execution_time_ms > 0` |
| T-24 | CC-19 | `test_next_steps_mention_chaos` | "chaos" token in `" ".join(next_steps)` |
| T-25 | CC-20 | `test_second_run_files_still_parse` | All chaos `.py` parse after second invocation |

### 10.2 Behavior tests (`test_add_chaos_testing_behavior.py`)

| # | Test ID | Test name | Assertion |
|---|---------|-----------|-----------|
| B-01 | INV-CT-07 | `test_healthz_excluded_from_chaos` | `GET /healthz` → 200 when error_rate=1.0 |
| B-02 | CC-09 | `test_chaos_status_route_shape` | `GET /chaos/status` → `{enabled, environment, latency_ms, error_rate, timeout_rate}` |
| B-03 | INV-CT-06 | `test_chaos_disabled_by_default` | `enabled == False` on fresh engine |
| B-04 | INV-CT-04/05 | `test_production_guard_blocks_enable` | `is_enabled() == False` after `enable()` with `ENVIRONMENT=production` |
| B-05 | INV-CT-10 | `test_enable_route_403_in_production` | `POST /chaos/enable` → 403 when `ENVIRONMENT=production` |
| B-06 | CC-11 | `test_injectors_importable` | `from app.chaos.injectors import ...` — no ImportError |
| B-07 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk on all generated files |
| B-08 | CC-08 | `test_config_4space_indent` | Fields inside `class Settings` body |
| B-09 | QS-9 | `test_middleware_pass_through_when_disabled` | Overhead < 0.1 ms when chaos is off |
| B-10 | QS-12 | `test_status_contains_environment_key` | `"environment"` in `GET /chaos/status` response |

---

## 11. Interaction Matrix

| Other tool | Interaction type | Notes |
|------------|-----------------|-------|
| `add_load_shedding` (TOOL-095) | ✅ Complementary | Chaos latency raises p99 → triggers load shedding 429; validates load shedding threshold calibration |
| `add_adaptive_timeouts` (TOOL-096) | ✅ Complementary | Chaos timeout hang triggers adaptive timeout adjustment; validates timeout escalation |
| `add_bulkhead_isolation` (TOOL-097) | ✅ Complementary | Chaos errors fill bulkhead semaphore slots; validates pool exhaustion handling |
| `add_retry_budget` (TOOL-098) | ✅ Complementary | Chaos errors cause client retries; validates budget tracking under fault load |
| `add_graceful_shutdown` (TOOL-100) | ✅ Neutral | Both use middleware pattern; register `GracefulShutdownMiddleware` before `ChaosMiddleware` in `main.py` |
| `add_circuit_breaker` | ✅ Complementary | Chaos errors trigger circuit breaker open state; validates trip threshold calibration |
| `add_anomaly_detector` (TOOL-102) | ✅ Complementary | Chaos-induced errors and latency spike anomaly scores; validates alert thresholds |
| `add_request_fingerprint` (TOOL-103) | ✅ Neutral | Chaos errors on first request do not affect idempotency replay of the same fingerprint |
| `generate_project` | ✅ Prerequisite | Requires `app/core/config.py` with `class Settings` — generate project first |
| `add_arq_worker` (TOOL-053) | ✅ Neutral | Background worker routes excluded from chaos; `ChaosMiddleware` only affects ASGI layer |
| `add_api_replay_debugger` (TOOL-101) | ✅ Complementary | Chaos-injected 500s are recorded by replay debugger; replay shows original vs error diff |
| `add_healthcheck` | ✅ Required | `/healthz` must exist in pass-through list; both tools needed for chaos-safe health probes |
| Second `add_chaos_testing` call | ✅ Idempotent | `no_op` — engine already present |
| `add_load_shedding` + chaos at high rate | ⚠️ Cascade risk | With chaos error_rate=0.8 + load shedding, most requests 500 or 429; test one at a time |

---

## 12. Rollback Procedure

### 12.1 Remove generated chaos package

```bash
rm -rf app/chaos/
```

### 12.2 Remove chaos routes

```bash
rm -f app/api/routes/chaos.py
```

### 12.3 Restore config

```bash
git checkout HEAD -- app/core/config.py
```

Or manually remove the `CHAOS_ENABLED`, `CHAOS_LATENCY_MS`, `CHAOS_ERROR_RATE`, `CHAOS_TIMEOUT_RATE` fields from `app/core/config.py`.

### 12.4 Remove middleware and router from `main.py`

```bash
git checkout HEAD -- app/main.py
```

Or manually remove:
- `from app.chaos.middleware import ChaosMiddleware`
- `from app.api.routes.chaos import router as _chaos_router`
- `app.add_middleware(ChaosMiddleware)`
- `app.include_router(_chaos_router)`

### 12.5 Verify rollback

```bash
python -c "from app.main import app; print('OK')"
pytest tests/ -x --tb=short
```

### 12.6 Re-run to restore

```bash
# Re-install after rollback:
python -c "
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_chaos_testing import add_chaos_testing
r = add_chaos_testing(ToolInput(project_dir='$(pwd)'))
print(r.status, r.files_created)
"
```

---

## 13. Edge Cases

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| EC-01 | `"ChaosEngine"` already in `app/chaos/__init__.py` | `status="no_op"`, no files modified |
| EC-02 | `dry_run=True` on any valid project | `status="success"`, zero writes, filesystem unchanged |
| EC-03 | `ENVIRONMENT=production` + `engine.enable()` | `_enabled` stays `False`; no exception raised |
| EC-04 | `ENVIRONMENT=production` + `is_enabled()` with `_enabled=True` | Returns `False` due to second guard |
| EC-05 | `CHAOS_ERROR_RATE=0.0` and `CHAOS_LATENCY_MS=0` | Middleware is active but no-ops; zero overhead |
| EC-06 | `GET /healthz` with chaos `error_rate=1.0` | Returns `200 OK`; excluded from `_PASS_THROUGH` |
| EC-07 | `app/api/routes/` directory does not exist | Routes file skipped; tool still succeeds with 4 files instead of 5 |
| EC-08 | `app/core/config.py` does not exist | Config patch skipped; `files_modified` remains empty |
| EC-09 | `CHAOS_ENABLED=True` set in `.env` at startup | Engine auto-enables on first `get_chaos_engine()` call |
| EC-10 | `app/main.py` already contains `ChaosMiddleware` | `_patch_main()` detects string and skips re-patching |
| EC-11 | `CHAOS_LATENCY_MS` set to negative value | `LatencyInjector` skips sleep when `latency_ms <= 0` |
| EC-12 | `CHAOS_ERROR_RATE` > 1.0 | `ErrorInjector` always fires (equivalent to 1.0); no exception from `random.random()` |
| EC-13 | `TimeoutInjector` with `hang_seconds=35` at `timeout_rate=1.0` | Every request hangs 35 s; upstream must have client-side timeout |
| EC-14 | `get_chaos_engine()` called concurrently on startup | Race condition on `_engine is None` check; safe in Python GIL context, last writer wins |
| EC-15 | Second `add_chaos_testing` call after manual partial deletion | If `ChaosEngine` not in file, tool re-runs fully — not a true no_op |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All CC-01 through CC-20 pass in `test_add_chaos_testing.py`
2. ✅ `ChaosEngine.enable()` silently no-ops when `ENVIRONMENT=production`
3. ✅ `ChaosEngine.is_enabled()` returns `False` when `ENVIRONMENT=production` regardless of `_enabled` flag
4. ✅ `POST /chaos/enable` returns `403 Forbidden` when `ENVIRONMENT=production`
5. ✅ `CHAOS_ENABLED` defaults to `False` in `app/core/config.py`
6. ✅ All three injectors in `app.chaos.injectors` are individually importable
7. ✅ `ChaosMiddleware` excludes `/healthz`, `/chaos/status`, `/chaos/enable`, `/chaos/disable`
8. ✅ `GET /chaos/status` response includes both `enabled` and `environment` keys
9. ✅ All generated `.py` files pass `ast.parse()` with no `SyntaxError`
10. ✅ No generated function exceeds 50 LOC (AST walk)
11. ✅ Config fields have 4-space indent inside `class Settings` body
12. ✅ `execution_time_ms` is a positive integer in all result types
13. ✅ Second run returns `no_op` without modifying files
14. ✅ `dry_run=True` produces zero filesystem writes

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks

- [ ] Validate `project_dir` with `validate_project_dir()` — return error if invalid
- [ ] Run `ensure_prerequisites(Prereq.CONFIG_SETTINGS, Prereq.REQUIREMENTS_TXT)` — return error if not met
- [ ] Check idempotency: `"ChaosEngine" in (app/chaos/__init__.py)` → return `no_op` if true
- [ ] If `dry_run=True`, return early success with note about what would be created

### 15.2 Chaos package creation

- [ ] Create `app/chaos/` directory with `mkdir(parents=True, exist_ok=True)`
- [ ] Write `app/chaos/__init__.py` via `_write_chaos_engine()`:
  - [ ] `ChaosEngine` class with `enable()` containing production guard on `ENVIRONMENT`
  - [ ] `is_enabled()` with second production guard
  - [ ] `status()` returning dict with 5 keys
  - [ ] `get_chaos_engine()` singleton factory seeding from environment vars
- [ ] Write `app/chaos/injectors.py` via `_write_chaos_injectors()`:
  - [ ] `LatencyInjector.inject()` — async, skips if `latency_ms <= 0`
  - [ ] `ErrorInjector.inject()` — sync, raises `HTTPException(500)` at configured rate
  - [ ] `TimeoutInjector.inject()` — async, sleeps `hang_seconds` at configured rate

### 15.3 Middleware

- [ ] Write `app/chaos/middleware.py` via `_write_chaos_middleware()`:
  - [ ] `_PASS_THROUGH` frozenset with 4 paths
  - [ ] `ChaosMiddleware(BaseHTTPMiddleware)` with `dispatch()` method
  - [ ] Early return if `not engine.is_enabled()` or `path in _PASS_THROUGH`
  - [ ] Instantiate and call injectors in order: latency → error → timeout

### 15.4 Routes

- [ ] Write `app/api/routes/chaos.py` via `_write_chaos_routes()` (only if `routes_dir.exists()`):
  - [ ] `router = APIRouter(prefix="/chaos", tags=["chaos"])`
  - [ ] `POST /enable` — route-level production guard (403), then `engine.enable()`
  - [ ] `POST /disable` — `engine.disable()`
  - [ ] `GET /status` — `engine.status()`

### 15.5 Config and main.py patches

- [ ] Patch `app/core/config.py` via `_patch_config()`:
  - [ ] Skip if `"CHAOS_ENABLED"` already in file
  - [ ] Inject 4 fields with 4-space indent
  - [ ] Anchor insertion at `settings = Settings()` or append
- [ ] Patch `app/main.py` via `_patch_main()` (only if file exists):
  - [ ] Skip if `"ChaosMiddleware"` already in file
  - [ ] Inject import lines after `from fastapi import FastAPI`
  - [ ] Append middleware and router registration

### 15.6 Validation and result construction

- [ ] Loop over `files_created`: `ast.parse(path.read_text())` for all `.py` files — return error on `SyntaxError`
- [ ] Return `ToolResult` with `status="success"`, `files_created`, `files_modified`, `notes` (5 items), `next_steps` (7 items), `execution_time_ms`

---

## 16. Documentation Output

### 16.1 Success (fresh project)

```json
{
  "status": "success",
  "files_created": [
    "/project/app/chaos/__init__.py",
    "/project/app/chaos/injectors.py",
    "/project/app/chaos/middleware.py",
    "/project/app/api/routes/chaos.py"
  ],
  "files_modified": ["/project/app/core/config.py"],
  "notes": [
    "Chaos testing added: LatencyInjector, ErrorInjector, TimeoutInjector.",
    "PRODUCTION GUARD: chaos is physically blocked when ENVIRONMENT=production.",
    "ChaosMiddleware only activates when CHAOS_ENABLED=true AND not production.",
    "Endpoints: POST /chaos/enable, POST /chaos/disable, GET /chaos/status.",
    "Config: CHAOS_ENABLED (default false), CHAOS_LATENCY_MS, CHAOS_ERROR_RATE."
  ],
  "next_steps": [
    "Set CHAOS_ENABLED=true in .env for dev/staging ONLY.",
    "Set CHAOS_LATENCY_MS=200 to inject 200ms latency.",
    "Set CHAOS_ERROR_RATE=0.1 for 10% random 500 errors.",
    "Set CHAOS_TIMEOUT_RATE=0.05 for 5% request timeouts.",
    "POST /chaos/enable to activate (blocked in production).",
    "POST /chaos/disable to deactivate.",
    "Wire ChaosMiddleware into app.add_middleware() in main.py."
  ],
  "execution_time_ms": 91
}
```

### 16.2 No-op (already installed)

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "ChaosEngine already present — chaos testing already enabled, skipped."
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
    "[dry_run] Would create app/chaos/__init__.py, injectors.py, middleware.py, and app/api/routes/chaos.py."
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
