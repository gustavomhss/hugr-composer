---
spec_id: "TOOL-097"
tool_name: "add_bulkhead_isolation"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-BH-01"
  - "INV-BH-02"
  - "INV-BH-03"
  - "INV-BH-04"
  - "INV-BH-05"
  - "INV-BH-06"
  - "INV-BH-07"
  - "INV-BH-08"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-N-1"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-23"
  - "T-24"
  - "T-25"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-097: add_bulkhead_isolation

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_bulkhead_isolation` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium-High |
| Dependencies | FastAPI, pydantic-settings |
| Signature | `add_bulkhead_isolation(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_bulkhead_isolation", "description": "Add bulkhead isolation with per-pool concurrency limits and 503 backpressure for FastAPI services.", "tags": ["extend", "infrastructure"], "entry": "add_bulkhead_isolation"}` |
| Files created (typical) | 6 — `app/resilience/__init__.py`, `app/resilience/bulkhead.py`, `app/resilience/pool_config.py`, `app/resilience/bulkhead_status.py`, `app/middleware/bulkhead.py`, `app/api/routes/bulkhead_status.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_bulkhead_isolation` tool installs pool-based concurrency isolation into a FastAPI project, preventing a traffic surge in one route category from consuming all available coroutine slots and starving other categories. The bulkhead pattern takes its name from ship construction: watertight compartments that confine flooding to one section and keep the rest of the hull intact. Without bulkheads, a sudden analytics burst consumes all `asyncio` event-loop concurrency; payment flows queue behind analytics traffic and time out. With bulkheads, payments get their own `asyncio.Semaphore(max=10)`, analytics get `Semaphore(max=20)`, and CRUD gets `Semaphore(max=50)`. When the analytics semaphore is exhausted, new analytics requests immediately receive `503 Service Unavailable` with `X-Bulkhead-Group: analytics` — they are not held in a queue consuming resources.

The generated `Bulkhead` class wraps an `asyncio.Semaphore` per named pool. `BulkheadConfig` is a `dataclass` with `__post_init__` validation that raises `ValueError` if any `limit < 1`. `_PoolState` is a private dataclass carrying the semaphore and its configured limit; its `active` and `available` properties introspect `semaphore._value` for real-time telemetry. `classify_route(path)` maps paths to pool names: `/api/v*/payment*` and `/checkout*` → `"payments"`; `/analytics*` and `/reporting*` → `"analytics"`; everything else → `"crud"`. `BulkheadMiddleware` calls `classify_route`, acquires the semaphore via `Bulkhead.acquire(group)`, and returns `503 {"detail": "Bulkhead full"}` with `X-Bulkhead-Group: <group>` on `BulkheadFullError`. `GET /resilience/bulkheads` returns per-group `{"active", "max", "available"}` for ops dashboards. The `get_bulkhead()` factory creates a process-wide singleton from `settings.BULKHEAD_*` config values.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget; measured via `execution_time_ms` |
| Files created | ≥ 5 | bulkhead, pool_config, bulkhead_status, middleware, route (CC-04) |
| Files modified | ≥ 1 | Config patch (CC-05) |
| Max function LOC | ≤ 50 | AST walk enforced (CC-07) |
| Semaphore acquire decision | < 0.1 ms | In-process `asyncio.Semaphore`; no I/O |
| `503` response latency | < 1 ms | Short-circuit before any handler logic |
| `/resilience/bulkheads` response | < 5 ms | In-process dict lookup over bounded pool map |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   └── core/
│       └── config.py   # No BULKHEAD_* fields
```

A sudden surge of 500 analytics requests consumes all `asyncio` coroutine slots. Payment flows queue behind analytics traffic and time out. The service degrades uniformly.

### 4.2 Bulkhead (asyncio.Semaphore isolation): AFTER

```python
# app/resilience/bulkhead.py
"""Per-pool concurrency isolation via asyncio.Semaphore."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


class BulkheadFullError(Exception):
    """Raised when a bulkhead pool is at capacity."""


@dataclass
class _PoolState:
    semaphore: asyncio.Semaphore
    limit: int

    @property
    def active(self) -> int:
        return self.limit - self.semaphore._value  # type: ignore[attr-defined]

    @property
    def available(self) -> int:
        return self.semaphore._value  # type: ignore[attr-defined]


class Bulkhead:
    """Isolation container holding named async semaphore pools."""

    def __init__(self, pools: dict[str, int]) -> None:
        self._pools: dict[str, _PoolState] = {
            name: _PoolState(asyncio.Semaphore(limit), limit)
            for name, limit in pools.items()
        }

    def acquire(self, group: str) -> asyncio.Semaphore:
        """Return semaphore context for group; raises BulkheadFullError if full."""
        state = self._pools.get(group)
        if state is None or state.semaphore._value == 0:  # type: ignore
            raise BulkheadFullError(f"Bulkhead pool '{group}' is full")
        return state.semaphore

    def status(self) -> dict[str, dict]:
        """Return per-pool active/max/available counts."""
        return {
            name: {"active": s.active, "max": s.limit, "available": s.available}
            for name, s in self._pools.items()
        }


_bulkhead: Bulkhead | None = None


def get_bulkhead() -> Bulkhead:
    """Return the process-wide Bulkhead singleton."""
    global _bulkhead
    if _bulkhead is None:
        from app.core.config import settings
        config = _make_config(settings)
        _bulkhead = Bulkhead(config.as_dict())
    return _bulkhead
```

### 4.3 BulkheadConfig dataclass: AFTER

```python
# app/resilience/pool_config.py
"""Configuration dataclass for Bulkhead pool limits."""
from dataclasses import dataclass


@dataclass
class BulkheadConfig:
    payments_max: int = 10
    crud_max: int = 50
    analytics_max: int = 20

    def __post_init__(self) -> None:
        for field, val in [
            ("payments_max", self.payments_max),
            ("crud_max", self.crud_max),
            ("analytics_max", self.analytics_max),
        ]:
            if val < 1:
                raise ValueError(
                    f"BulkheadConfig.{field} must be >= 1, got {val}"
                )

    def as_dict(self) -> dict[str, int]:
        return {
            "payments": self.payments_max,
            "crud": self.crud_max,
            "analytics": self.analytics_max,
        }
```

### 4.4 classify_route and BulkheadMiddleware: AFTER

```python
# app/middleware/bulkhead.py
"""ASGI middleware that enforces per-pool concurrency via bulkheads."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.resilience.bulkhead import BulkheadFullError, get_bulkhead


def classify_route(path: str) -> str:
    """Map a request path to a bulkhead pool name."""
    if "payment" in path or "checkout" in path:
        return "payments"
    if "analytics" in path or "reporting" in path:
        return "analytics"
    return "crud"


class BulkheadMiddleware(BaseHTTPMiddleware):
    """Enforce per-group concurrency limits; return 503 on exhaustion."""

    async def dispatch(self, request: Request, call_next):
        from app.core.config import settings
        if not getattr(settings, "BULKHEAD_ENABLED", True):
            return await call_next(request)

        group = classify_route(request.url.path)
        bulkhead = get_bulkhead()
        try:
            sem = bulkhead.acquire(group)
        except BulkheadFullError:
            return JSONResponse(
                status_code=503,
                content={"detail": "Bulkhead full"},
                headers={"X-Bulkhead-Group": group},
            )
        async with sem:
            return await call_next(request)
```

### 4.5 Status route: AFTER

```python
# app/api/routes/bulkhead_status.py
from fastapi import APIRouter
from app.resilience.bulkhead import get_bulkhead

router = APIRouter(prefix="/resilience", tags=["resilience"])


@router.get("/bulkheads")
async def bulkhead_status() -> dict:
    """Return per-pool concurrency stats for ops dashboards."""
    return get_bulkhead().status()
```

### 4.6 Config patch: AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- bulkhead settings — added by add_bulkhead_isolation tool ---
    BULKHEAD_ENABLED: bool = True
    BULKHEAD_PAYMENTS_MAX: int = 10
    BULKHEAD_CRUD_MAX: int = 50
    BULKHEAD_ANALYTICS_MAX: int = 20
```

### 4.7 Typical main.py registration (after install)

```python
# app/main.py — after install
from app.middleware.bulkhead import BulkheadMiddleware

app = FastAPI()
app.add_middleware(BulkheadMiddleware)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Fingerprint `"Bulkhead" in bulkhead.py` → `no_op` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` AST-parses** | `_assert_parses` on each created file |
| QS-4 | **No function exceeds 50 LOC** | AST walk assertion |
| QS-5 | **`asyncio.Semaphore` used for pool isolation** | Direct in `Bulkhead.__init__` |
| QS-6 | **`503 + X-Bulkhead-Group` header on full pool** | `BulkheadMiddleware` emits both on `BulkheadFullError` |
| QS-7 | **`BulkheadConfig.__post_init__` raises `ValueError` for `limit < 1`** | Validated in `__post_init__` loop |
| QS-8 | **Config fields 4-space indent inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-9 | **`execution_time_ms` positive on all return paths** | `_elapsed_ms(start)` on all branches |
| QS-10 | **Status route returns per-group active/max/available** | `GET /resilience/bulkheads` backed by `Bulkhead.status()` (CC-15) |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_bulkhead_isolation.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run returns `status="no_op"`, zero file ops | `r2.status == "no_op"` and both lists empty | T-02 |
| CC-03 | `dry_run=True` writes zero bytes | `before == after` dict over every `.py` | T-03 |
| CC-04 | ≥ 5 files created, all exist | `len(files_created) >= 5`; each path exists | T-04 |
| CC-05 | ≥ 1 file modified (config), exists | `len(files_modified) >= 1`; path exists | T-05 |
| CC-06 | All `.py` in `app/resilience/` and `app/middleware/` AST-parse | `ast.parse` loop | T-06 |
| CC-07 | No generated function > 50 LOC | AST walk `max_loc <= 50` | T-07 |
| CC-08 | `BULKHEAD_ENABLED` in config with 4-space indent | String scan + indent check | T-08 |
| CC-09 | `bulkhead.py` exists and contains `Bulkhead` | File exists + `"Bulkhead" in content` | T-09 |
| CC-10 | `asyncio.Semaphore` used in source | `"asyncio.Semaphore"` present | T-10 |
| CC-11 | `pool_config.py` contains `BulkheadConfig` | File exists + symbol | T-11 |
| CC-12 | Pool names `payments`, `crud`, `analytics` defined | All three strings in source | T-12 |
| CC-13 | `BulkheadMiddleware` in `app/middleware/bulkhead.py` | File + symbol | T-13 |
| CC-14 | `503` response on full pool | `"503"` in middleware source | T-14 |
| CC-15 | `bulkhead_status.py` + `GET /resilience/bulkheads` route | File exists + route pattern in source | T-15 |
| CC-16 | `BulkheadFullError` exception defined | Symbol in `bulkhead.py` | T-16 |
| CC-17 | `X-Bulkhead-Group` response header | `"X-Bulkhead-Group"` in middleware source | T-17 |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-23 |
| CC-N | `next_steps` mentions bulkhead guidance | Token in lowercased join | T-24 |
| CC-LAST | After two runs, all `.py` remain parseable | `ast.parse` after two invocations | T-25 |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_bulkhead_isolation.py`
- [ ] `Bulkhead` uses `asyncio.Semaphore` for each named pool
- [ ] `BulkheadFullError` raised and caught in middleware → `503 + X-Bulkhead-Group`
- [ ] `BulkheadConfig.__post_init__` validates `limit >= 1` with `ValueError`
- [ ] `GET /resilience/bulkheads` returns `{group: {active, max, available}}`
- [ ] `classify_route` routes `payments`, `analytics`, `crud` correctly
- [ ] Config fields with 4-space indent inside `class Settings`
- [ ] `execution_time_ms` positive on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-BH-01 | Tool ALWAYS idempotent on second invocation | `"Bulkhead" in bulkhead.py` → `no_op` | T-02, T-25 |
| INV-BH-02 | `dry_run=True` NEVER writes to disk | Early return | T-03 |
| INV-BH-03 | Every generated `.py` MUST parse as valid Python | `_assert_parses` loop | T-06, T-25 |
| INV-BH-04 | Full pool MUST return `503 + X-Bulkhead-Group` | Middleware `JSONResponse(503)` with header | T-14, T-17 |
| INV-BH-05 | `BulkheadConfig` MUST reject `limit < 1` | `__post_init__` `ValueError` | B-06 (behavior) |
| INV-BH-06 | `asyncio.Semaphore` MUST be used for isolation | Direct construction in `Bulkhead.__init__` | T-10 |
| INV-BH-07 | Config fields MUST be inside `class Settings` with 4-space indent | `_patch_config` anchor | T-08 |
| INV-BH-08 | `execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | T-23 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install bulkhead isolation into a clean FastAPI project**
- **As a** platform engineer preventing analytics from starving payment flows
- **I want** one tool call to add per-pool concurrency isolation
- **So that** a traffic surge in one route category cannot exhaust all coroutine slots
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_bulkhead_isolation(ToolInput(project_dir=...))`
- **Then:**
  - Returns `status="success"` (INV-BH-01)
  - `files_created >= 5` (CC-04), `files_modified >= 1` (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Idempotent CI re-run**
- **As a** CI job that re-applies tooling on every commit
- **I want** the tool to skip silently when already installed
- **Given:** `app/resilience/bulkhead.py` already contains `Bulkhead`
- **When:** Second invocation
- **Then:** `status="no_op"`, zero writes (INV-BH-01); verified by T-02, T-25

**US-03: Preview with dry_run**
- **As a** developer auditing a tool invocation
- **I want** to see what would change without touching files
- **Given:** Fresh fixture project
- **When:** `add_bulkhead_isolation(ToolInput(dry_run=True))`
- **Then:** `status="success"`; filesystem byte-identical (INV-BH-02); verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function ≤ 50 LOC
- **Given:** Tool emitted all bulkhead files
- **When:** AST walk over `app/`
- **Then:** `max_loc <= 50` (QS-4); verified by T-07

**US-05: Config binds from environment variables**
- **As an** ops engineer sizing pools per deployment
- **I want** `BULKHEAD_PAYMENTS_MAX=20` in `.env` to override the default
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` instantiates
- **Then:** `BULKHEAD_PAYMENTS_MAX` inside `class Settings` with 4-space indent (INV-BH-07)

### 9.2 Bulkhead behaviour (US-06 .. US-12)

**US-06: Analytics surge does not starve payments**
- **As a** checkout flow hitting `/api/v1/payments`
- **I want** my request to proceed even when all analytics slots are consumed
- **Given:** `analytics` pool at capacity (`available=0`)
- **When:** A payment request arrives (`classify_route` → `"payments"`)
- **Then:** Payment semaphore is available; request proceeds normally (INV-BH-06)

**US-07: Analytics request receives 503 when pool full**
- **As a** low-priority analytics client
- **I want** an explicit `503` when the analytics pool is exhausted
- **So that** I can back off instead of waiting indefinitely
- **Given:** All 20 analytics slots active
- **When:** New analytics request arrives
- **Then:** `BulkheadMiddleware` catches `BulkheadFullError` → `503 {"detail": "Bulkhead full"}` with `X-Bulkhead-Group: analytics` (INV-BH-04)

**US-08: X-Bulkhead-Group identifies the saturated pool**
- **As a** client receiving 503
- **I want** the `X-Bulkhead-Group` header to identify which pool was full
- **So that** my retry logic can target a different endpoint or wait
- **Given:** `crud` pool is full
- **When:** 503 returned
- **Then:** `X-Bulkhead-Group: crud` header present (CC-17)

**US-09: Status endpoint for ops dashboard**
- **As an** SRE running a live traffic dashboard
- **I want** `GET /resilience/bulkheads` to show per-pool slot counts
- **Given:** 3 of 10 payments slots active, 15 of 20 analytics active
- **When:** `GET /resilience/bulkheads`
- **Then:** `{"payments": {"active": 3, "max": 10, "available": 7}, "analytics": {"active": 15, "max": 20, "available": 5}, "crud": {...}}` (CC-15)

**US-10: Config validation catches invalid pool limit**
- **As a** developer who accidentally set `BULKHEAD_PAYMENTS_MAX=0`
- **I want** a `ValueError` at startup, not a silent semaphore with max=0
- **Given:** `BulkheadConfig(payments_max=0)`
- **When:** `__post_init__` runs
- **Then:** `ValueError: BulkheadConfig.payments_max must be >= 1, got 0` (INV-BH-05)

**US-11: classify_route maps paths correctly**
- **As a** developer extending the route classifier
- **I want** the default mappings to be sensible and well-tested
- **Given:** Various paths
- **When:** `classify_route(path)` called
- **Then:**
  - `/api/v1/payments/123` → `"payments"` (contains "payment")
  - `/analytics/events` → `"analytics"` (starts with "/analytics")
  - `/api/v1/users` → `"crud"` (no payment/analytics match)
  - `/checkout` → `"payments"` (contains "checkout")

**US-12: BULKHEAD_ENABLED=false disables isolation**
- **As an** ops engineer during incident investigation
- **I want** to disable bulkhead isolation without redeploying
- **Given:** `settings.BULKHEAD_ENABLED == False`
- **When:** Middleware processes any request
- **Then:** Passes all requests through without semaphore check

### 9.3 Semaphore mechanics (US-13 .. US-17)

**US-13: Semaphore is released after request completes**
- **As a** service processing sequential requests through the same pool
- **I want** each request to release the semaphore on completion
- **Given:** `async with sem:` used in middleware
- **When:** Request handler returns
- **Then:** Semaphore `_value` increments back; next request can acquire

**US-14: Semaphore is released on handler exception**
- **As a** service where handlers sometimes raise unhandled exceptions
- **I want** the semaphore released even if the handler throws
- **Given:** Handler raises `ValueError`
- **When:** `async with sem:` context exits on exception
- **Then:** Context manager guarantees release; `available` count recovers

**US-15: Process-wide singleton**
- **As a** service with multiple concurrent requests
- **I want** all request handlers to share the same `Bulkhead` instance
- **Given:** `get_bulkhead()` called from middleware on every request
- **When:** Multiple concurrent calls
- **Then:** All share the same singleton with the same semaphores — pool limits are global

**US-16: Fresh singleton on process restart**
- **As an** ops engineer restarting the service
- **I want** pool counters to reset to zero active on restart
- **Given:** `_bulkhead: Bulkhead | None = None` at module scope
- **When:** New process starts
- **Then:** New `Bulkhead` created with fresh semaphores; `active=0` for all pools

**US-17: Custom pool name falls through to crud**
- **As a** developer adding a new route category not yet in `classify_route`
- **I want** new paths to default to the `crud` pool
- **So that** unknown paths are still throttled, not exempted
- **Given:** `classify_route("/api/v1/search")` — no "payment" or "analytics"
- **When:** Called
- **Then:** Returns `"crud"` (default branch)

### 9.4 Code quality (US-18 .. US-22)

**US-18: No optional SDKs at module top-level**
- **As a** dependency auditor
- **I want** only `asyncio`, `dataclasses`, and `starlette` imports at module scope
- **Given:** `bulkhead.py`, `pool_config.py`, `middleware/bulkhead.py`
- **When:** Modules imported
- **Then:** No `numpy`, `scipy`, or other optional deps

**US-19: Second run does not corrupt any file**
- **Given:** First run completed successfully
- **When:** Second run executes
- **Then:** `status="no_op"`; all `.py` parse (CC-LAST)

**US-20: Tool reports execution time on all paths**
- **Given:** Any invocation path
- **When:** `result.execution_time_ms` read
- **Then:** Positive integer (CC-N-1)

**US-21: next_steps guides operator**
- **Given:** Success return path
- **When:** `result.next_steps` inspected
- **Then:** Contains `"BULKHEAD_ENABLED"` and middleware registration guidance (CC-N)

**US-22: Error on missing project_dir**
- **Given:** `inp.project_dir` points to missing directory
- **When:** Tool called
- **Then:** `status="error"` with `execution_time_ms > 0`

### 9.5 Operator and integration (US-23 .. US-25)

**US-23: Register middleware in main.py**
- **As a** developer following next_steps
- **I want** `app.add_middleware(BulkheadMiddleware)` to be the only required change
- **Given:** `app/middleware/bulkhead.py` generated
- **When:** Added to `app/main.py`
- **Then:** All requests route through bulkhead isolation

**US-24: Combine with load shedding**
- **As a** resilience architect
- **I want** load shedding at the front (system p99) and bulkheads per pool
- **Given:** Both middlewares registered: load shedding FIRST, then bulkhead
- **When:** Overload hits
- **Then:** Load shedding rejects `LOW` traffic first; if `HIGH` traffic saturates a bulkhead pool, `503` is returned at the pool level

**US-25: Pool sizing driven by profiling**
- **As an** SRE sizing the pools
- **I want** `GET /resilience/bulkheads` to show real-time utilisation during load test
- **Given:** Load test running at 2× expected traffic
- **When:** Dashboard polls `/resilience/bulkheads` every second
- **Then:** `active/max` ratio shows which pool is the bottleneck; ops adjusts `BULKHEAD_*_MAX` accordingly

---

## 10. Test Plan

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `bh_t01` | `add_bulkhead_isolation(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `bh_t02`; run once | Run second time | `r2.status == "no_op"`; empty lists (CC-02) |
| T-03 | `test_dry_run` | Fixture `bh_t03`; snapshot `.py` | `dry_run=True` | `status == "success"`; byte-identical fs (CC-03) |
| T-04 | `test_files_created_count` | Fixture `bh_t04` | Run tool | `len(files_created) >= 5`; all exist (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `bh_t05` | Run tool | `len(files_modified) >= 1`; all exist (CC-05) |

### 10.2 Category B — Code quality (T-06 .. T-08)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture; run tool | `ast.parse` all `.py` in resilience + middleware + routes | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture; run tool | AST walk `app/` for functions | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture; run tool | Read `config.py` | `BULKHEAD_ENABLED` present; 4-space indent (CC-08) |

### 10.3 Category C — Domain modules (T-09 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-09 | `test_bulkhead_created` | Fixture; run tool | Read `bulkhead.py` | `"Bulkhead"` in content (CC-09) |
| T-10 | `test_semaphore_used` | Fixture; run tool | Read `bulkhead.py` | `"asyncio.Semaphore"` present (CC-10) |
| T-11 | `test_pool_config_created` | Fixture; run tool | Read `pool_config.py` | `"BulkheadConfig"` present (CC-11) |
| T-12 | `test_pool_names` | Fixture; run tool | Read bulkhead source | `"payments"`, `"crud"`, `"analytics"` all present (CC-12) |
| T-13 | `test_middleware_created` | Fixture; run tool | Read `middleware/bulkhead.py` | `"BulkheadMiddleware"` present (CC-13) |
| T-14 | `test_503_on_full_pool` | Fixture; run tool | Read middleware | `"503"` in content (CC-14) |
| T-15 | `test_status_route` | Fixture; run tool | Read `bulkhead_status.py` + route | File + `/resilience/bulkheads` path (CC-15) |
| T-16 | `test_bulkhead_full_error` | Fixture; run tool | Read `bulkhead.py` | `"BulkheadFullError"` present (CC-16) |
| T-17 | `test_x_bulkhead_group_header` | Fixture; run tool | Read middleware | `"X-Bulkhead-Group"` present (CC-17) |

### 10.4 Category D — Meta (T-23 .. T-25)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-23 | `test_execution_time_recorded` | Fixture; run tool | Read `result.execution_time_ms` | `> 0` (CC-N-1) |
| T-24 | `test_next_steps_present` | Fixture; run tool | Inspect `result.next_steps` | Contains bulkhead guidance (CC-N) |
| T-25 | `test_idempotent_project_still_parses` | Fixture; run twice | `ast.parse` all `.py` | No `SyntaxError` (CC-LAST) |

### 10.5 Behavior tests (B-01 .. B-10)

| # | Test | Assertion |
|---|------|-----------|
| B-01 | `test_b01_healthz_returns_200` | `/healthz` → 200 (base liveness) |
| B-02 | `test_b02_bulkhead_full_error_at_capacity` | `BulkheadFullError` when pool at `max` |
| B-03 | `test_b03_classify_route_payments` | `/api/v1/payments/123` → `"payments"` |
| B-04 | `test_b04_classify_route_analytics` | `/analytics/events` → `"analytics"` |
| B-05 | `test_b05_classify_route_default` | `/api/v1/users` → `"crud"` |
| B-06 | `test_b06_pool_config_rejects_zero` | `BulkheadConfig(payments_max=0)` → `ValueError` |
| B-07 | `test_b07_status_dict_shape` | `Bulkhead.status()` keys: `active`, `max`, `available` |
| B-08 | `test_b08_all_functions_under_50_loc` | All functions ≤ 50 LOC |
| B-09 | `test_b09_config_4_space_indent` | `BULKHEAD_ENABLED` line starts with 4 spaces |
| B-10 | `test_b10_get_bulkhead_singleton` | `get_bulkhead()` returns same instance twice |

### 10.6 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_bulkhead_isolation.py -v
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_bulkhead_isolation_behavior.py -v
```

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_load_shedding` (TOOL-095) | Yes | ✅ Compatible — load shedding FIRST | Load shedding rejects at system p99 before bulkhead semaphore is checked |
| `add_adaptive_timeouts` (TOOL-096) | No | ✅ Compatible | Timeouts bound duration; bulkheads bound concurrency — orthogonal |
| `add_retry_budget` (TOOL-098) | No | ✅ Compatible | Retry budget prevents retry amplification from backed-off bulkhead pools |
| `add_chaos_testing` (TOOL-099) | No | ✅ Compatible | Chaos can simulate pool saturation to validate `503` responses |
| `add_graceful_shutdown` (TOOL-100) | Yes | ✅ Compatible — bulkhead after graceful shutdown | Draining check runs before bulkhead; draining requests still acquire semaphores |
| `add_circuit_breaker` | No | ✅ Compatible | Circuit breaker trips on error rate; bulkhead full is a separate 503 category |
| `add_rate_limiting` | No | ⚠️ Caveat | Rate limiting per user; bulkhead per pool — do not substitute |
| `add_anomaly_detector` (TOOL-102) | No | ✅ Compatible | Anomaly detector alerts on pool saturation patterns; bulkhead enforces hard limits |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Worker enqueue endpoints can be classified as `crud`; workers themselves bypass ASGI middleware |
| `add_multi_tenancy` | No | ⚠️ Caveat | Extend `classify_route` to account for tenant admin paths if needed |
| `add_rbac` | No | ✅ Compatible | RBAC is in-handler; bulkhead is in-middleware — no conflict |
| `add_event_driven` | No | ✅ Compatible | Event publishing is quick I/O; use `crud` pool |
| `add_sse` | No | ⚠️ Caveat | SSE connections are long-lived; holding a semaphore for minutes depletes the pool — classify SSE as a separate pool or exclude from bulkhead |
| `add_webhook_receiver` | No | ✅ Compatible | Incoming webhooks classified as `crud` by default; can be reassigned |
| `add_sqladmin` | No | ✅ Compatible | Admin routes classified as `crud`; admin traffic does not starve payments |

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- app/core/config.py

rm -f app/resilience/bulkhead.py \
      app/resilience/pool_config.py \
      app/resilience/bulkhead_status.py \
      app/middleware/bulkhead.py \
      app/api/routes/bulkhead_status.py
```

### 12.2 Middleware removal from main.py

```python
# Remove from app/main.py:
# app.add_middleware(BulkheadMiddleware)
```

### 12.3 Failure mode: partial write

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

### 12.4 Emergency: disable without rollback

Set `BULKHEAD_ENABLED=false` in `.env` and restart. Middleware checks the flag and passes all requests through.

### 12.5 Uninstall validator

```bash
test ! -f app/resilience/bulkhead.py \
  || (echo "bulkhead.py still present" && exit 1)
grep -q "BULKHEAD_ENABLED" app/core/config.py \
  && echo "config still patched" && exit 1
grep -q "BulkheadMiddleware" app/main.py \
  && echo "middleware still registered — remove manually" && exit 1
echo "rollback verified"
```

### 12.6 Re-install after rollback

After rollback the fingerprint is gone:

```python
result = add_bulkhead_isolation(ToolInput(project_dir="..."))
assert result.status == "success"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | `bulkhead.py` already contains `Bulkhead` | `status="no_op"` — zero file writes (INV-BH-01) |
| EC-02 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; no file touched (INV-BH-02) |
| EC-03 | `BULKHEAD_PAYMENTS_MAX=0` in env | `BulkheadConfig.__post_init__` raises `ValueError` at `get_bulkhead()` call time |
| EC-04 | Path not matching any category | Falls through to `"crud"` pool (US-17) |
| EC-05 | `BULKHEAD_ENABLED=false` in env | Middleware passes all requests unconditionally |
| EC-06 | `app/core/config.py` missing `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | Fallback before `settings = Settings()` or EOF |
| EC-07 | `app/core/config.py` already contains `BULKHEAD_ENABLED` | `_patch_config` early-returns; no duplicate block |
| EC-08 | `app/middleware/` directory missing | Tool creates it via `mkdir(parents=True, exist_ok=True)` |
| EC-09 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-10 | Tool runs twice back-to-back in CI | Second run returns `no_op`; project remains parseable (T-25) |
| EC-11 | `asyncio.Semaphore(0)` — would immediately block all | `BulkheadConfig.__post_init__` rejects limit=0 before this can happen |
| EC-12 | SSE connection holds semaphore for minutes | Pool depleted; new SSE requests get 503 — caller should classify SSE as its own pool |
| EC-13 | `classify_route` receives empty path `""` | No match → returns `"crud"` |
| EC-14 | Handler exception after semaphore acquired | `async with sem:` guarantees release on exception |
| EC-15 | Very high `BULKHEAD_CRUD_MAX` (e.g. 10000) | `asyncio.Semaphore(10000)` is valid; `_value` starts at 10000 |
| EC-16 | Generated file fails `ast.parse` | `_assert_parses` raises `SyntaxError`; partial files remain — use rollback 12.3 |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 20 Completeness Criteria verified via `test_add_bulkhead_isolation.py` passing
2. ✅ Test report shows 0 failed across structural and behavior test files
3. ✅ Tool execution time < 5 s on reference hardware
4. ✅ Second invocation returns `status="no_op"` (INV-BH-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-BH-02)
6. ✅ Every generated `.py` AST-parses cleanly (INV-BH-03)
7. ✅ No generated function exceeds 50 LOC (QS-4)
8. ✅ `asyncio.Semaphore` used for pool isolation (INV-BH-06)
9. ✅ Full pool returns `503 + X-Bulkhead-Group` (INV-BH-04)
10. ✅ `BulkheadConfig.__post_init__` rejects `limit < 1` with `ValueError` (INV-BH-05)
11. ✅ `GET /resilience/bulkheads` returns active/max/available per group (CC-15)
12. ✅ `classify_route` maps payments/analytics/crud correctly (CC-12)
13. ✅ `BULKHEAD_*` config fields inside `class Settings` with 4-space indent (INV-BH-07)
14. ✅ `execution_time_ms > 0` on every return path (INV-BH-08)
15. ✅ Behavior tests B-01..B-10 pass against real module imports

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` passes
- [ ] `app/resilience/bulkhead.py` does NOT contain `"Bulkhead"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return early

### 15.2 Resilience package

- [ ] `mkdir -p app/resilience`
- [ ] Write `app/resilience/__init__.py` (empty or minimal)
- [ ] Write `app/resilience/bulkhead.py` via `_write_bulkhead`:
  - [ ] `BulkheadFullError` exception class
  - [ ] `_PoolState` dataclass with `active` and `available` properties
  - [ ] `Bulkhead` class with `__init__`, `acquire`, `status`
  - [ ] `get_bulkhead()` singleton factory
- [ ] Write `app/resilience/pool_config.py` via `_write_pool_config`:
  - [ ] `BulkheadConfig` dataclass with `payments_max`, `crud_max`, `analytics_max`
  - [ ] `__post_init__` validates each `limit >= 1`
  - [ ] `as_dict()` returns `{"payments": payments_max, "crud": ..., "analytics": ...}`
- [ ] Write `app/resilience/bulkhead_status.py` (optional helper module)

### 15.3 Middleware

- [ ] `mkdir -p app/middleware` (if missing)
- [ ] Write `app/middleware/bulkhead.py` via `_write_middleware`:
  - [ ] `classify_route(path)` → `"payments"` | `"analytics"` | `"crud"`
  - [ ] `BulkheadMiddleware(BaseHTTPMiddleware)` with `dispatch`
  - [ ] Early check `BULKHEAD_ENABLED`
  - [ ] `JSONResponse(status_code=503, ..., headers={"X-Bulkhead-Group": group})`
  - [ ] `async with sem:` context manager for acquired semaphore

### 15.4 Status route

- [ ] `mkdir -p app/api/routes` (if missing)
- [ ] Write `app/api/routes/bulkhead_status.py` with `GET /resilience/bulkheads`

### 15.5 Config patch

- [ ] Early-return if `"BULKHEAD_ENABLED" in src`
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] 4-space indent for all four fields
- [ ] `BULKHEAD_ENABLED: bool = True`
- [ ] `BULKHEAD_PAYMENTS_MAX: int = 10`
- [ ] `BULKHEAD_CRUD_MAX: int = 50`
- [ ] `BULKHEAD_ANALYTICS_MAX: int = 20`

### 15.6 Validation and result

- [ ] `_assert_parses` on all created `.py` files
- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` describe pool names, limits, middleware behaviour, status route
- [ ] `next_steps` include `BULKHEAD_ENABLED`, middleware registration, pool sizing guidance
- [ ] `execution_time_ms` set on all branches

### 15.7 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring describes the three pools and the ship bulkhead analogy

---

## 16. Documentation Output

Example `ToolResult` JSON (success path):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/resilience/__init__.py",
    "/tmp/fixture/app/resilience/bulkhead.py",
    "/tmp/fixture/app/resilience/pool_config.py",
    "/tmp/fixture/app/resilience/bulkhead_status.py",
    "/tmp/fixture/app/middleware/bulkhead.py",
    "/tmp/fixture/app/api/routes/bulkhead_status.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py"
  ],
  "notes": [
    "Bulkhead isolation added: 3 pools (payments=10, crud=50, analytics=20).",
    "BulkheadMiddleware returns 503 + X-Bulkhead-Group when pool is full.",
    "classify_route maps: payment/checkout paths → payments; analytics/reporting → analytics; rest → crud.",
    "Status: GET /resilience/bulkheads returns active/max/available per pool."
  ],
  "next_steps": [
    "Set BULKHEAD_ENABLED=true in .env.",
    "Register BulkheadMiddleware in app/main.py: app.add_middleware(BulkheadMiddleware).",
    "Tune BULKHEAD_PAYMENTS_MAX / CRUD_MAX / ANALYTICS_MAX for your concurrency profile.",
    "Monitor GET /resilience/bulkheads during load test to identify bottleneck pools."
  ],
  "execution_time_ms": 95
}
```

Example `no_op` return:

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "Bulkhead already present — bulkhead isolation already installed, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 3
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/resilience/bulkhead.py (Bulkhead, BulkheadFullError, _PoolState),",
    "         app/resilience/pool_config.py (BulkheadConfig, __post_init__ validation),",
    "         app/middleware/bulkhead.py (BulkheadMiddleware, classify_route),",
    "         app/api/routes/bulkhead_status.py (GET /resilience/bulkheads).",
    "         Config: BULKHEAD_ENABLED, PAYMENTS_MAX=10, CRUD_MAX=50, ANALYTICS_MAX=20.",
    "[dry_run] No files written."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 1
}
```

Example `error` return:

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - CONFIG_SETTINGS: app/core/config.py missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 2
}
```

---
