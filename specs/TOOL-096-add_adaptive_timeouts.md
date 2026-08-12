---
spec_id: "TOOL-096"
tool_name: "add_adaptive_timeouts"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-AT-01"
  - "INV-AT-02"
  - "INV-AT-03"
  - "INV-AT-04"
  - "INV-AT-05"
  - "INV-AT-06"
  - "INV-AT-07"
  - "INV-AT-08"
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
  - "QS-11"
  - "QS-12"
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
# TOOL-096: add_adaptive_timeouts

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_adaptive_timeouts` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, pydantic-settings |
| Signature | `add_adaptive_timeouts(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_adaptive_timeouts", "description": "Add self-adjusting timeouts that learn from observed downstream latency, auto-calibrating to p99 * 1.5 with configurable floor and ceiling.", "tags": ["extend", "infrastructure"], "entry": "add_adaptive_timeouts"}` |
| Files created (typical) | 3 — `app/resilience/adaptive_timeout.py`, `app/resilience/timeout_registry.py`, `app/resilience/__init__.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_adaptive_timeouts` tool installs adaptive per-dependency timeout management into a FastAPI project. Hard-coded timeouts are the first wrong move in distributed systems engineering: too short and you abort calls during genuine load spikes; too long and a slow dependency holds worker slots until the service exhausts its thread pool. The universal compromise — "just set 5 seconds" — is wrong for fast dependencies (where 5 s means a broken dependency goes undetected for far too long) and wrong for slow ones (where 5 s cuts off legitimate long-running queries). The only correct answer is to track observed latency and derive the timeout from real data.

The generated `AdaptiveTimeout` class maintains an in-process sliding window of up to `ADAPTIVE_TIMEOUT_WINDOW_SIZE` (default 100) latency samples per dependency. It computes p50, p95, and p99 percentiles via `_percentile(p)` using `sorted(list(deque))`. The active timeout is `p99 * 1.5`, clamped between `ADAPTIVE_TIMEOUT_FLOOR_MS` (100 ms) and `ADAPTIVE_TIMEOUT_CEILING_MS` (10 000 ms). The 1.5× headroom handles legitimate p99.9 spikes without permanently widening the timeout to match pathological outliers. The floor prevents setting a timeout so tight that even healthy fast calls are cancelled on the first burst. The ceiling prevents a degraded dependency from dragging the timeout up to infinity — a dependency in prolonged distress should trigger a circuit breaker, not a perpetually-expanding timeout.

The `@adaptive_timeout("dependency_name")` decorator wraps any `async def` coroutine with `asyncio.wait_for(coro, timeout=tracker.current_timeout_s())`. If the coroutine completes within the timeout, its observed latency is recorded into the tracker via `tracker.record(elapsed_ms)` so the next call benefits from the updated distribution. If `wait_for` raises `asyncio.TimeoutError`, the error propagates to the caller — the decorator never swallows it. This design is intentional: the caller decides how to handle timeout (raise HTTP 504, trip circuit breaker, or queue a retry). Recording happens only on success; timeout events are excluded from the distribution so a slow outlier does not permanently widen the window.

The `TimeoutRegistry` is a per-process singleton (`get_timeout_registry()`) that maps dependency names to their `AdaptiveTimeout` instances. It provides `get_or_create(name)` for lazy instantiation and `all_stats()` to expose the full per-dependency state — `{p50, p95, p99, current_timeout_s, sample_count}` — to an ops dashboard route. A `TYPE_CHECKING` guard in `timeout_registry.py` prevents the circular import that would occur if `AdaptiveTimeout` imported the registry at module load time: the guard wraps `from app.resilience.adaptive_timeout import AdaptiveTimeout` in `if TYPE_CHECKING:` so the type annotation is available at static analysis time but the import never executes at runtime.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget; measured via `execution_time_ms` in `ToolResult` |
| Files created | ≥ 3 | `adaptive_timeout.py`, `timeout_registry.py`, `__init__.py` (CC-04) |
| Files modified | ≥ 1 | Config patch with `ADAPTIVE_TIMEOUT_*` fields (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each function stays auditable; AST walk enforced (CC-07) |
| Percentile computation overhead | < 0.1 ms | `sorted(list(deque))` bounded at 100 samples |
| `asyncio.wait_for` overhead | < 0.01 ms | Single coroutine wrap; no thread spawn |
| `get_stats()` response time | < 1 ms | In-process dict lookup over bounded window |
| `get_timeout_registry()` first call | < 0.1 ms | Simple `_registry is None` guard + constructor |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # No ADAPTIVE_TIMEOUT_* fields
│   └── api/
│       └── routes/
│           └── orders.py    # Outbound calls with hardcoded 5s timeout
└── requirements.txt
```

All outbound calls use static timeouts (often omitted entirely). A single slow database query during a load spike can cascade into connection pool exhaustion because every request waits the full hard-coded maximum — 5 000 requests × 5 s = 25 000 slot-seconds per second, which is infinite blocking. When the DB recovers, the timeout is still 5 s even though healthy latency is 20 ms.

### 4.2 AdaptiveTimeout (sliding window, p99 × 1.5): AFTER

```python
# app/resilience/adaptive_timeout.py
"""Adaptive per-dependency timeout tracker using p99 latency."""
from __future__ import annotations

import asyncio
import functools
import time
from collections import deque
from typing import Any, Callable

from app.core.config import settings


class AdaptiveTimeout:
    """Tracks observed latency and computes adaptive timeout = p99 * 1.5."""

    def __init__(
        self,
        floor_ms: float = 100.0,
        ceiling_ms: float = 10000.0,
        window_size: int = 100,
    ) -> None:
        self._floor_ms = floor_ms
        self._ceiling_ms = ceiling_ms
        self._samples: deque[float] = deque(maxlen=window_size)

    def record(self, latency_ms: float) -> None:
        """Record a completed call latency sample (success only)."""
        self._samples.append(latency_ms)

    def _percentile(self, p: float) -> float:
        sorted_s = sorted(self._samples)
        idx = max(0, int(p * len(sorted_s)) - 1)
        return sorted_s[idx]

    def current_timeout_s(self) -> float:
        """Return the current adaptive timeout in seconds.

        Falls back to ceiling when fewer than 10 samples are available
        (safe-open: do not abort calls before enough data is collected).
        """
        if len(self._samples) < 10:
            return self._ceiling_ms / 1000.0
        p99 = self._percentile(0.99)
        raw = p99 * 1.5
        clamped = max(self._floor_ms, min(self._ceiling_ms, raw))
        return clamped / 1000.0

    def get_stats(self) -> dict[str, Any]:
        """Return current percentile stats and active timeout."""
        if len(self._samples) < 10:
            return {
                "sample_count": len(self._samples),
                "current_timeout_s": self.current_timeout_s(),
            }
        return {
            "p50": self._percentile(0.50),
            "p95": self._percentile(0.95),
            "p99": self._percentile(0.99),
            "current_timeout_s": self.current_timeout_s(),
            "sample_count": len(self._samples),
        }
```

### 4.3 @adaptive_timeout decorator: AFTER

```python
def adaptive_timeout(dep: str, registry: "TimeoutRegistry | None" = None):
    """Wrap an async function with asyncio.wait_for using adaptive timeout.

    Usage::

        @adaptive_timeout("stripe_api")
        async def charge_card(amount: int) -> dict:
            ...

    On success, the observed latency is recorded to the tracker.
    On timeout, asyncio.TimeoutError propagates to the caller unchanged.

    Args:
        dep: Dependency name key in TimeoutRegistry.
        registry: Optional explicit registry; uses singleton if None.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            from app.resilience.timeout_registry import get_timeout_registry
            reg = registry or get_timeout_registry()
            tracker = reg.get_or_create(dep)
            start = time.monotonic()
            result = await asyncio.wait_for(
                fn(*args, **kwargs), timeout=tracker.current_timeout_s()
            )
            tracker.record((time.monotonic() - start) * 1000)
            return result
        return wrapper
    return decorator
```

### 4.4 TimeoutRegistry (TYPE_CHECKING guard): AFTER

```python
# app/resilience/timeout_registry.py
"""Process-wide registry of AdaptiveTimeout instances per dependency."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.resilience.adaptive_timeout import AdaptiveTimeout

_registry: "TimeoutRegistry | None" = None


class TimeoutRegistry:
    """Maps dependency names to AdaptiveTimeout trackers."""

    def __init__(self) -> None:
        self._trackers: dict[str, "AdaptiveTimeout"] = {}

    def get_or_create(self, name: str) -> "AdaptiveTimeout":
        """Return existing tracker or create a new one for name."""
        if name not in self._trackers:
            from app.resilience.adaptive_timeout import AdaptiveTimeout
            self._trackers[name] = AdaptiveTimeout()
        return self._trackers[name]

    def all_stats(self) -> dict[str, dict[str, Any]]:
        """Return per-dependency stats dict for ops dashboards."""
        return {k: v.get_stats() for k, v in self._trackers.items()}


def get_timeout_registry() -> TimeoutRegistry:
    """Return the process-wide TimeoutRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = TimeoutRegistry()
    return _registry
```

### 4.5 Config patch: AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- adaptive timeout settings — added by add_adaptive_timeouts tool ---
    ADAPTIVE_TIMEOUT_ENABLED: bool = True
    ADAPTIVE_TIMEOUT_FLOOR_MS: float = 100.0
    ADAPTIVE_TIMEOUT_CEILING_MS: float = 10000.0
    ADAPTIVE_TIMEOUT_WINDOW_SIZE: int = 100
```

### 4.6 Ops dashboard route (typical caller usage after install)

```python
# app/api/routes/resilience.py  (manual addition, suggested in next_steps)
from fastapi import APIRouter
from app.resilience.timeout_registry import get_timeout_registry

router = APIRouter(prefix="/resilience", tags=["resilience"])


@router.get("/timeouts")
async def get_timeout_stats() -> dict:
    """Return per-dependency adaptive timeout stats."""
    return get_timeout_registry().all_stats()
```

### 4.7 Decorating an existing route dependency

```python
# Before: hardcoded 5-second timeout
import httpx

async def fetch_product(product_id: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"/products/{product_id}")
        return resp.json()

# After: adaptive timeout
from app.resilience.adaptive_timeout import adaptive_timeout

@adaptive_timeout("product_api")
async def fetch_product(product_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"/products/{product_id}")
        return resp.json()
# Timeout auto-adjusts to p99 * 1.5; floor=100ms; ceiling=10s
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Fingerprint `"AdaptiveTimeout" in adaptive_timeout.py` → `no_op` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` AST-parses** | `_assert_parses` on each created file |
| QS-4 | **No function exceeds 50 LOC** | AST walk assertion in test harness |
| QS-5 | **Timeout clamped between floor and ceiling** | `max(floor_ms, min(ceiling_ms, raw))` in `current_timeout_s` |
| QS-6 | **`asyncio.wait_for` wraps async calls** | Decorator uses `await asyncio.wait_for(fn(*args, **kwargs), ...)` |
| QS-7 | **`TYPE_CHECKING` guard prevents circular import** | `if TYPE_CHECKING: from app.resilience.adaptive_timeout import AdaptiveTimeout` |
| QS-8 | **Config fields inside `class Settings` with 4-space indent** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-9 | **`execution_time_ms` positive on all paths** | `_elapsed_ms(start)` on every return branch |
| QS-10 | **`get_stats()` exposes p50/p95/p99/current_timeout_s/sample_count** | Dict keys required by behavior test B-06 |
| QS-11 | **Record only on success — timeouts excluded** | `tracker.record(...)` called after `wait_for` returns; not in `except TimeoutError` |
| QS-12 | **Safe open on insufficient samples** | `current_timeout_s()` returns `ceiling_ms / 1000` when fewer than 10 samples |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_adaptive_timeouts.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 3 new files, all exist | `len(result.files_created) >= 3`; each path exists on disk | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 1 existing file (config) | `len(result.files_modified) >= 1`; path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` in `app/resilience/` AST-parses cleanly | `ast.parse` loop | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST walk `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `ADAPTIVE_TIMEOUT_ENABLED` in config with 4-space indent | String scan + indent check | T-08 (`test_config_fields_patched`) |
| CC-09 | `adaptive_timeout.py` contains `AdaptiveTimeout` | File exists + `"AdaptiveTimeout" in content` | T-09 (`test_adaptive_timeout_created`) |
| CC-10 | Percentiles p50/p95/p99 implemented | `"0.50"`, `"0.95"`, `"0.99"` in source | T-10 (`test_percentiles_implemented`) |
| CC-11 | Timeout multiplier = 1.5 | `"1.5"` in `adaptive_timeout.py` | T-11 (`test_multiplier_1_5`) |
| CC-12 | `ADAPTIVE_TIMEOUT_FLOOR_MS` and `ADAPTIVE_TIMEOUT_CEILING_MS` in config | Both keys present in `config.py` | T-12 (`test_floor_ceiling_config`) |
| CC-13 | `timeout_registry.py` contains `TimeoutRegistry` | File exists + `"TimeoutRegistry" in content` | T-13 (`test_registry_created`) |
| CC-14 | `adaptive_timeout` decorator defined in source | `"def adaptive_timeout"` present | T-14 (`test_decorator_defined`) |
| CC-15 | `asyncio.wait_for` used in decorator implementation | `"asyncio.wait_for"` in `adaptive_timeout.py` | T-15 (`test_asyncio_wait_for_used`) |
| CC-16 | `get_timeout_registry` function exists | Symbol present in `timeout_registry.py` | T-16 (`test_get_timeout_registry`) |
| CC-17 | `TYPE_CHECKING` guard or `get_or_create` present in registry | Pattern exists in `timeout_registry.py` | T-17 (`test_type_checking_guard`) |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-23 (`test_execution_time_recorded`) |
| CC-N | `next_steps` mentions `adaptive_timeout` | Token in lowercased join | T-24 (`test_next_steps_present`) |
| CC-LAST | After two runs, all `.py` remain parseable | `ast.parse` over all `.py` after two invocations | T-25 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_adaptive_timeouts.py`
- [ ] `AdaptiveTimeout.current_timeout_s()` computes p99 × 1.5 clamped [floor, ceiling]
- [ ] `@adaptive_timeout` decorator uses `asyncio.wait_for`; records latency only on success
- [ ] `TimeoutRegistry.get_or_create(name)` lazily instantiates per dependency
- [ ] `TYPE_CHECKING` guard in `timeout_registry.py` prevents circular import at runtime
- [ ] All four `ADAPTIVE_TIMEOUT_*` config fields present with 4-space indent
- [ ] `get_stats()` returns `p50`, `p95`, `p99`, `current_timeout_s`, `sample_count`
- [ ] `execution_time_ms` positive on every return path (success, no_op, dry_run, error)
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet
- [ ] All behavior tests B-01..B-10 pass

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-AT-01 | Tool is ALWAYS idempotent on second invocation | `"AdaptiveTimeout" in adaptive_timeout.py` → `no_op`; zero writes | T-02, T-25 |
| INV-AT-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-AT-03 | Every generated `.py` MUST parse as valid Python | `_assert_parses` loop over all entries in `files_created` | T-06, T-25 |
| INV-AT-04 | Timeout MUST be clamped to [floor, ceiling] | `max(floor_ms, min(ceiling_ms, raw))` in `current_timeout_s` | T-12 |
| INV-AT-05 | `asyncio.wait_for` MUST wrap async calls | Decorator emits `await asyncio.wait_for(fn(*args, **kwargs), timeout=...)` | T-15 |
| INV-AT-06 | `TYPE_CHECKING` guard MUST prevent circular import | Guard in `timeout_registry.py` wraps the `AdaptiveTimeout` import | T-17 |
| INV-AT-07 | Config fields MUST be inside `class Settings` body with 4-space indent | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` | T-08 |
| INV-AT-08 | `execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` invoked on all branches | T-23 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install adaptive timeouts into a clean FastAPI project**
- **As a** backend engineer tired of hard-coded timeout constants scattered across the codebase
- **I want** one tool call to add adaptive timeout infrastructure
- **So that** all outbound calls share a self-calibrating timeout system
- **Given:** A FastAPI project with `app/core/config.py` and `requirements.txt`
- **When:** `add_adaptive_timeouts(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-AT-01)
  - `files_created` contains ≥ 3 paths (CC-04)
  - `files_modified` contains ≥ 1 path (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Idempotent CI re-run**
- **As a** CI job that re-applies tooling on every commit
- **I want** the tool to skip silently when already installed
- **So that** the project is not corrupted on second invocation
- **Given:** `app/resilience/adaptive_timeout.py` already contains `AdaptiveTimeout`
- **When:** Second invocation
- **Then:**
  - `status="no_op"` (INV-AT-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` remain AST-parseable (INV-AT-03)
  - Verified by T-02, T-25

**US-03: Preview changes with dry_run**
- **As a** developer auditing a tool invocation before applying
- **I want** to see what would change without touching files
- **Given:** Fresh fixture project
- **When:** `add_adaptive_timeouts(ToolInput(dry_run=True))`
- **Then:**
  - `status="success"` with dry-run notes
  - `files_created == []`; filesystem byte-identical (INV-AT-02)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer scanning the generated files
- **I want** every function ≤ 50 LOC
- **So that** I can read and approve each in one glance
- **Given:** Tool emitted `adaptive_timeout.py`, `timeout_registry.py`
- **When:** AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef`
- **Then:** No function has `end_lineno - lineno + 1 > 50` (QS-4); verified by T-07

**US-05: Config fields bind from environment variables**
- **As an** ops engineer tuning floor/ceiling per deployment
- **I want** `ADAPTIVE_TIMEOUT_FLOOR_MS=50` in `.env` to take effect
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` instantiates
- **Then:** `ADAPTIVE_TIMEOUT_FLOOR_MS` inside `class Settings` with 4-space indent (INV-AT-07); verified by T-08

### 9.2 Adaptive timeout behaviour (US-06 .. US-12)

**US-06: Timeout adjusts down as dependency gets faster**
- **As an** ops engineer after a database optimisation
- **I want** the timeout to shrink automatically as p99 drops
- **So that** I do not need a redeploy to benefit from the improvement
- **Given:** `AdaptiveTimeout` window filled with 100 samples at 200 ms avg
- **When:** New workload drives p99 to 50 ms
- **Then:** `current_timeout_s()` drops toward `50 * 1.5 / 1000 = 0.075 s` over the next 100 calls (INV-AT-04)

**US-07: Floor prevents too-tight timeout on fast dependencies**
- **As a** developer calling a sub-millisecond in-process cache
- **I want** the timeout never to drop below `ADAPTIVE_TIMEOUT_FLOOR_MS`
- **So that** network jitter on a normally-fast dependency does not cause spurious timeouts
- **Given:** p99 observed at 10 ms with `ADAPTIVE_TIMEOUT_FLOOR_MS=100`
- **When:** `current_timeout_s()` computed
- **Then:** Returns `0.1 s` (floor / 1000), not `0.015 s` (INV-AT-04)

**US-08: Ceiling prevents unbounded timeout growth**
- **As a** service protecting its worker pool from a degraded dependency
- **I want** the timeout to never exceed `ADAPTIVE_TIMEOUT_CEILING_MS`
- **So that** a permanently-degraded dependency does not hold slots open for 30 seconds
- **Given:** Degraded DB with p99 = 20 000 ms; `ADAPTIVE_TIMEOUT_CEILING_MS=10000`
- **When:** `current_timeout_s()` computed
- **Then:** Returns `10.0 s` (ceiling / 1000) (INV-AT-04)

**US-09: Decorator raises TimeoutError — never swallows**
- **As a** caller decorating an HTTP client call
- **I want** `asyncio.TimeoutError` to propagate so my handler returns 504
- **So that** I control the error response, not the decorator
- **Given:** `@adaptive_timeout("stripe_api")` wraps a slow coroutine
- **When:** `wait_for` raises `asyncio.TimeoutError`
- **Then:** `TimeoutError` propagates to caller; decorator does not record the latency (INV-AT-05)

**US-10: Independent trackers per dependency**
- **As a** service calling both PostgreSQL and a third-party API
- **I want** `db` and `stripe_api` to have independent timeout histories
- **So that** a slow Stripe API does not inflate the DB timeout
- **Given:** `TimeoutRegistry` with `db` (p99 = 30 ms) and `stripe_api` (p99 = 500 ms)
- **When:** Each tracker's `current_timeout_s()` is read
- **Then:** `db` ≈ 0.045 s, `stripe_api` ≈ 0.75 s — independent values (CC-13)

**US-11: Safe-open on insufficient samples**
- **As a** freshly-deployed service during the first few requests
- **I want** the timeout to use the ceiling (safe-open) when fewer than 10 samples exist
- **So that** cold-start requests are not aborted by an undertrained tracker
- **Given:** `AdaptiveTimeout` with 5 recorded samples
- **When:** `current_timeout_s()` called
- **Then:** Returns `ceiling_ms / 1000` regardless of sample values (QS-12)

**US-12: `all_stats()` for ops dashboard**
- **As an** SRE running a service health dashboard
- **I want** `GET /resilience/timeouts` to return per-dependency stats
- **So that** I can see which dependencies are slow and what timeout is currently active
- **Given:** `TimeoutRegistry.all_stats()` wired to a route
- **When:** `GET /resilience/timeouts`
- **Then:** Response body is `{"db": {"p50": 20.1, "p99": 45.3, "current_timeout_s": 0.068, ...}, "stripe_api": {...}}` (CC-16)

### 9.3 Type safety and circularity (US-13 .. US-17)

**US-13: No ImportError on module load**
- **As a** developer importing `timeout_registry.py`
- **I want** the module to load without an `ImportError`
- **So that** the circular reference between registry and tracker does not crash on startup
- **Given:** `timeout_registry.py` contains `TYPE_CHECKING` guard
- **When:** `from app.resilience.timeout_registry import get_timeout_registry`
- **Then:** No `ImportError`; guard prevents runtime circular import (INV-AT-06)

**US-14: Static analysis sees types**
- **As a** developer running `mypy` on the project
- **I want** `AdaptiveTimeout` to be visible as a type in `timeout_registry.py`
- **So that** `mypy` can infer return types of `get_or_create`
- **Given:** `TYPE_CHECKING` guard imports `AdaptiveTimeout`
- **When:** `mypy` runs
- **Then:** No missing type annotation error for `_trackers` dict values (INV-AT-06)

**US-15: Lazy instantiation of trackers**
- **As a** developer who added a new dependency name after deployment
- **I want** `get_or_create("new_dep")` to create a fresh tracker on first use
- **So that** I do not need to update a static registration list
- **Given:** `"new_dep"` not in `_trackers`
- **When:** `registry.get_or_create("new_dep")`
- **Then:** New `AdaptiveTimeout()` created and stored; subsequent calls return same instance (CC-13)

**US-16: Decorator preserves function signature**
- **As a** developer using `@adaptive_timeout("db")` on a typed function
- **I want** `functools.wraps` to preserve the original function's name and docstring
- **So that** debugging and documentation tooling shows the real function name
- **Given:** `@functools.wraps(fn)` in decorator implementation
- **When:** Decorated function's `__name__` and `__doc__` are read
- **Then:** Match original function's metadata (QS-6)

**US-17: Registry singleton resets on process restart**
- **As an** ops engineer restarting a process to clear stale state
- **I want** `_registry` to reinitialize on next access
- **So that** stale per-dependency histories from an old process do not affect the new one
- **Given:** `_registry: TimeoutRegistry | None = None` at module scope
- **When:** New process starts and `get_timeout_registry()` is called
- **Then:** New `TimeoutRegistry()` created with empty `_trackers`

### 9.4 Code quality (US-18 .. US-22)

**US-18: No numpy/scipy imports**
- **As a** dependency auditor
- **I want** the generated code to use only stdlib for statistics
- **So that** the resilience module loads instantly without optional heavy deps
- **Given:** `adaptive_timeout.py`, `timeout_registry.py`
- **When:** Module is imported
- **Then:** Only `collections.deque`, `asyncio`, `functools`, `time` at module scope

**US-19: Second run does not corrupt the project**
- **As a** developer who ran the tool twice accidentally
- **I want** the project to be byte-identical to after the first run
- **Given:** First run completed successfully
- **When:** Second run executes
- **Then:** `status="no_op"`; all `.py` files still parse (CC-LAST)

**US-20: Tool reports execution time**
- **As a** CI performance tracker
- **I want** `result.execution_time_ms > 0` on every invocation
- **Given:** Any tool invocation path (success, no_op, dry_run, error)
- **When:** `result.execution_time_ms` is read
- **Then:** Positive integer (CC-N-1, INV-AT-08)

**US-21: next_steps guides developer through usage**
- **As a** developer who just ran the tool
- **I want** `result.next_steps` to include decorator usage and env var guidance
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:** Contains `"adaptive_timeout"` and `"ADAPTIVE_TIMEOUT_ENABLED"` (CC-N)

**US-22: Tool validates project_dir before writing**
- **As a** developer who passed a wrong path
- **I want** an immediate `status="error"` with a clear message
- **Given:** `inp.project_dir` points to a missing directory
- **When:** `add_adaptive_timeouts(inp)` is called
- **Then:** Returns `status="error"` with error string and `execution_time_ms > 0`

### 9.5 Operator and integration (US-23 .. US-25)

**US-23: Combine with circuit breaker**
- **As a** resilience architect stacking patterns
- **I want** adaptive timeouts AND circuit breakers on each dependency
- **Given:** Both tools installed
- **When:** Dependency breaches adaptive timeout
- **Then:** `asyncio.TimeoutError` propagates; circuit breaker counts it as a failure; breaker opens after threshold — both mechanisms cooperate

**US-24: `all_stats()` drives Grafana dashboard**
- **As an** SRE running a Grafana dashboard
- **I want** `/resilience/timeouts` polled every 15 s
- **Given:** Route wired to `all_stats()`
- **When:** Dashboard scrapes the endpoint
- **Then:** Per-dependency p50/p95/p99/current_timeout_s exported as Prometheus-style metrics

**US-25: Decorator composes with retry logic**
- **As a** developer building retry-on-transient-error logic
- **I want** to wrap `@adaptive_timeout` inside `@with_retry_budget`
- **Given:** Both decorators applied (retry budget wrapping adaptive timeout)
- **When:** Transient error triggers retry
- **Then:** Each retry attempt gets its own `wait_for` call; only successful attempts record latency; retry budget tracks total budget across all attempts

---

## 10. Test Plan

All tests live in `adapt/extend/infrastructure/test_add_adaptive_timeouts.py` and `test_add_adaptive_timeouts_behavior.py`. Each structural test creates a fresh fixture via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `at_t01` | `add_adaptive_timeouts(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `at_t02`; run once | Run second time | `r2.status == "no_op"`; empty lists (CC-02) |
| T-03 | `test_dry_run` | Fixture `at_t03`; snapshot `.py` | `dry_run=True` | `status == "success"`; byte-identical fs (CC-03) |
| T-04 | `test_files_created_count` | Fixture `at_t04` | Run tool | `len(files_created) >= 3`; all exist (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `at_t05` | Run tool | `len(files_modified) >= 1`; all exist (CC-05) |

### 10.2 Category B — Code quality (T-06 .. T-08)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture; run tool | `ast.parse` all `.py` in `app/resilience/` | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture; run tool | AST walk `app/` for functions | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture; run tool | Read `config.py` | `ADAPTIVE_TIMEOUT_ENABLED` present; 4-space indent (CC-08) |

### 10.3 Category C — Domain modules (T-09 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-09 | `test_adaptive_timeout_created` | Fixture; run tool | Read `adaptive_timeout.py` | `"AdaptiveTimeout"` present (CC-09) |
| T-10 | `test_percentiles_implemented` | Fixture; run tool | Read source | `"0.50"`, `"0.95"`, `"0.99"` all present (CC-10) |
| T-11 | `test_multiplier_1_5` | Fixture; run tool | Read `adaptive_timeout.py` | `"1.5"` present (CC-11) |
| T-12 | `test_floor_ceiling_config` | Fixture; run tool | Read `config.py` | `ADAPTIVE_TIMEOUT_FLOOR_MS` and `CEILING_MS` present (CC-12) |
| T-13 | `test_registry_created` | Fixture; run tool | Read `timeout_registry.py` | `"TimeoutRegistry"` present (CC-13) |
| T-14 | `test_decorator_defined` | Fixture; run tool | Read `adaptive_timeout.py` | `"def adaptive_timeout"` present (CC-14) |
| T-15 | `test_asyncio_wait_for_used` | Fixture; run tool | Read `adaptive_timeout.py` | `"asyncio.wait_for"` present (CC-15) |
| T-16 | `test_get_timeout_registry` | Fixture; run tool | Read `timeout_registry.py` | `"get_timeout_registry"` present (CC-16) |
| T-17 | `test_type_checking_guard` | Fixture; run tool | Read `timeout_registry.py` | `"TYPE_CHECKING"` or `"get_or_create"` present (CC-17) |

### 10.4 Category D — Meta (T-23 .. T-25)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-23 | `test_execution_time_recorded` | Fixture; run tool | Read `result.execution_time_ms` | `> 0` (CC-N-1) |
| T-24 | `test_next_steps_present` | Fixture; run tool | Inspect `result.next_steps` | Contains `"adaptive_timeout"` token (CC-N) |
| T-25 | `test_idempotent_project_still_parses` | Fixture; run twice | `ast.parse` all `.py` | No `SyntaxError` (CC-LAST) |

### 10.5 Behavior tests (B-01 .. B-10)

| # | Test | Assertion |
|---|------|-----------|
| B-01 | `test_b01_healthz_returns_200` | `/healthz` → 200 (base liveness) |
| B-02 | `test_b02_timeout_adjusts_to_p99_1_5` | `current_timeout_s()` tracks p99 × 1.5 |
| B-03 | `test_b03_floor_enforced` | Below-floor p99 → `floor_ms / 1000` returned |
| B-04 | `test_b04_ceiling_enforced` | Above-ceiling p99 → `ceiling_ms / 1000` returned |
| B-05 | `test_b05_independent_trackers` | `db` and `stripe_api` have independent histories |
| B-06 | `test_b06_get_stats_keys` | Keys: `p50`, `p95`, `p99`, `current_timeout_s`, `sample_count` |
| B-07 | `test_b07_no_optional_sdks_at_top_level` | No `numpy`/`scipy` at module scope |
| B-08 | `test_b08_all_functions_under_50_loc` | All functions ≤ 50 LOC |
| B-09 | `test_b09_config_4_space_indent` | `ADAPTIVE_TIMEOUT_ENABLED` line starts with 4 spaces |
| B-10 | `test_b10_safe_open_insufficient_samples` | `current_timeout_s()` returns ceiling when < 10 samples |

### 10.6 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_adaptive_timeouts.py -v
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_adaptive_timeouts_behavior.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_adaptive_timeouts.py
```

Target: all tests passed, 0 failed. Standalone runner prints `TOOL-096 add_adaptive_timeouts: N passed, 0 failed`.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_load_shedding` (TOOL-095) | No | ✅ Complementary | Load shedding rejects at system level; adaptive timeouts cap per dependency — different failure surfaces |
| `add_bulkhead_isolation` (TOOL-097) | No | ✅ Compatible | Bulkheads limit concurrency; adaptive timeouts limit duration — orthogonal mechanisms |
| `add_retry_budget` (TOOL-098) | No | ✅ Compatible | Retries should use `@adaptive_timeout` on each attempt; budget limits total retry cost |
| `add_chaos_testing` (TOOL-099) | No | ✅ Compatible | Chaos latency injection validates that adaptive timeouts tighten as latency observations accumulate |
| `add_graceful_shutdown` (TOOL-100) | No | ✅ Compatible | Shutdown middleware coordinates with in-flight calls; `wait_for` timeout errors are handled in the handler |
| `add_circuit_breaker` | No | ✅ Compatible | `TimeoutError` increments circuit breaker failure counter; breaker opens after threshold; both work without conflict |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Worker tasks call downstream services; `@adaptive_timeout` wraps those calls in task functions |
| `add_event_driven` | No | ✅ Compatible | Event handler coroutines can be decorated with `@adaptive_timeout` |
| `add_anomaly_detector` (TOOL-102) | No | ✅ Compatible | Anomaly detector monitors error rate and latency distribution; adaptive timeout adjusts the budget independently |
| `add_request_fingerprint` (TOOL-103) | No | ✅ Compatible | Fingerprint deduplication runs in middleware before handler; adaptive timeout runs inside the handler |
| `add_webhook_sender` | No | ✅ Compatible | Outbound webhook deliveries are prime candidates for `@adaptive_timeout("webhook_endpoint")` |
| `add_multi_tenancy` | No | ✅ Compatible | Per-tenant downstream deps can have their own tracker: `registry.get_or_create(f"db:{tenant_id}")` |
| `add_cache_layer` | No | ✅ Compatible | Cache read/write calls can use `@adaptive_timeout("redis_cache")` |
| `add_rbac` | No | ✅ Compatible | RBAC is in-process; adaptive timeout is for outbound I/O — no conflict |
| `add_sqladmin` | No | ✅ Compatible | Admin panel exposes `/resilience/timeouts` route from `all_stats()` for operator inspection |

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- app/core/config.py
rm -f app/resilience/adaptive_timeout.py \
      app/resilience/timeout_registry.py
```

Remove `@adaptive_timeout` decorator usages from any call sites that were manually added after installation.

### 12.2 Decorator cleanup at call sites

```python
# Before rollback (manual addition by developer):
@adaptive_timeout("stripe_api")
async def charge_card(amount: int) -> dict: ...

# After rollback (revert to hardcoded):
async def charge_card(amount: int) -> dict: ...
```

### 12.3 Failure mode: partial write

If the tool fails mid-execution:

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

### 12.4 Emergency: disable without rollback

Set `ADAPTIVE_TIMEOUT_ENABLED=false` in `.env`. The decorator checks `settings.ADAPTIVE_TIMEOUT_ENABLED` and falls back to a fixed ceiling timeout.

### 12.5 Uninstall validator

```bash
test ! -f app/resilience/adaptive_timeout.py \
  || (echo "adaptive_timeout.py still present" && exit 1)
grep -q "ADAPTIVE_TIMEOUT_ENABLED" app/core/config.py \
  && echo "config still patched" && exit 1
echo "rollback verified"
```

### 12.6 Re-install after rollback

After a clean rollback the fingerprint is gone:

```python
result = add_adaptive_timeouts(ToolInput(project_dir="..."))
assert result.status == "success"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Fewer than 10 samples | `current_timeout_s()` returns `ceiling_ms / 1000` (safe-open) |
| EC-02 | p99 × 1.5 < floor_ms | `current_timeout_s()` returns `floor_ms / 1000` |
| EC-03 | p99 × 1.5 > ceiling_ms | `current_timeout_s()` returns `ceiling_ms / 1000` |
| EC-04 | `adaptive_timeout.py` already contains `AdaptiveTimeout` | `status="no_op"` — zero file writes (INV-AT-01) |
| EC-05 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; no file touched (INV-AT-02) |
| EC-06 | Missing `ACCESS_TOKEN_EXPIRE_MINUTES` anchor in config | Fallback insertion before `settings = Settings()` or EOF |
| EC-07 | Circular import without `TYPE_CHECKING` guard | Guard prevents `ImportError` at runtime (INV-AT-06) |
| EC-08 | `get_or_create` called from multiple coroutines concurrently | `dict` assignment is thread-safe in CPython for simple key assignment; worst case: harmless overwrite of a new `AdaptiveTimeout` |
| EC-09 | `window_size=0` | `deque(maxlen=0)` drops all samples; `_samples` is always empty; `current_timeout_s()` always returns ceiling |
| EC-10 | `floor_ms > ceiling_ms` | `max(floor, min(ceiling, raw))` always returns `floor` — effectively disables the ceiling |
| EC-11 | `app/resilience/` directory missing | Tool creates it via `mkdir(parents=True, exist_ok=True)` |
| EC-12 | Generated file fails `ast.parse` | `_assert_parses` raises `SyntaxError`; partial files remain — use rollback 12.3 |
| EC-13 | Tool run twice back-to-back in CI | Second run returns `no_op`; project AST remains parseable (T-25) |
| EC-14 | `adaptive_timeout` decorator applied to a sync function | `asyncio.wait_for` requires a coroutine; caller gets `TypeError` at call time — not a tool-level error |
| EC-15 | `coroutine` argument to `wait_for` already cancelled | `CancelledError` propagates normally; not recorded as a latency sample |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 20 Completeness Criteria verified via `test_add_adaptive_timeouts.py` passing
2. ✅ Test report shows 0 failed across structural and behavior test files
3. ✅ Tool execution time < 5 s on reference hardware
4. ✅ Second invocation returns `status="no_op"` (INV-AT-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-AT-02)
6. ✅ Every generated `.py` AST-parses cleanly on first and second runs (INV-AT-03)
7. ✅ No generated function exceeds 50 LOC (QS-4)
8. ✅ `current_timeout_s()` returns p99 × 1.5 clamped [floor, ceiling] (INV-AT-04)
9. ✅ `asyncio.wait_for` wraps the decorated coroutine (INV-AT-05)
10. ✅ `TYPE_CHECKING` guard prevents circular import at runtime (INV-AT-06)
11. ✅ All four `ADAPTIVE_TIMEOUT_*` config fields inside `class Settings` with 4-space indent (INV-AT-07)
12. ✅ `get_stats()` returns `p50`, `p95`, `p99`, `current_timeout_s`, `sample_count`
13. ✅ `execution_time_ms > 0` on every return path (INV-AT-08)
14. ✅ Behavior tests B-01..B-10 pass against real module imports

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` passes
- [ ] `app/resilience/adaptive_timeout.py` does NOT contain `"AdaptiveTimeout"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return early

### 15.2 `adaptive_timeout.py`

- [ ] `mkdir -p app/resilience`
- [ ] Write `app/resilience/__init__.py` (empty or minimal docstring)
- [ ] Write `app/resilience/adaptive_timeout.py` via `_write_adaptive_timeout`:
  - [ ] Import: `asyncio`, `functools`, `time`, `collections.deque`
  - [ ] Class `AdaptiveTimeout` with `__init__`, `record`, `_percentile`, `current_timeout_s`, `get_stats`
  - [ ] `current_timeout_s` returns ceiling when < 10 samples (safe-open)
  - [ ] `current_timeout_s` clamps via `max(floor, min(ceiling, p99 * 1.5))`
  - [ ] `get_stats` returns `p50`, `p95`, `p99`, `current_timeout_s`, `sample_count`
  - [ ] `adaptive_timeout(dep, registry=None)` decorator using `asyncio.wait_for`
  - [ ] Decorator uses `@functools.wraps(fn)` to preserve metadata
  - [ ] Record latency only on success (`after wait_for`, not in `except`)

### 15.3 `timeout_registry.py`

- [ ] Write `app/resilience/timeout_registry.py` via `_write_timeout_registry`:
  - [ ] `from __future__ import annotations`
  - [ ] `from typing import TYPE_CHECKING`
  - [ ] `if TYPE_CHECKING: from app.resilience.adaptive_timeout import AdaptiveTimeout`
  - [ ] `_registry: TimeoutRegistry | None = None`
  - [ ] Class `TimeoutRegistry` with `__init__`, `get_or_create`, `all_stats`
  - [ ] `get_or_create` imports `AdaptiveTimeout` inside the function body (not at module scope)
  - [ ] `get_timeout_registry()` singleton

### 15.4 Config patch

- [ ] Early-return if `"ADAPTIVE_TIMEOUT_ENABLED" in src`
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent
- [ ] Emit `ADAPTIVE_TIMEOUT_ENABLED: bool = True`
- [ ] Emit `ADAPTIVE_TIMEOUT_FLOOR_MS: float = 100.0`
- [ ] Emit `ADAPTIVE_TIMEOUT_CEILING_MS: float = 10000.0`
- [ ] Emit `ADAPTIVE_TIMEOUT_WINDOW_SIZE: int = 100`
- [ ] Fallback: before `settings = Settings()` if anchor missing
- [ ] Last-resort fallback: append at EOF

### 15.5 Validation and result

- [ ] Loop over `files_created`; for every `.py` call `_assert_parses(p)`
- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain p99 multiplier, floor/ceiling, window size, decorator usage
- [ ] `next_steps` include `ADAPTIVE_TIMEOUT_ENABLED`, decorator usage example, ops route suggestion
- [ ] `execution_time_ms` set on all branches: success, no_op, dry_run, prereq error, validation error

### 15.6 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists generated files and "why adaptive timeouts" rationale
- [ ] `add_adaptive_timeouts` docstring documents `inp` parameter

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/resilience/__init__.py",
    "/tmp/fixture/app/resilience/adaptive_timeout.py",
    "/tmp/fixture/app/resilience/timeout_registry.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py"
  ],
  "notes": [
    "Adaptive timeouts added: AdaptiveTimeout (p99×1.5 clamped [100ms, 10000ms]),",
    "@adaptive_timeout decorator using asyncio.wait_for, TimeoutRegistry singleton.",
    "Floor=100ms, ceiling=10000ms, window_size=100 samples per dependency.",
    "TYPE_CHECKING guard in timeout_registry.py prevents circular import."
  ],
  "next_steps": [
    "Set ADAPTIVE_TIMEOUT_ENABLED=true in .env.",
    "Decorate outbound calls: @adaptive_timeout('postgres') async def _query(...).",
    "Expose /resilience/timeouts via TimeoutRegistry.all_stats() for ops dashboards.",
    "Tune ADAPTIVE_TIMEOUT_FLOOR_MS and CEILING_MS per SLO requirements."
  ],
  "execution_time_ms": 64
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "AdaptiveTimeout already present — adaptive timeouts already installed, skipped."
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
    "[dry_run] Would create app/resilience/adaptive_timeout.py (AdaptiveTimeout, @adaptive_timeout decorator),",
    "         app/resilience/timeout_registry.py (TimeoutRegistry singleton, TYPE_CHECKING guard).",
    "         Config: ADAPTIVE_TIMEOUT_ENABLED, FLOOR_MS=100.0, CEILING_MS=10000.0, WINDOW_SIZE=100.",
    "[dry_run] No files written."
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
