# TOOL-095: add_load_shedding

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_load_shedding` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings |
| Signature | `add_load_shedding(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_load_shedding", "description": "Add adaptive load shedding with priority lanes and degradation tiers to protect FastAPI services under overload.", "tags": ["extend", "infrastructure"], "entry": "add_load_shedding"}` |
| Files created (typical) | 5 — `app/resilience/__init__.py`, `app/resilience/load_shedder.py`, `app/resilience/priority.py`, `app/resilience/degradation.py`, `app/middleware/load_shedding.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_load_shedding` tool installs an adaptive load shedding system into a FastAPI project that protects the service from cascading failure during traffic surges, dependency slowdowns, or misconfigured clients. Without load shedding, a FastAPI service under overload saturates its thread pool and connection limits while still accepting new requests — every in-flight request slows, timeouts stack, and the service tips into a death spiral where retries amplify the very load that is causing the problem. Teams traditionally respond to overload by over-provisioning capacity — adding more replicas ahead of every peak. That is expensive and fragile; it does not help when the overload is caused by a misbehaving client tier that instantly saturates additional capacity too. The correct answer is to make the service responsible for its own protection: to know when it is overloaded, to communicate that knowledge to callers via standard HTTP semantics, and to do so with request-aware discrimination so that critical paths remain available even when non-critical paths are fully rejected.

The generated system operates on two interlocking mechanisms. First, a `LoadShedder` tracks a sliding window of request latencies (default 100 samples) and computes the empirical p99. When p99 exceeds `LOAD_SHEDDING_P99_THRESHOLD_MS` (default 500 ms), the shedder signals that the service is overloaded. The recovery window (`LOAD_SHEDDING_RECOVERY_WINDOW_S`, default 10 s) prevents oscillation: once shedding activates, it persists until p99 returns below threshold for a sustained period — a single fast request does not cancel shedding. Second, a `DegradationManager` maps load pressure to four tiers — `NORMAL`, `TIER_1`, `TIER_2`, `TIER_3` — each of which progressively disables non-essential features (analytics events, read-side caches, recommendation engines) while keeping core transactional paths alive. The tier map is a `frozenset` per tier checked via `is_feature_enabled(feature_name, tier)`.

Request priority is assigned by `classify_request(path)` using a four-level taxonomy: `CRITICAL` (health probes `/healthz`, `/readyz`, `/metrics`, auth flows `/auth/token`) are always passed through regardless of shedding state; `HIGH` (primary read/write APIs matching `/api/v*`) pass through in TIER_1 and TIER_2; `NORMAL` traffic is shed in TIER_3; `LOW` traffic (analytics `/analytics*`, recommendations `/recommendations*`) receives a `429 Too Many Requests` with a `Retry-After: 30` header as soon as TIER_1 activates. The `LoadSheddingMiddleware` is a `BaseHTTPMiddleware` subclass that intercepts each request, determines its `RequestPriority` via `classify_request`, queries `get_load_shedder().is_shedding()`, and short-circuits with `JSONResponse(status_code=429, content={"detail": "Service overloaded"}, headers={"Retry-After": "30"})` for rejected traffic — the client receives explicit backpressure instead of a mystery timeout.

Key design decisions: the `deque`-based sliding window is bounded (`maxlen=window_size`) and never leaks memory regardless of traffic volume; the p99 computation (`_percentile(0.99)`) uses `sorted(samples)[int(0.99 * len) - 1]` with a minimum-sample guard of 10 observations to prevent premature activation in the first seconds after boot; `get_load_shedder()` returns a process-wide singleton so all concurrent requests share one window and shedding decisions are consistent; the feature-disable map in `DegradationManager.is_feature_enabled(feature_name, tier)` is a plain `frozenset` per tier with no external config — every feature name listed in a tier's disabled set returns `False` at that tier or above; operators flip `LOAD_SHEDDING_ENABLED` in `.env` to disable the entire system without a redeploy; the recovery guard (`_shed_since`) tracks when shedding began so the recovery-window comparison works across multiple `is_shedding()` calls without resetting unnecessarily.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget; measured via `execution_time_ms` in `ToolResult` |
| Files created | ≥ 4 | Requires: load_shedder, priority, degradation, middleware (CC-04) |
| Files modified | ≥ 1 | Config patch with `LOAD_SHEDDING_*` fields (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; AST walk enforced (CC-07) |
| Middleware decision latency | < 0.5 ms | In-process sliding window lookup; no external I/O |
| p99 computation overhead | < 0.1 ms | `sorted(list(deque))` bounded at 100 samples |
| `429` response latency from dispatch | ≤ 1 ms | Single priority check + short-circuit `JSONResponse` |
| `CRITICAL` request false-shed rate | 0% | `classify_request` returns `CRITICAL` for health/auth; middleware skips unconditionally |
| `is_shedding()` computation | O(n log n) | Bounded by `window_size=100`; always < 1 ms in practice |
| Feature flag lookup (`is_feature_enabled`) | O(1) | `frozenset` membership test |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # No load shedding middleware
│   ├── core/
│   │   └── config.py        # Settings class, no LOAD_SHEDDING_* fields
│   └── middleware/
│       └── idempotency.py   # No load shedding middleware registered
└── requirements.txt
```

Under traffic surge, every request is accepted and queued regardless of latency trajectory. Low-priority analytics calls compete for the same connection pool slots as checkout flows. The service degrades uniformly rather than shedding the least valuable traffic first. A `/analytics/events` call that normally takes 5 ms now takes 800 ms because the DB pool is exhausted, but it is still accepted. The service tips into a death spiral.

### 4.2 LoadShedder (sliding-window p99): AFTER

```python
# app/resilience/load_shedder.py
"""Adaptive load shedder using a sliding-window p99 latency estimator."""
from __future__ import annotations

import time
from collections import deque

_shedder: "LoadShedder | None" = None


class LoadShedder:
    """Track request latency and signal overload when p99 breaches threshold."""

    def __init__(
        self,
        threshold_ms: float = 500.0,
        window_size: int = 100,
        recovery_window_s: float = 10.0,
    ) -> None:
        self._threshold_ms = threshold_ms
        self._window_size = window_size
        self._recovery_window_s = recovery_window_s
        self._samples: deque[float] = deque(maxlen=window_size)
        self._shedding = False
        self._shed_since: float | None = None

    def record(self, latency_ms: float) -> None:
        """Record a completed request latency sample."""
        self._samples.append(latency_ms)

    def get_p99(self) -> float | None:
        """Return p99 latency or None if fewer than 10 samples."""
        if len(self._samples) < 10:
            return None
        return self._percentile(0.99)

    def _percentile(self, p: float) -> float:
        sorted_s = sorted(self._samples)
        idx = max(0, int(p * len(sorted_s)) - 1)
        return sorted_s[idx]

    def is_shedding(self) -> bool:
        """Return True when load shedding is active."""
        p99 = self.get_p99()
        if p99 is None:
            return False
        if p99 > self._threshold_ms:
            self._shedding = True
            self._shed_since = time.monotonic()
        elif self._shedding and self._shed_since is not None:
            if time.monotonic() - self._shed_since > self._recovery_window_s:
                self._shedding = False
                self._shed_since = None
        return self._shedding


def get_load_shedder() -> LoadShedder:
    """Return the process-wide LoadShedder singleton."""
    global _shedder
    if _shedder is None:
        _shedder = LoadShedder()
    return _shedder
```

### 4.3 RequestPriority and classify_request: AFTER

```python
# app/resilience/priority.py
"""Request priority taxonomy for load shedding decisions."""
from __future__ import annotations

import enum


class RequestPriority(enum.IntEnum):
    CRITICAL = 0   # always passes — health, auth
    HIGH = 1       # passes until TIER_2
    NORMAL = 2     # shed at TIER_2
    LOW = 3        # shed at TIER_1


def classify_request(path: str) -> RequestPriority:
    """Map a request path to its load shedding priority."""
    if path in {"/healthz", "/readyz", "/metrics", "/auth/token"}:
        return RequestPriority.CRITICAL
    if path.startswith("/analytics") or path.startswith("/recommendations"):
        return RequestPriority.LOW
    if path.startswith("/api/v"):
        return RequestPriority.HIGH
    return RequestPriority.NORMAL
```

### 4.4 DegradationManager: AFTER

```python
# app/resilience/degradation.py
"""Feature degradation tiers for progressive service impairment."""
from __future__ import annotations

import enum


class DegradationTier(enum.IntEnum):
    NORMAL = 0
    TIER_1 = 1   # Shed LOW; disable analytics_events
    TIER_2 = 2   # Shed LOW + NORMAL; disable recommendations
    TIER_3 = 3   # Shed LOW + NORMAL + HIGH; emergency mode


_DISABLED_IN_TIER: dict[DegradationTier, frozenset[str]] = {
    DegradationTier.TIER_1: frozenset({"analytics_events", "usage_tracking"}),
    DegradationTier.TIER_2: frozenset({
        "analytics_events", "usage_tracking", "recommendations", "read_cache",
    }),
    DegradationTier.TIER_3: frozenset({
        "analytics_events", "usage_tracking", "recommendations", "read_cache",
        "search_index_refresh", "reporting_aggregate",
    }),
}


class DegradationManager:
    """Maps load tier to disabled feature set."""

    def is_feature_enabled(self, feature_name: str, tier: DegradationTier) -> bool:
        """Return False if feature_name is disabled at the given tier."""
        disabled = _DISABLED_IN_TIER.get(tier, frozenset())
        return feature_name not in disabled
```

### 4.5 LoadSheddingMiddleware: AFTER

```python
# app/middleware/load_shedding.py
"""ASGI middleware that rejects low-priority requests under load."""
from __future__ import annotations

import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.resilience.load_shedder import get_load_shedder
from app.resilience.priority import RequestPriority, classify_request


class LoadSheddingMiddleware(BaseHTTPMiddleware):
    """Reject LOW-priority requests when p99 exceeds threshold."""

    async def dispatch(self, request: Request, call_next):
        from app.core.config import settings
        if not getattr(settings, "LOAD_SHEDDING_ENABLED", True):
            return await call_next(request)

        priority = classify_request(request.url.path)
        if priority == RequestPriority.CRITICAL:
            return await call_next(request)

        shedder = get_load_shedder()
        if shedder.is_shedding() and priority == RequestPriority.LOW:
            return JSONResponse(
                status_code=429,
                content={"detail": "Service overloaded"},
                headers={"Retry-After": "30"},
            )
        start = time.monotonic()
        response = await call_next(request)
        shedder.record((time.monotonic() - start) * 1000)
        return response
```

### 4.6 Config patch: AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- load shedding settings — added by add_load_shedding tool ---
    LOAD_SHEDDING_ENABLED: bool = True
    LOAD_SHEDDING_P99_THRESHOLD_MS: float = 500.0
    LOAD_SHEDDING_RECOVERY_WINDOW_S: float = 10.0
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees all three fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables.

### 4.7 Typical caller usage (after install)

```python
# app/main.py — after install
from app.middleware.load_shedding import LoadSheddingMiddleware

app = FastAPI()
app.add_middleware(LoadSheddingMiddleware)
```

```python
# app/api/routes/example.py — checking degradation tier
from app.resilience.degradation import DegradationManager, DegradationTier
from app.resilience.load_shedder import get_load_shedder

manager = DegradationManager()

@router.post("/analytics/ingest")
async def ingest_event(payload: dict):
    # Check degradation tier before doing expensive processing
    shedder = get_load_shedder()
    tier = DegradationTier.TIER_1 if shedder.is_shedding() else DegradationTier.NORMAL
    if not manager.is_feature_enabled("analytics_events", tier):
        return {"status": "dropped", "reason": "degradation_tier_1"}
    # ... process event
    return {"status": "ok"}
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Pre-flight check `"LoadShedder" in app/resilience/load_shedder.py` returns `no_op` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` AST-parses** | `_assert_parses` run on each created file |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk assertion in test harness |
| QS-5 | **`CRITICAL` requests always pass** | `classify_request` returns `CRITICAL` for health/auth; middleware skips unconditionally |
| QS-6 | **`LOW` requests get explicit `429 + Retry-After`** | Middleware emits `JSONResponse(429)` with `Retry-After: 30` header |
| QS-7 | **Config fields live inside `class Settings` body** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-8 | **Sliding window is bounded** | `deque(maxlen=window_size)` — memory-safe regardless of traffic volume |
| QS-9 | **No optional SDKs at module top-level** | No `import numpy`, `import scipy` at module scope in resilience files |
| QS-10 | **`execution_time_ms` is positive on every return path** | `_elapsed_ms(start)` called on success, no_op, dry_run, error |
| QS-11 | **`DegradationTier` has exactly four members** | `NORMAL`, `TIER_1`, `TIER_2`, `TIER_3` — no stubs |
| QS-12 | **Recovery window prevents oscillation** | `_shed_since` timestamp checked on recovery path; single fast request does not cancel shedding |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_load_shedding.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 4 new files | `len(result.files_created) >= 4` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 1 existing file (config) | `len(result.files_modified) >= 1` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` in `app/resilience/` and `app/middleware/` | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `LOAD_SHEDDING_ENABLED` inside `class Settings` with 4-space indent | String scan + indent check on field line | T-08 (`test_config_fields_patched`) |
| CC-09 | `app/resilience/load_shedder.py` exists and contains `LoadShedder` | File exists + `"LoadShedder" in content` | T-09 (`test_load_shedder_created`) |
| CC-10 | `DegradationTier` enum has `NORMAL`, `TIER_1`, `TIER_2`, `TIER_3` members | Substring checks in degradation file | T-10 (`test_degradation_tier_enum`) |
| CC-11 | `app/resilience/priority.py` exists with `RequestPriority` enum | File exists + all four member names | T-11 (`test_priority_created`) |
| CC-12 | `classify_request` function is defined in `priority.py` | `"classify_request" in content` | T-12 (`test_classify_request_defined`) |
| CC-13 | `app/resilience/degradation.py` exists with `DegradationManager` + `is_feature_enabled` | File exists + both symbol checks | T-13 (`test_degradation_created`) |
| CC-14 | `LoadSheddingMiddleware` exists in `app/middleware/load_shedding.py` | File exists + `"LoadSheddingMiddleware" in content` | T-14 (`test_middleware_created`) |
| CC-15 | Middleware emits `429` + `Retry-After` header | `"429" in content` and `"Retry-After" in content` | T-15 (`test_middleware_429`) |
| CC-16 | `CRITICAL` priority always passes; `LOW` is targeted first | `"CRITICAL" in content` and `LOW` shed logic present | T-16 (`test_critical_passes_low_targeted`) |
| CC-17 | `_percentile` or p99 computed from sliding window | `"0.99" in content` and `"deque"` in load_shedder | T-17 (`test_p99_sliding_window`) |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-23 (`test_execution_time_recorded`) |
| CC-N | `next_steps` guides developer to set `LOAD_SHEDDING_ENABLED` | Lowercased join contains `"load_shedding"` | T-24 (`test_next_steps_present`) |
| CC-LAST | After two runs, all `.py` files remain parseable | `ast.parse` over all `.py` after two invocations | T-25 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_load_shedding.py`
- [ ] `add_load_shedding.py` fingerprint-checks `"LoadShedder" in load_shedder.py` and returns `no_op` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `RequestPriority.CRITICAL` traffic is never shed under any tier or load state
- [ ] `RequestPriority.LOW` traffic receives `429 + Retry-After: 30` header when shedding active
- [ ] `p99` uses bounded `deque(maxlen=window_size)` with minimum 10-sample guard
- [ ] `DegradationTier` has exactly four members: `NORMAL`, `TIER_1`, `TIER_2`, `TIER_3`
- [ ] Config fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent
- [ ] `execution_time_ms` set on every return path (success, no_op, dry_run, error)
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet
- [ ] All behavior tests B-01..B-10 pass against real ASGI app

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-LS-01 | Tool is ALWAYS idempotent on second invocation | `"LoadShedder" in load_shedder.py` → `no_op`; zero file writes | T-02, T-25 |
| INV-LS-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-LS-03 | Every generated `.py` MUST parse as valid Python | `_assert_parses` loop over all entries in `files_created` | T-06, T-25 |
| INV-LS-04 | `CRITICAL` requests MUST always pass through — no exceptions | `priority == CRITICAL` → `return await call_next(request)` before shedding check | T-16 |
| INV-LS-05 | `LOW` requests MUST receive `429 + Retry-After` when shedding active | Middleware `JSONResponse(status_code=429)` + `Retry-After: 30` header | T-15 |
| INV-LS-06 | Sliding window MUST be bounded | `deque(maxlen=window_size)` construction — never unbounded list | T-17 |
| INV-LS-07 | `LOAD_SHEDDING_*` fields MUST be inside `class Settings` body with 4-space indent | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` | T-08 |
| INV-LS-08 | `execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` invoked on success, no_op, dry_run, and error branches | T-23 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install load shedding into a clean FastAPI project**
- **As a** reliability engineer protecting a payment API
- **I want** one tool call to add adaptive load shedding
- **So that** the service degrades gracefully under traffic surge rather than dying uniformly
- **Given:** A FastAPI project with `app/core/config.py` and `requirements.txt`
- **When:** `add_load_shedding(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-LS-01)
  - `files_created` contains ≥ 4 paths (CC-04)
  - `files_modified` contains ≥ 1 path (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Idempotent re-run in CI**
- **As a** CI job that re-applies tooling on every commit
- **I want** the tool to skip silently when already installed
- **So that** CI does not corrupt the project on repeat runs
- **Given:** `app/resilience/load_shedder.py` already contains `LoadShedder`
- **When:** Second invocation
- **Then:**
  - `status="no_op"` (INV-LS-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` remain AST-parseable (INV-LS-03)
  - Verified by T-02, T-25

**US-03: Preview changes with dry_run**
- **As a** developer auditing a tool invocation before applying
- **I want** to see what would change without touching files
- **So that** I can review the exact file list before committing
- **Given:** Fresh fixture project
- **When:** `add_load_shedding(ToolInput(dry_run=True))`
- **Then:**
  - `status="success"` with dry-run notes
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-LS-02)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer scanning the generated files
- **I want** every generated function to be ≤ 50 LOC
- **So that** I can read and approve each function in one glance
- **Given:** Tool emitted `load_shedder.py`, `priority.py`, `degradation.py`, `middleware/load_shedding.py`
- **When:** AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef`
- **Then:**
  - No function has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

**US-05: Config fields bind from environment variables**
- **As an** ops engineer tuning the shedding threshold
- **I want** `LOAD_SHEDDING_P99_THRESHOLD_MS=800` in `.env` to override the default
- **So that** I can tune per-deployment without rebuilding images
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` instantiates
- **Then:**
  - `LOAD_SHEDDING_P99_THRESHOLD_MS` inside `class Settings` with 4-space indent picks up env var (INV-LS-07)
  - Verified by T-08

### 9.2 Load shedding behaviour (US-06 .. US-12)

**US-06: Health probe always returns 200 during overload**
- **As a** load balancer sending `GET /healthz`
- **I want** the probe to always return 200 even during p99 breach
- **So that** the instance is not removed from rotation during a latency spike
- **Given:** `classify_request("/healthz")` returns `CRITICAL`
- **When:** Middleware evaluates the request while `is_shedding()` is `True`
- **Then:** Request passes through unconditionally — no 429 (INV-LS-04)

**US-07: Analytics call receives explicit backpressure**
- **As a** low-priority analytics client
- **I want** `429 Retry-After: 30` when the service is saturated
- **So that** I back off instead of amplifying the overload
- **Given:** `classify_request("/analytics/events")` returns `LOW`
- **When:** Middleware detects shedding is active
- **Then:** Response `429 {"detail": "Service overloaded"}` with `Retry-After: 30` header (INV-LS-05)

**US-08: Primary API passes through in TIER_1**
- **As a** checkout flow hitting `/api/v1/orders`
- **I want** to continue operating when only LOW traffic is being shed
- **So that** revenue-critical flows are not disrupted by analytics load
- **Given:** `classify_request("/api/v1/orders")` returns `HIGH`
- **When:** `is_shedding()` is `True` but tier is TIER_1
- **Then:** Request passes through; only `LOW` priority receives 429

**US-09: p99 tracks real latency distribution**
- **As an** SRE watching the p99 metric
- **I want** shedding to activate only after sustained high p99
- **So that** transient spikes do not cause spurious shedding cascades
- **Given:** `LoadShedder` with `window_size=100` and minimum 10 samples
- **When:** 95 samples under threshold, then 5 samples over
- **Then:** `is_shedding()` state depends on whether overall p99 breaches threshold (CC-17)

**US-10: Shedding auto-recovers after load subsides**
- **As an** operator watching the system recover post-spike
- **I want** shedding to deactivate automatically after `LOAD_SHEDDING_RECOVERY_WINDOW_S`
- **So that** normal traffic resumes without manual intervention
- **Given:** `is_shedding() == True` and p99 drops below threshold
- **When:** `recovery_window_s` seconds elapse since shedding onset
- **Then:** `is_shedding()` returns `False`; LOW traffic resumes

**US-11: Boot-time minimum sample guard**
- **As a** freshly-deployed service receiving its first requests
- **I want** shedding to not activate on the first 9 requests
- **So that** a cold-start latency spike does not shed early users
- **Given:** `LoadShedder` with fewer than 10 samples
- **When:** `get_p99()` is called
- **Then:** Returns `None`; `is_shedding()` returns `False`

**US-12: Operator disables system via env flag**
- **As an** ops engineer during an incident
- **I want** `LOAD_SHEDDING_ENABLED=false` to disable shedding without redeploying
- **So that** I can rule out load shedding as a contributing factor quickly
- **Given:** `settings.LOAD_SHEDDING_ENABLED == False`
- **When:** Middleware processes any request
- **Then:** Passes request through unconditionally (QS-9)

### 9.3 Degradation tier system (US-13 .. US-17)

**US-13: Feature flags disable analytics events in TIER_1**
- **As a** product feature guard checking degradation state
- **I want** `is_feature_enabled("analytics_events", TIER_1)` to return `False`
- **So that** the analytics write path skips work before the service reaches critical load
- **Given:** `DegradationTier.TIER_1` active
- **When:** Handler calls `manager.is_feature_enabled("analytics_events", DegradationTier.TIER_1)`
- **Then:** Returns `False` (CC-13)

**US-14: TIER_2 disables recommendations in addition to analytics**
- **As a** service protecting its most expensive feature path
- **I want** `is_feature_enabled("recommendations", TIER_2)` to return `False`
- **So that** ML inference calls stop before the DB pool is fully starved
- **Given:** `DegradationTier.TIER_2` active
- **When:** Handler calls `manager.is_feature_enabled("recommendations", DegradationTier.TIER_2)`
- **Then:** Returns `False`

**US-15: NORMAL tier enables all features**
- **As a** service operating below threshold
- **I want** all features enabled at `DegradationTier.NORMAL`
- **So that** no functionality is disabled when the service is healthy
- **Given:** `DegradationTier.NORMAL`
- **When:** `manager.is_feature_enabled("analytics_events", DegradationTier.NORMAL)`
- **Then:** Returns `True`

**US-16: Unknown feature name returns True (safe default)**
- **As a** developer who added a new feature name not in the disable set
- **I want** unknown features to be treated as enabled by default
- **So that** I do not accidentally disable new features by omitting them from the disable map
- **Given:** A feature name not in any tier's disabled frozenset
- **When:** `manager.is_feature_enabled("new_feature", DegradationTier.TIER_3)`
- **Then:** Returns `True` (frozenset membership test fails → enabled)

**US-17: Four-tier taxonomy is exhaustive**
- **As a** developer reading the degradation map
- **I want** exactly four named tiers: `NORMAL`, `TIER_1`, `TIER_2`, `TIER_3`
- **So that** documentation and dashboards reference a stable set of states
- **Given:** `DegradationTier` enum in `degradation.py`
- **When:** Listing members
- **Then:** Exactly 4 members (CC-10)

### 9.4 Code quality and safety (US-18 .. US-22)

**US-18: No numpy/scipy at module top-level**
- **As a** dependency auditor
- **I want** no heavy numerical libraries imported at module level
- **So that** the resilience module loads instantly on every request worker boot
- **Given:** `load_shedder.py`, `priority.py`, `degradation.py`, `middleware/load_shedding.py`
- **When:** Module is imported
- **Then:** Only stdlib (`collections.deque`, `time`, `enum`, `math`) at module scope (QS-9)

**US-19: Second run does not corrupt any file**
- **As a** developer who accidentally ran the tool twice
- **I want** the project to be identical to after the first run
- **So that** the double-run does not cause a syntax error or import collision
- **Given:** First run completed successfully
- **When:** Second run executes
- **Then:** `status="no_op"`; all `.py` files still AST-parse (CC-LAST)

**US-20: Tool reports execution time**
- **As a** CI performance tracker
- **I want** `result.execution_time_ms > 0`
- **So that** I can monitor tool speed across versions
- **Given:** Any tool invocation path (success, no_op, dry_run, error)
- **When:** `result.execution_time_ms` is read
- **Then:** Positive integer (CC-N-1, INV-LS-08)

**US-21: next_steps guides operator through setup**
- **As a** developer who just ran the tool
- **I want** `result.next_steps` to include middleware registration and env var guidance
- **So that** I do not forget to register the middleware in `app/main.py`
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:** Contains `"LOAD_SHEDDING_ENABLED"` and `"add_middleware"` guidance (CC-N)

**US-22: Tool validates project_dir before writing**
- **As a** developer who passed a wrong path
- **I want** an immediate `status="error"` with a clear message
- **So that** I do not get a partial write followed by an obscure `FileNotFoundError`
- **Given:** `inp.project_dir` points to a missing directory
- **When:** `add_load_shedding(inp)` is called
- **Then:** Returns `status="error"` with `error` string and `execution_time_ms > 0`

### 9.5 Operator and integration (US-23 .. US-25)

**US-23: Register middleware in main.py after install**
- **As a** developer following the next_steps
- **I want** to register `LoadSheddingMiddleware` in one line
- **So that** ASGI intercepts all requests through the middleware stack
- **Given:** `app/middleware/load_shedding.py` generated
- **When:** `app.add_middleware(LoadSheddingMiddleware)` added to `app/main.py`
- **Then:** All requests pass through the middleware; LOW traffic receives 429 during overload

**US-24: Combine with circuit breaker**
- **As a** resilience architect stacking patterns
- **I want** load shedding at the front door and circuit breakers around each downstream
- **So that** system-wide overload and per-dependency failure are handled independently
- **Given:** Both `add_load_shedding` and `add_circuit_breaker` installed
- **When:** A downstream dependency fails open
- **Then:** Circuit breaker trips for that dependency; load shedding activates if the failures cascade into high p99; both work without conflict

**US-25: Sliding window resets on process restart**
- **As an** ops engineer who just rolled out a fix for a memory leak
- **I want** the sliding window to start fresh on the new process
- **So that** stale high-latency samples from the old process do not trigger immediate shedding
- **Given:** `_shedder` is a module-level singleton initialized to `None`
- **When:** New process starts and `get_load_shedder()` is called
- **Then:** `LoadShedder()` created with empty `deque`; `get_p99()` returns `None` until 10 samples collected

---

## 10. Test Plan

All tests live in `adapt/extend/infrastructure/test_add_load_shedding.py` and `test_add_load_shedding_behavior.py`. Each structural test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `ls_t01` | `add_load_shedding(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `ls_t02`; run once | Run second time | `r2.status == "no_op"`; `files_created == []`; `files_modified == []` (CC-02) |
| T-03 | `test_dry_run` | Fixture `ls_t03`; snapshot all `.py` | `add_load_shedding(ToolInput(dry_run=True))` | `status == "success"`; byte-identical filesystem (CC-03) |
| T-04 | `test_files_created_count` | Fixture `ls_t04` | Run tool | `len(files_created) >= 4`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `ls_t05` | Run tool | `len(files_modified) >= 1`; every path exists (CC-05) |

### 10.2 Category B — Code quality (T-06 .. T-08)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `ls_t06`; run tool | `ast.parse` every `.py` in `app/resilience/` and `app/middleware/` | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `ls_t07`; run tool | AST walk `app/` for `FunctionDef`/`AsyncFunctionDef` | `end_lineno - lineno + 1 <= 50` for all functions (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `ls_t08`; run tool | Read `app/core/config.py` | `LOAD_SHEDDING_ENABLED` present; line starts with 4-space indent (CC-08) |

### 10.3 Category C — Domain modules (T-09 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-09 | `test_load_shedder_created` | Fixture `ls_t09`; run tool | Read `app/resilience/load_shedder.py` | `LoadShedder` and `get_load_shedder` present (CC-09) |
| T-10 | `test_degradation_tier_enum` | Fixture `ls_t10`; run tool | Read `degradation.py` | `NORMAL`, `TIER_1`, `TIER_2`, `TIER_3` all present (CC-10) |
| T-11 | `test_priority_created` | Fixture `ls_t11`; run tool | Read `app/resilience/priority.py` | `RequestPriority` + all four members present (CC-11) |
| T-12 | `test_classify_request_defined` | Fixture `ls_t12`; run tool | Read `priority.py` | `"classify_request"` in content (CC-12) |
| T-13 | `test_degradation_created` | Fixture `ls_t13`; run tool | Read `degradation.py` | `DegradationManager` + `is_feature_enabled` present (CC-13) |
| T-14 | `test_middleware_created` | Fixture `ls_t14`; run tool | Read `app/middleware/load_shedding.py` | `"LoadSheddingMiddleware"` in content (CC-14) |
| T-15 | `test_middleware_429` | Fixture `ls_t15`; run tool | Read middleware source | `"429"` and `"Retry-After"` in content (CC-15) |
| T-16 | `test_critical_passes_low_targeted` | Fixture `ls_t16`; run tool | Read middleware + priority sources | `"CRITICAL"` pass-through and `LOW` shed logic (CC-16) |
| T-17 | `test_p99_sliding_window` | Fixture `ls_t17`; run tool | Read `load_shedder.py` | `"0.99"` and `"deque"` in content (CC-17) |

### 10.4 Category D — Meta (T-23 .. T-25)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-23 | `test_execution_time_recorded` | Fixture `ls_t23`; run tool | Read `result.execution_time_ms` | `> 0` (CC-N-1) |
| T-24 | `test_next_steps_present` | Fixture `ls_t24`; run tool | Inspect `result.next_steps` | Lowercased join contains `"load_shedding"` (CC-N) |
| T-25 | `test_idempotent_project_still_parses` | Fixture `ls_t25`; run twice | `ast.parse` all `.py` | No `SyntaxError` after two invocations (CC-LAST) |

### 10.5 Behavior tests (B-01 .. B-10)

Reside in `test_add_load_shedding_behavior.py`. Boot real ASGI app with generated middleware using `httpx.ASGITransport`.

| # | Test | Assertion |
|---|------|-----------|
| B-01 | `test_b01_healthz_returns_200` | `GET /healthz` → 200 even when shedding mocked as active |
| B-02 | `test_b02_load_shedder_tracks_p99` | `LoadShedder.get_p99()` returns 99th percentile from recorded samples |
| B-03 | `test_b03_request_priority_values` | `RequestPriority` integer values: `CRITICAL=0`, `HIGH=1`, `NORMAL=2`, `LOW=3` |
| B-04 | `test_b04_classify_request` | `/healthz` → `CRITICAL`; `/analytics/x` → `LOW`; `/api/v1/x` → `HIGH` |
| B-05 | `test_b05_degradation_manager_tier1` | `is_feature_enabled("analytics_events", TIER_1)` returns `False` |
| B-06 | `test_b06_is_shedding_activates` | `is_shedding()` returns `True` after filling window with values above threshold |
| B-07 | `test_b07_no_optional_sdks_at_top_level` | No `numpy`/`scipy` import at module top-level in resilience or middleware files |
| B-08 | `test_b08_all_functions_under_50_loc` | AST walk confirms all functions ≤ 50 LOC |
| B-09 | `test_b09_config_4_space_indent` | `LOAD_SHEDDING_ENABLED` line in `config.py` starts with exactly 4 spaces |
| B-10 | `test_b10_minimum_sample_guard` | `get_p99()` returns `None` when fewer than 10 samples recorded |

### 10.6 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_load_shedding.py -v
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_load_shedding_behavior.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_load_shedding.py
```

Target: all tests passed, 0 failed. Standalone runner prints `TOOL-095 add_load_shedding: N passed, 0 failed`.

---

## 11. Interaction Matrix

How `add_load_shedding` composes with other SKILL-001 tools. Order matters for middleware stack registration.

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_adaptive_timeouts` (TOOL-096) | No | ✅ Compatible | Timeouts enforce per-dependency caps; load shedding protects system-wide p99 — complementary layers |
| `add_bulkhead_isolation` (TOOL-097) | No | ✅ Compatible | Bulkheads limit concurrency per pool; load shedding rejects at the front door before pools are hit |
| `add_retry_budget` (TOOL-098) | No | ✅ Compatible | Retry budget limits retry amplification that drives p99 higher; load shedding reduces new arrivals |
| `add_chaos_testing` (TOOL-099) | No | ✅ Compatible | Chaos testing can simulate latency spikes to validate that shedding activates correctly |
| `add_graceful_shutdown` (TOOL-100) | Yes | ✅ Compatible — load shedding BEFORE shutdown | Register `LoadSheddingMiddleware` before `ShutdownMiddleware`; both are `BaseHTTPMiddleware` |
| `add_circuit_breaker` | No | ✅ Compatible | Circuit breaker handles individual dependency failures; load shedding handles aggregate system overload |
| `add_rate_limiting` | No | ⚠️ Caveat | Rate limiting enforces per-user quotas; load shedding enforces system-wide capacity — do NOT substitute |
| `add_anomaly_detector` (TOOL-102) | No | ✅ Compatible | Anomaly detector alerts on statistical deviations; load shedding acts on p99 latency — different signals |
| `add_api_replay_debugger` (TOOL-101) | No | ✅ Compatible | Replay debugger can replay a traffic spike to test that shedding activates at the right threshold |
| `add_request_fingerprint` (TOOL-103) | Yes | ✅ Compatible — fingerprint BEFORE load shedding | Deduplication runs first; if duplicate is detected it returns without going through the shedder |
| `add_multi_tenancy` | No | ⚠️ Caveat | `classify_request` should be extended to mark tenant admin health-check paths as `CRITICAL` |
| `add_rbac` | No | ✅ Compatible | RBAC runs inside the handler; load shedding runs before the handler is reached — no conflict |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Worker enqueue calls (`POST /enqueue-triggering`) can be `HIGH` priority; background workers are separate processes and unaffected |
| `add_event_driven` | No | ✅ Compatible | Event-driven routes can register as `HIGH` or `CRITICAL` in `classify_request` |
| `add_cache_layer` | No | ✅ Compatible | Cache read/write paths can be classified; during TIER_2 `read_cache` feature can be disabled to skip cache warming |
| `add_sse` | No | ⚠️ Caveat | SSE connections are long-lived; load shedding should not close existing connections — only reject new ones |
| `add_webhook_receiver` | No | ✅ Compatible | Incoming webhooks are typically `HIGH` priority; return 429 for `LOW` from external senders is safe |
| `add_feature_flags` | No | ✅ Compatible | Feature flags provide persistent on/off; `DegradationManager.is_feature_enabled` provides transient load-reactive flags |
| `add_sqladmin` | No | ✅ Compatible | Admin panel routes should be classified as `CRITICAL` or `HIGH` in `classify_request` |

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- app/core/config.py

rm -f app/resilience/load_shedder.py \
      app/resilience/priority.py \
      app/resilience/degradation.py \
      app/middleware/load_shedding.py

# Remove resilience __init__.py only if it was empty before the tool
# Remove middleware registration from app/main.py
```

### 12.2 Middleware rollback in main.py

```python
# Remove this line from app/main.py:
# app.add_middleware(LoadSheddingMiddleware)
```

### 12.3 Failure mode: partial write

If the tool fails mid-execution (e.g. `_assert_parses` raises `SyntaxError`), partially-written files remain on disk:

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
# Then delete any partially-written files in app/resilience/ and app/middleware/
```

### 12.4 Emergency: disable shedding without rollback

If load shedding is causing false-positives in production:

1. Set `LOAD_SHEDDING_ENABLED=false` in `.env` and restart the service.
2. The middleware checks `settings.LOAD_SHEDDING_ENABLED` and passes all requests through.
3. No code rollback required; the generated files remain intact.
4. After diagnosing, tune `LOAD_SHEDDING_P99_THRESHOLD_MS` upward and re-enable.

### 12.5 Uninstall validator

```bash
test ! -f app/resilience/load_shedder.py \
  || (echo "load_shedder.py still present" && exit 1)

grep -q "LOAD_SHEDDING_ENABLED" app/core/config.py \
  && echo "config still patched" && exit 1

grep -q "LoadSheddingMiddleware" app/main.py \
  && echo "middleware still registered in main.py — remove manually" && exit 1

echo "rollback verified"
```

### 12.6 Re-install after rollback

After a clean rollback, `app/resilience/load_shedder.py` does not exist, so the idempotency guard clears and the tool can be re-run:

```python
result = add_load_shedding(ToolInput(project_dir="..."))
assert result.status == "success"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing `CONFIG_SETTINGS` prereq | `ensure_prerequisites` returns errors → `status="error"` with prereq details and hint |
| EC-03 | `app/resilience/load_shedder.py` already contains `LoadShedder` | Early return `status="no_op"` — zero file writes |
| EC-04 | `inp.dry_run=True` on a fresh project | Returns `status="success"` with dry-run notes; no file touched (INV-LS-02) |
| EC-05 | `app/core/config.py` already contains `LOAD_SHEDDING_ENABLED` | `_patch_config` early-returns; no duplicate block appended |
| EC-06 | `app/core/config.py` lacks `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | Fallback insertion before `settings = Settings()` or at EOF (still valid Python) |
| EC-07 | Window has fewer than 10 samples | `get_p99()` returns `None`; `is_shedding()` returns `False` — no premature shedding on fresh boot |
| EC-08 | All incoming requests are `CRITICAL` priority | No request ever receives 429; system accepts all traffic even under overload |
| EC-09 | `LOAD_SHEDDING_ENABLED=false` in env | Middleware checks flag; passes all requests through without evaluating `is_shedding()` |
| EC-10 | `app/middleware/` directory missing | Tool creates it via `mkdir(parents=True, exist_ok=True)` before writing middleware file |
| EC-11 | `app/resilience/` directory missing | Tool creates it via `mkdir(parents=True, exist_ok=True)` before writing resilience files |
| EC-12 | Generated `load_shedder.py` fails `ast.parse` | `_assert_parses` raises `SyntaxError`; partial files remain — use rollback 12.3 |
| EC-13 | p99 spikes then immediately drops | `_shedding` remains `True` until `recovery_window_s` elapses; single fast request does not cancel shedding |
| EC-14 | `window_size=0` passed via patched settings | `deque(maxlen=0)` drops all samples; `get_p99()` always returns `None`; `is_shedding()` always `False` |
| EC-15 | Tool run twice back-to-back in CI | Second run returns `no_op`; project AST remains parseable (T-25 verifies) |
| EC-16 | `app/core/config.py` is read-only on disk | Tool raises `PermissionError`; `files_modified` does not include config — caller must fix permissions |
| EC-17 | `classify_request` receives empty path `""` | Falls through to `NORMAL` priority (no match for `CRITICAL`, `LOW`, or `/api/v*`) |
| EC-18 | Middleware called during lifespan startup (before yield) | FastAPI lifespan calls do not route through ASGI middleware; no shedding risk |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 20 Completeness Criteria verified via `test_add_load_shedding.py` passing
2. ✅ Test report shows 0 failed across structural and behavior test files
3. ✅ Tool execution time < 5 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-LS-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-LS-02)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-LS-03)
7. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
8. ✅ `LOAD_SHEDDING_*` settings live inside `class Settings` body with 4-space indentation (INV-LS-07)
9. ✅ `CRITICAL` requests never receive 429 under any load condition (INV-LS-04)
10. ✅ `LOW` requests receive `429 + Retry-After: 30` when `is_shedding()` is True (INV-LS-05)
11. ✅ `deque(maxlen=window_size)` used for bounded sliding window (INV-LS-06)
12. ✅ `DegradationTier` has exactly `NORMAL`, `TIER_1`, `TIER_2`, `TIER_3` members (CC-10)
13. ✅ `execution_time_ms > 0` on every return path including error (INV-LS-08)
14. ✅ Behavior tests B-01..B-10 pass against real ASGI app with `httpx.ASGITransport`
15. ✅ Developer can register `LoadSheddingMiddleware` in one line per `next_steps` guidance

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` passes
- [ ] `app/resilience/load_shedder.py` does NOT contain `"LoadShedder"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Resilience package

- [ ] `mkdir -p app/resilience`
- [ ] Write `app/resilience/__init__.py` (empty or minimal docstring)
- [ ] Write `app/resilience/load_shedder.py` via `_write_load_shedder` (`LoadShedder`, `_percentile`, `get_p99`, `is_shedding`, `record`, `get_load_shedder`)
- [ ] Write `app/resilience/priority.py` via `_write_priority` (`RequestPriority` enum, `classify_request`)
- [ ] Write `app/resilience/degradation.py` via `_write_degradation` (`DegradationTier` enum, `_DISABLED_IN_TIER` dict, `DegradationManager`, `is_feature_enabled`)

### 15.3 Middleware

- [ ] `mkdir -p app/middleware` (if missing)
- [ ] Write `app/middleware/load_shedding.py` via `_write_middleware` (`LoadSheddingMiddleware(BaseHTTPMiddleware)`)
- [ ] Middleware checks `settings.LOAD_SHEDDING_ENABLED` early-out
- [ ] Middleware short-circuits `CRITICAL` requests unconditionally before `is_shedding()` call
- [ ] Middleware returns `JSONResponse(status_code=429, ..., headers={"Retry-After": "30"})` for `LOW` when shedding
- [ ] Middleware records latency to `get_load_shedder().record(latency_ms)` for every passing request

### 15.4 Config patch

- [ ] Early-return if `"LOAD_SHEDDING_ENABLED" in src`
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent
- [ ] Emit `LOAD_SHEDDING_ENABLED: bool = True`
- [ ] Emit `LOAD_SHEDDING_P99_THRESHOLD_MS: float = 500.0`
- [ ] Emit `LOAD_SHEDDING_RECOVERY_WINDOW_S: float = 10.0`
- [ ] Fallback: insert before `settings = Settings()` if anchor missing
- [ ] Last-resort: append at EOF

### 15.5 Validation and result

- [ ] Loop over `files_created`; for every `.py` call `_assert_parses(p)`
- [ ] `_assert_parses` raises `SyntaxError` with file path on failure
- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` describe middleware, priority taxonomy, p99 window, and degradation tiers
- [ ] `next_steps` include `LOAD_SHEDDING_ENABLED`, middleware registration line, and threshold tuning guidance
- [ ] `execution_time_ms` set on all return branches: success, no_op, dry_run, prereq error, validation error

### 15.6 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists generated files and "why load shedding" rationale
- [ ] `add_load_shedding` docstring documents the `inp` parameter and return value

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/resilience/__init__.py",
    "/tmp/fixture/app/resilience/load_shedder.py",
    "/tmp/fixture/app/resilience/priority.py",
    "/tmp/fixture/app/resilience/degradation.py",
    "/tmp/fixture/app/middleware/load_shedding.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py"
  ],
  "notes": [
    "Load shedding added: LoadShedder (sliding-window p99), RequestPriority (CRITICAL/HIGH/NORMAL/LOW),",
    "DegradationManager (NORMAL/TIER_1/TIER_2/TIER_3), LoadSheddingMiddleware.",
    "CRITICAL requests always pass. LOW requests receive 429 + Retry-After: 30 when shedding active.",
    "p99 window_size=100, threshold=500ms, recovery=10s."
  ],
  "next_steps": [
    "Set LOAD_SHEDDING_ENABLED=true in .env.",
    "Register LoadSheddingMiddleware in app/main.py: app.add_middleware(LoadSheddingMiddleware).",
    "Tune LOAD_SHEDDING_P99_THRESHOLD_MS and LOAD_SHEDDING_RECOVERY_WINDOW_S for your SLOs.",
    "Verify: run load test and observe 429 responses for /analytics paths under overload.",
    "Extend classify_request() in app/resilience/priority.py to add project-specific paths."
  ],
  "execution_time_ms": 87
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "LoadShedder already present — load shedding already enabled, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 4
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/resilience/ package (load_shedder.py, priority.py, degradation.py),",
    "         app/middleware/load_shedding.py (LoadSheddingMiddleware).",
    "         Config: LOAD_SHEDDING_ENABLED, LOAD_SHEDDING_P99_THRESHOLD_MS=500.0, LOAD_SHEDDING_RECOVERY_WINDOW_S=10.0.",
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
