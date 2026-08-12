---
spec_id: "TOOL-098"
tool_name: "add_retry_budget"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-RB-01"
  - "INV-RB-02"
  - "INV-RB-03"
  - "INV-RB-04"
  - "INV-RB-05"
  - "INV-RB-06"
  - "INV-RB-07"
  - "INV-RB-08"
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
# TOOL-098: add_retry_budget

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_retry_budget` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, pydantic-settings |
| Signature | `add_retry_budget(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_retry_budget", "description": "Add a retry budget system that limits retry amplification by tracking the ratio of retries to original requests in a sliding window.", "tags": ["extend", "infrastructure"], "entry": "add_retry_budget"}` |
| Files created (typical) | 4 — `app/resilience/__init__.py`, `app/resilience/retry_budget.py`, `app/resilience/retry_decorator.py`, `app/api/routes/retry_status.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_retry_budget` tool installs a retry budget system into a FastAPI project. Retries are a first-line resilience mechanism — when a transient failure occurs, a retry often succeeds. But unbounded retries are also the primary mechanism by which a partially-degraded service tips into full outage: every failed request spawns one or more retries, and those retries themselves fail and spawn more, creating exponential amplification of traffic at exactly the moment a dependency is already struggling. Exponential backoff helps but does not bound the total volume; a retry budget does.

A retry budget constrains retries to a configurable fraction of total calls within a sliding time window. The generated `RetryBudget` class maintains a `collections.deque`-based sliding window of call events — each event is a `(timestamp_float, is_retry_bool)` tuple. On each `can_retry()` call, the budget first runs `_evict(now)` to discard events older than `window_s` seconds, then computes `retry_count / max(1, total_count)`. If this ratio exceeds `RETRY_BUDGET_RATIO` (default 0.10, meaning at most 10% of calls can be retries in any window), `can_retry()` returns `False` and the caller must fail fast. A warm-up guard (`RETRY_BUDGET_MIN_REQUESTS`, default 10) prevents the budget from blocking retries before enough data has accumulated — during cold start or a quiet period, `can_retry()` always returns `True`.

The `@with_retry_budget("service")` decorator wraps any `async def` function: on success, it records a non-retry event via `budget.record(is_retry=False)`; on `Exception`, it checks `budget.can_retry()` — if the budget allows, it records `is_retry=True` and re-raises the exception for the caller to handle as a retry (backoff, fallback, etc.); if exhausted, it raises `BudgetExhaustedError` instead. `get_retry_budget(service)` is a per-service singleton factory. `all_budget_stats()` returns a snapshot of all tracked services for the `GET /resilience/retry-budget` status route. A `threading.Lock` guards deque mutations because `deque.popleft()` is not atomic when multiple threads also call `record()`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget; measured via `execution_time_ms` |
| Files created | ≥ 4 | retry_budget, retry_decorator, retry_status route, __init__ (CC-04) |
| Files modified | ≥ 1 | Config patch (CC-05) |
| Max function LOC | ≤ 50 | AST walk enforced (CC-07) |
| `can_retry()` overhead | < 0.1 ms | Deque scan bounded by `window_s` × request rate |
| `GET /resilience/retry-budget` | < 5 ms | In-process dict snapshot |
| `_evict()` amortised | O(k) | Removes only expired events from the front of the deque |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   └── core/config.py   # No RETRY_BUDGET_* fields
```

Every retry policy is bespoke — some handlers retry 3 times unconditionally, others retry forever, creating unbounded amplification. A dependency at 50% error rate generates 50% retries, which generate more errors, which generate more retries, until the service collapses.

### 4.2 RetryBudget (sliding-window ratio + threading.Lock): AFTER

```python
# app/resilience/retry_budget.py
"""Sliding-window retry budget to prevent retry amplification."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class BudgetExhaustedError(Exception):
    """Raised when the retry budget is exhausted for a service."""


_budgets: dict[str, "RetryBudget"] = {}
_budgets_lock = threading.Lock()


class RetryBudget:
    """Track retry/total ratio in a sliding window and enforce a limit."""

    def __init__(
        self,
        ratio: float = 0.10,
        window_s: float = 60.0,
        min_requests: int = 10,
    ) -> None:
        self._ratio = ratio
        self._window_s = window_s
        self._min_requests = min_requests
        self._events: deque[tuple[float, bool]] = deque()
        self._lock = threading.Lock()

    def record(self, is_retry: bool) -> None:
        """Record a call event (retry or original request)."""
        with self._lock:
            self._events.append((time.monotonic(), is_retry))

    def _evict(self, now: float) -> None:
        """Remove events older than window_s (called under lock)."""
        cutoff = now - self._window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def can_retry(self) -> bool:
        """Return True if a retry is allowed under the current budget."""
        with self._lock:
            now = time.monotonic()
            self._evict(now)
            events = list(self._events)
        total = len(events)
        if total < self._min_requests:
            return True  # warm-up guard
        retries = sum(1 for _, is_r in events if is_r)
        return (retries / total) < self._ratio

    def stats(self) -> dict[str, Any]:
        """Return current budget stats snapshot."""
        with self._lock:
            self._evict(time.monotonic())
            events = list(self._events)
        total = len(events)
        retries = sum(1 for _, is_r in events if is_r)
        ratio = retries / max(1, total)
        return {
            "total": total,
            "retries": retries,
            "ratio": ratio,
            "budget_ratio": self._ratio,
            "budget_ok": ratio < self._ratio,
        }


def get_retry_budget(
    service: str,
    ratio: float = 0.10,
    window_s: float = 60.0,
    min_requests: int = 10,
) -> RetryBudget:
    """Return (or create) the per-service RetryBudget singleton."""
    with _budgets_lock:
        if service not in _budgets:
            _budgets[service] = RetryBudget(
                ratio=ratio, window_s=window_s, min_requests=min_requests
            )
        return _budgets[service]


def all_budget_stats() -> dict[str, dict[str, Any]]:
    """Return stats for all tracked services."""
    with _budgets_lock:
        names = list(_budgets.keys())
    return {name: _budgets[name].stats() for name in names}
```

### 4.3 @with_retry_budget decorator: AFTER

```python
# app/resilience/retry_decorator.py
"""Decorator that checks retry budget before allowing exception to propagate."""
from __future__ import annotations

import functools
from typing import Any, Callable

from app.resilience.retry_budget import BudgetExhaustedError, get_retry_budget


def with_retry_budget(service: str) -> Callable:
    """Wrap an async function with retry budget enforcement.

    On success: records a non-retry event.
    On Exception: checks budget. If allowed, records retry event and
    re-raises so the caller can retry. If exhausted, raises
    BudgetExhaustedError.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            budget = get_retry_budget(service)
            try:
                result = await fn(*args, **kwargs)
                budget.record(is_retry=False)
                return result
            except Exception:
                if not budget.can_retry():
                    raise BudgetExhaustedError(
                        f"Retry budget exhausted for service '{service}'"
                    )
                budget.record(is_retry=True)
                raise
        return wrapper
    return decorator
```

### 4.4 Status route: AFTER

```python
# app/api/routes/retry_status.py
from fastapi import APIRouter
from app.resilience.retry_budget import all_budget_stats

router = APIRouter(prefix="/resilience", tags=["resilience"])


@router.get("/retry-budget")
async def retry_budget_status() -> dict:
    """Return current retry budget stats for all tracked services."""
    return {"services": all_budget_stats()}
```

### 4.5 Config patch: AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- retry budget settings — added by add_retry_budget tool ---
    RETRY_BUDGET_RATIO: float = 0.10
    RETRY_BUDGET_WINDOW_S: float = 60.0
    RETRY_BUDGET_MIN_REQUESTS: int = 10
```

### 4.6 Typical caller usage (after install)

```python
# Before: unbounded retries
async def charge_card(amount: int) -> dict:
    for attempt in range(3):
        try:
            return await stripe_api.charge(amount)
        except TransientError:
            if attempt == 2:
                raise

# After: budget-constrained retries
from app.resilience.retry_decorator import with_retry_budget

@with_retry_budget("stripe")
async def charge_card(amount: int) -> dict:
    return await stripe_api.charge(amount)

# Caller retries with budget check:
from app.resilience.retry_budget import BudgetExhaustedError
for _ in range(3):
    try:
        return await charge_card(amount)
        break
    except BudgetExhaustedError:
        raise  # budget exhausted — fail fast, do not retry
    except TransientError:
        continue  # budget ok — retry
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"RetryBudget" in retry_budget.py` → `no_op` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` AST-parses** | `_assert_parses` on each created file |
| QS-4 | **No function exceeds 50 LOC** | AST walk assertion |
| QS-5 | **`threading.Lock` guards deque mutations** | `with self._lock:` wraps `record()`, `_evict()`, and `can_retry()` reads |
| QS-6 | **`_evict` removes stale events correctly** | `deque.popleft()` loop discards events older than `window_s` |
| QS-7 | **`BudgetExhaustedError` raised, not `RuntimeError`** | Named exception class |
| QS-8 | **Config fields 4-space indent inside `class Settings`** | `_patch_config` anchor |
| QS-9 | **`execution_time_ms` positive on all paths** | `_elapsed_ms(start)` on every branch |
| QS-10 | **`GET /resilience/retry-budget` returns per-service stats** | Route backed by `all_budget_stats()` (CC-10) |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_retry_budget.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run returns `status="no_op"`, zero file ops | `r2.status == "no_op"` | T-02 |
| CC-03 | `dry_run=True` writes zero bytes | `before == after` | T-03 |
| CC-04 | ≥ 4 files created, all exist | `len(files_created) >= 4` | T-04 |
| CC-05 | ≥ 1 file modified (config), exists | `len(files_modified) >= 1` | T-05 |
| CC-06 | All `.py` in `app/resilience/` and `app/api/routes/` AST-parse | `ast.parse` loop | T-06 |
| CC-07 | No function > 50 LOC | AST walk `max_loc <= 50` | T-07 |
| CC-08 | `RETRY_BUDGET_RATIO` in config with 4-space indent | Substring + indent check | T-08 |
| CC-09 | `retry_budget.py` exists and AST-parses | File + `ast.parse` | T-09 |
| CC-10 | `retry_status.py` route uses `APIRouter` + `/retry-budget` path | File + symbols | T-10 |
| CC-11 | `class RetryBudget` defined | Symbol in `retry_budget.py` | T-11 |
| CC-12 | `BudgetExhaustedError` defined | Symbol in source | T-12 |
| CC-13 | `deque` + `_evict` (or `popleft`) in source | Sliding window pattern present | T-13 |
| CC-14 | `with_retry_budget` decorator defined | Symbol in `retry_decorator.py` | T-14 |
| CC-15 | `can_retry` method exists | Symbol in `retry_budget.py` | T-15 |
| CC-16 | `all_budget_stats` function exists | Symbol in `retry_budget.py` | T-16 |
| CC-17 | `get_retry_budget` factory exists | Symbol in `retry_budget.py` | T-17 |
| CC-N-1 | `execution_time_ms > 0` | Positive check | T-23 |
| CC-N | `next_steps` mentions retry budget | Token in lowercased join | T-24 |
| CC-LAST | Two runs → all `.py` parseable | `ast.parse` after two invocations | T-25 |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_retry_budget.py`
- [ ] `RetryBudget` uses `collections.deque` sliding window
- [ ] `threading.Lock` guards all deque mutations in `record()`, `_evict()`, and `can_retry()`
- [ ] `_evict` removes events older than `window_s` via `deque.popleft()` loop
- [ ] `can_retry()` returns `True` below `min_requests` warm-up guard
- [ ] `BudgetExhaustedError` raised (not swallowed) when budget is exhausted
- [ ] `@with_retry_budget` records on success AND checks/records on exception
- [ ] `GET /resilience/retry-budget` returns per-service stats
- [ ] Config fields with 4-space indent inside `class Settings`
- [ ] `execution_time_ms` positive on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-RB-01 | Tool ALWAYS idempotent on second invocation | `"RetryBudget" in retry_budget.py` → `no_op` | T-02, T-25 |
| INV-RB-02 | `dry_run=True` NEVER writes to disk | Early return | T-03 |
| INV-RB-03 | Every generated `.py` MUST parse | `_assert_parses` loop | T-06, T-25 |
| INV-RB-04 | `threading.Lock` MUST guard deque mutations | `with self._lock:` in `record` and `_evict` | Behavior B-07 |
| INV-RB-05 | Warm-up guard MUST allow retries below `min_requests` | `total < self._min_requests → True` | B-03 |
| INV-RB-06 | Budget exhausted MUST raise `BudgetExhaustedError`, not suppress | Named exception raised in decorator | T-12 |
| INV-RB-07 | Config fields MUST be inside `class Settings` with 4-space indent | `_patch_config` anchor | T-08 |
| INV-RB-08 | `execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` | T-23 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install retry budget into a clean FastAPI project**
- **As a** backend engineer whose service amplifies retry traffic during degradation
- **I want** one tool call to add retry budget infrastructure
- **So that** retry amplification is automatically capped at 10% of total calls
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_retry_budget(ToolInput(project_dir=...))`
- **Then:** `status="success"`; `files_created >= 4`; `files_modified >= 1` (CC-01, CC-04, CC-05)

**US-02: Idempotent CI re-run**
- **Given:** `retry_budget.py` already contains `RetryBudget`
- **When:** Second invocation
- **Then:** `status="no_op"`, zero writes (INV-RB-01); verified by T-02, T-25

**US-03: Preview with dry_run**
- **Given:** Fresh fixture project
- **When:** `dry_run=True`
- **Then:** `status="success"`; filesystem unchanged (INV-RB-02); verified by T-03

**US-04: Generated project stays auditable**
- **Given:** Tool emitted all retry budget files
- **When:** AST walk over `app/`
- **Then:** All functions ≤ 50 LOC (QS-4); verified by T-07

**US-05: Config binds from environment variables**
- **Given:** pydantic-settings reads `class Settings`
- **When:** `RETRY_BUDGET_RATIO=0.05` in `.env` and `Settings()` instantiates
- **Then:** `RETRY_BUDGET_RATIO` inside `class Settings` with 4-space indent (INV-RB-07)

### 9.2 Budget behaviour (US-06 .. US-13)

**US-06: Budget allows retries below threshold**
- **Given:** `RetryBudget(ratio=0.10)` with 100 events, 9 retries (ratio=0.09)
- **When:** `can_retry()` called
- **Then:** Returns `True` — ratio 9% < 10%

**US-07: Budget exhausted at threshold**
- **Given:** `RetryBudget(ratio=0.0)` — zero retries allowed; warm-up passed
- **When:** `can_retry()` called
- **Then:** Returns `False`; decorator raises `BudgetExhaustedError` (INV-RB-06)

**US-08: Warm-up guard allows retries during cold start**
- **Given:** `RetryBudget(min_requests=10)` with only 5 events recorded
- **When:** `can_retry()` called
- **Then:** Returns `True` regardless of retry ratio (INV-RB-05)

**US-09: Sliding window evicts stale events**
- **Given:** Budget with 100 events recorded 120 s ago; `window_s=60`
- **When:** `can_retry()` called
- **Then:** `_evict` removes all stale events; `total=0`; warm-up guard applies → returns `True` (clean slate)

**US-10: Status endpoint for ops**
- **Given:** `GET /resilience/retry-budget`
- **When:** Called
- **Then:** Returns `{"services": {"stripe": {"total": 100, "retries": 9, "ratio": 0.09, "budget_ratio": 0.10, "budget_ok": true}}}` (CC-10)

**US-11: Budget is per-service**
- **Given:** `get_retry_budget("stripe")` and `get_retry_budget("db")`
- **When:** `stripe` budget is exhausted
- **Then:** `db` budget is unaffected; `get_retry_budget("db").can_retry()` still returns `True`

**US-12: Decorator records success**
- **Given:** `@with_retry_budget("stripe")` wraps a function that succeeds
- **When:** Function returns normally
- **Then:** `budget.record(is_retry=False)` called; `retries` count unchanged

**US-13: Decorator records retry and re-raises**
- **Given:** `@with_retry_budget("stripe")` wraps a function that raises `TransientError`; budget allows retry
- **When:** Exception raised
- **Then:** `budget.record(is_retry=True)`; `TransientError` re-raised for caller to handle

### 9.3 Thread safety (US-14 .. US-17)

**US-14: Lock prevents concurrent deque corruption**
- **Given:** Multiple threads calling `record()` concurrently
- **When:** All records complete
- **Then:** All events present; no `RuntimeError` from concurrent deque modification (INV-RB-04)

**US-15: `_evict` runs under lock**
- **Given:** Thread A calling `can_retry()` while thread B calling `record()`
- **When:** Both execute concurrently
- **Then:** `_evict` runs inside the lock; no race between eviction and appending

**US-16: `_budgets` dict protected by `_budgets_lock`**
- **Given:** Two coroutines calling `get_retry_budget("stripe")` simultaneously
- **When:** First call creates the budget; second call arrives before first completes
- **Then:** `_budgets_lock` ensures only one `RetryBudget` is created; both callers get the same instance

**US-17: Singleton budget stable across coroutine yields**
- **Given:** `asyncio` event loop yields between `get_retry_budget` and `budget.can_retry()`
- **When:** Another coroutine modifies the same budget's deque during the yield
- **Then:** Lock at `can_retry()` entry ensures consistent snapshot

### 9.4 Code quality (US-18 .. US-22)

**US-18: No optional SDKs at module top-level**
- **Given:** `retry_budget.py`, `retry_decorator.py`
- **When:** Modules imported
- **Then:** Only `threading`, `time`, `collections.deque`, `functools` at module scope

**US-19: Second run does not corrupt the project**
- **Given:** First run completed
- **When:** Second run executes
- **Then:** `status="no_op"`; all `.py` parse (CC-LAST)

**US-20: Tool reports execution time**
- **Given:** Any invocation path
- **When:** `result.execution_time_ms` read
- **Then:** Positive integer (CC-N-1)

**US-21: next_steps guides developer**
- **Given:** Success return
- **When:** `result.next_steps` inspected
- **Then:** Contains `"retry_budget"` and decorator usage example (CC-N)

**US-22: Error on missing project_dir**
- **Given:** `inp.project_dir` missing
- **When:** Tool called
- **Then:** `status="error"` with `execution_time_ms > 0`

### 9.5 Operator and integration (US-23 .. US-25)

**US-23: Combine with adaptive timeouts**
- **As a** developer stacking timeout and retry budget
- **Given:** `@adaptive_timeout("db")` inside `@with_retry_budget("db")`
- **When:** DB call times out → decorator retries; budget checked
- **Then:** Adaptive timeout records latency on success; retry budget tracks retry ratio; both cooperate without conflict

**US-24: Monitor retry amplification events**
- **As an** SRE watching service health
- **Given:** Dependency at 30% error rate; budget exhausted (ratio > 0.10)
- **When:** Dashboard polls `GET /resilience/retry-budget`
- **Then:** `budget_ok: false` alerts ops team that amplification is occurring; action: increase capacity or throttle upstream

**US-25: Tune budget per service SLO**
- **As a** developer setting per-service budget ratios
- **Given:** Stripe charges are critical (10% retry allowed); analytics writes are low-value (2% retry allowed)
- **When:** `get_retry_budget("stripe", ratio=0.10)` and `get_retry_budget("analytics", ratio=0.02)`
- **Then:** Each service has an independent budget tuned to its criticality

---

## 10. Test Plan

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `rb_t01` | `add_retry_budget(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `rb_t02`; run once | Run second time | `r2.status == "no_op"`; empty lists (CC-02) |
| T-03 | `test_dry_run` | Fixture `rb_t03`; snapshot `.py` | `dry_run=True` | Byte-identical fs (CC-03) |
| T-04 | `test_files_created_count` | Fixture `rb_t04` | Run tool | `len(files_created) >= 4`; all exist (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `rb_t05` | Run tool | `len(files_modified) >= 1`; all exist (CC-05) |

### 10.2 Category B — Code quality (T-06 .. T-08)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture; run tool | `ast.parse` all `.py` in resilience + routes | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture; run tool | AST walk `app/` | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture; run tool | Read `config.py` | `RETRY_BUDGET_RATIO` present; 4-space indent (CC-08) |

### 10.3 Category C — Domain modules (T-09 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-09 | `test_retry_budget_file` | Fixture; run tool | File exists + `ast.parse` | `retry_budget.py` parseable (CC-09) |
| T-10 | `test_retry_status_route` | Fixture; run tool | Read `retry_status.py` | `APIRouter` + `/retry-budget` path (CC-10) |
| T-11 | `test_class_retry_budget` | Fixture; run tool | Read `retry_budget.py` | `"class RetryBudget"` present (CC-11) |
| T-12 | `test_budget_exhausted_error` | Fixture; run tool | Read `retry_budget.py` | `"BudgetExhaustedError"` present (CC-12) |
| T-13 | `test_sliding_window_deque` | Fixture; run tool | Read `retry_budget.py` | `"deque"` + `"_evict"` or `"popleft"` present (CC-13) |
| T-14 | `test_with_retry_budget_decorator` | Fixture; run tool | Read `retry_decorator.py` | `"with_retry_budget"` present (CC-14) |
| T-15 | `test_can_retry` | Fixture; run tool | Read `retry_budget.py` | `"can_retry"` method present (CC-15) |
| T-16 | `test_all_budget_stats` | Fixture; run tool | Read `retry_budget.py` | `"all_budget_stats"` present (CC-16) |
| T-17 | `test_get_retry_budget` | Fixture; run tool | Read `retry_budget.py` | `"get_retry_budget"` present (CC-17) |

### 10.4 Category D — Meta (T-23 .. T-25)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-23 | `test_execution_time_recorded` | Fixture; run tool | Read `result.execution_time_ms` | `> 0` (CC-N-1) |
| T-24 | `test_next_steps_present` | Fixture; run tool | Inspect `result.next_steps` | Contains retry budget token (CC-N) |
| T-25 | `test_idempotent_project_still_parses` | Fixture; run twice | `ast.parse` all `.py` | No `SyntaxError` (CC-LAST) |

### 10.5 Behavior tests (B-01 .. B-08)

| # | Test | Assertion |
|---|------|-----------|
| B-01 | `test_b01_healthz_returns_200` | `/healthz` → 200 |
| B-02 | `test_b02_status_route` | `GET /resilience/retry-budget` → 200 + `services` key |
| B-03 | `test_b03_can_retry_true_below_ratio` | Budget allows retries when ratio < threshold |
| B-04 | `test_b04_budget_exhausted_at_zero_ratio` | `BudgetExhaustedError` when `ratio=0.0` after warm-up |
| B-05 | `test_b05_all_functions_under_50_loc` | All functions ≤ 50 LOC |
| B-06 | `test_b06_config_4_space_indent` | `RETRY_BUDGET_RATIO` line starts with 4 spaces |
| B-07 | `test_b07_no_optional_sdk_at_top_level` | No external deps at module scope |
| B-08 | `test_b08_warm_up_guard` | `can_retry()` returns `True` below `min_requests` |

### 10.6 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_retry_budget.py -v
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_retry_budget_behavior.py -v
```

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_load_shedding` (TOOL-095) | No | ✅ Complementary | Shed before retry; retry budget limits amplification from retries of shed requests |
| `add_adaptive_timeouts` (TOOL-096) | No | ✅ Compatible | `TimeoutError` → retry → budget check; retry budget counts timeout retries |
| `add_bulkhead_isolation` (TOOL-097) | No | ✅ Compatible | Bulkhead full (503) → retry → budget check; budget prevents retry storm |
| `add_chaos_testing` (TOOL-099) | No | ✅ Compatible | Chaos-injected errors validate that retry budget fires correctly |
| `add_graceful_shutdown` (TOOL-100) | No | ✅ Compatible | During shutdown drain, new retries are rejected by middleware before reaching budget |
| `add_circuit_breaker` | No | ✅ Compatible | Open breaker → short-circuit before retry; budget not consumed on breaker-open |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Worker task retry (`max_tries`) is separate from HTTP request retry budget; can share a budget for external API calls made inside tasks |
| `add_anomaly_detector` (TOOL-102) | No | ✅ Compatible | Anomaly detector sees elevated error rate when budget is exhausted; alerts operator |
| `add_event_driven` | No | ✅ Compatible | Event publishing retries can use `@with_retry_budget("event_bus")` |
| `add_webhook_sender` | No | ✅ Compatible | `webhook_retry_task` can use `@with_retry_budget("webhook_endpoint")` |
| `add_multi_tenancy` | No | ⚠️ Caveat | Per-tenant budget isolation: `get_retry_budget(f"stripe:{tenant_id}")` for tenant-scoped rate limiting |
| `add_cache_layer` | No | ✅ Compatible | Cache miss → DB call → `@with_retry_budget("db")`; cache hits do not consume budget |

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- app/core/config.py
rm -f app/resilience/retry_budget.py \
      app/resilience/retry_decorator.py \
      app/api/routes/retry_status.py
```

### 12.2 Decorator cleanup at call sites

Remove `@with_retry_budget("service")` decorators from all call sites that were manually added after installation.

### 12.3 Failure mode: partial write

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

### 12.4 Emergency: tighten budget without rollback

Set `RETRY_BUDGET_RATIO=0.0` in `.env` and restart. No retries will be allowed (after warm-up); budget exhausted state is immediate. Useful for stopping retry storms while the root cause is investigated.

### 12.5 Uninstall validator

```bash
test ! -f app/resilience/retry_budget.py \
  || (echo "retry_budget.py still present" && exit 1)
grep -q "RETRY_BUDGET_RATIO" app/core/config.py \
  && echo "config still patched" && exit 1
echo "rollback verified"
```

### 12.6 Re-install after rollback

```python
result = add_retry_budget(ToolInput(project_dir="..."))
assert result.status == "success"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | `retry_budget.py` already contains `RetryBudget` | `status="no_op"` (INV-RB-01) |
| EC-02 | `inp.dry_run=True` | `status="success"`, zero writes (INV-RB-02) |
| EC-03 | Fewer than `min_requests` events | `can_retry()` returns `True` regardless of ratio (INV-RB-05) |
| EC-04 | `ratio=0.0` after warm-up | First call to `can_retry()` returns `False`; `BudgetExhaustedError` raised |
| EC-05 | All events evicted (window expired) | Clean slate: `total=0`; warm-up guard → `can_retry()` returns `True` |
| EC-06 | Two threads call `record()` simultaneously | `threading.Lock` prevents corruption (INV-RB-04) |
| EC-07 | `window_s=0` | All events evicted on every `_evict` call; budget always warm-up state → always `True` |
| EC-08 | Config missing `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | Fallback before `settings = Settings()` or EOF |
| EC-09 | Config already contains `RETRY_BUDGET_RATIO` | `_patch_config` early-returns; no duplicate |
| EC-10 | Generated file fails `ast.parse` | `_assert_parses` raises `SyntaxError`; use rollback 12.3 |
| EC-11 | Tool run twice in CI | Second run `no_op`; project parseable (T-25) |
| EC-12 | `@with_retry_budget` applied to sync function | `await fn(...)` fails with `TypeError`; not a tool error |
| EC-13 | Budget singleton created before `min_requests` events | Warm-up guard fires; retries allowed until enough data accumulates |
| EC-14 | `RETRY_BUDGET_RATIO=1.0` (allow all retries) | `can_retry()` always returns `True` after warm-up; budget effectively disabled |
| EC-15 | `all_budget_stats()` called with zero registered services | Returns empty dict `{}`; no `KeyError` |
| EC-16 | `record(is_retry=True)` called before any `record(is_retry=False)` | Ratio = 1.0; if `total >= min_requests`, budget exhausted on next retry |
| EC-17 | Multiple services share the same `service` name string | They share one `RetryBudget` singleton — intended; document in next_steps |
| EC-18 | Project dir on a read-only filesystem | `_write_*` raises `PermissionError`; tool returns `status="error"` with message |
| EC-19 | `app/resilience/__init__.py` already exists (non-empty) | Tool overwrites with empty `__init__.py`; `no_op` check only guards `retry_budget.py` |
| EC-20 | `BudgetExhaustedError` not caught by caller | Propagates as `500` via FastAPI default handler; caller must handle explicitly |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 20 Completeness Criteria verified via `test_add_retry_budget.py` passing
2. ✅ Test report shows 0 failed
3. ✅ Tool execution time < 5 s
4. ✅ Second invocation returns `status="no_op"` (INV-RB-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-RB-02)
6. ✅ Every generated `.py` AST-parses cleanly (INV-RB-03)
7. ✅ No function exceeds 50 LOC (QS-4)
8. ✅ `threading.Lock` guards all deque mutations (INV-RB-04)
9. ✅ Warm-up guard allows retries below `min_requests` (INV-RB-05)
10. ✅ `BudgetExhaustedError` raised on exhaustion (INV-RB-06)
11. ✅ `GET /resilience/retry-budget` returns per-service stats (CC-10)
12. ✅ Config inside `class Settings` with 4-space indent (INV-RB-07)
13. ✅ `execution_time_ms > 0` on every path (INV-RB-08)
14. ✅ Behavior tests B-01..B-08 pass
15. ✅ EC-14..EC-20 edge cases documented and behavior verified
16. ✅ Section 15.6 observability guidance present in next_steps output

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` passes
- [ ] `app/resilience/retry_budget.py` does NOT contain `"RetryBudget"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return early

### 15.2 Resilience files

- [ ] `mkdir -p app/resilience`
- [ ] Write `app/resilience/__init__.py`
- [ ] Write `app/resilience/retry_budget.py` via `_write_retry_budget`:
  - [ ] `BudgetExhaustedError` exception class
  - [ ] `RetryBudget` with `__init__`, `record`, `_evict`, `can_retry`, `stats`
  - [ ] `threading.Lock` in `__init__`; `with self._lock:` in `record` and `can_retry`
  - [ ] `_evict` removes events where `event[0] < now - window_s`
  - [ ] Warm-up: `if total < self._min_requests: return True`
  - [ ] `get_retry_budget` per-service singleton with `_budgets_lock`
  - [ ] `all_budget_stats()` returns snapshot dict
- [ ] Write `app/resilience/retry_decorator.py` via `_write_retry_decorator`:
  - [ ] `with_retry_budget(service)` decorator
  - [ ] `@functools.wraps(fn)` preserves metadata
  - [ ] On success: `budget.record(is_retry=False)`
  - [ ] On exception: check `budget.can_retry()` → record `is_retry=True` and re-raise, or raise `BudgetExhaustedError`

### 15.3 Status route

- [ ] `mkdir -p app/api/routes` (if missing)
- [ ] Write `app/api/routes/retry_status.py` with `APIRouter(prefix="/resilience")` and `GET /retry-budget`

### 15.4 Config patch

- [ ] Early-return if `"RETRY_BUDGET_RATIO" in src`
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] 4-space indent for all three fields
- [ ] `RETRY_BUDGET_RATIO: float = 0.10`
- [ ] `RETRY_BUDGET_WINDOW_S: float = 60.0`
- [ ] `RETRY_BUDGET_MIN_REQUESTS: int = 10`

### 15.5 Validation and result

- [ ] `_assert_parses` on all created `.py` files
- [ ] Return `ToolResult` with `execution_time_ms=_elapsed_ms(start)`
- [ ] `notes` explain budget ratio, warm-up guard, sliding window
- [ ] `next_steps` include decorator usage example and ops monitoring guidance

### 15.6 Observability guidance (next_steps wording)

Ensure `next_steps` in the returned `ToolResult` includes all four of the following items so operators can act immediately after install:

1. **Set ratio in `.env`**: `RETRY_BUDGET_RATIO=0.10` — lower values protect downstream services more aggressively.
2. **Decorate retryable callers**: `@with_retry_budget('payment-service')` before every async function that calls an external service.
3. **Handle `BudgetExhaustedError`**: In each caller, catch `BudgetExhaustedError` and return a `503` rather than letting it propagate as `500`.
4. **Monitor the status endpoint**: Poll `GET /resilience/retry-budget` from your APM or alert on `ratio > 0.15` to catch cascading failure early.

---

## 16. Documentation Output

Example `ToolResult` JSON (success path):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/resilience/__init__.py",
    "/tmp/fixture/app/resilience/retry_budget.py",
    "/tmp/fixture/app/resilience/retry_decorator.py",
    "/tmp/fixture/app/api/routes/retry_status.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py"
  ],
  "notes": [
    "Retry budget added: RetryBudget with deque sliding window + threading.Lock.",
    "@with_retry_budget decorator checks budget before allowing retry.",
    "BudgetExhaustedError raised when retry ratio >= RETRY_BUDGET_RATIO (default 10%).",
    "Warm-up guard: retries always allowed until min_requests events recorded.",
    "Status: GET /resilience/retry-budget."
  ],
  "next_steps": [
    "Set RETRY_BUDGET_RATIO=0.10 in .env (or lower for stricter budgets).",
    "Decorate retryable calls: @with_retry_budget('payment-service').",
    "Handle BudgetExhaustedError in caller: fail fast instead of retrying.",
    "Monitor GET /resilience/retry-budget to detect amplification events."
  ],
  "execution_time_ms": 72
}
```

Example `no_op` return:

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "RetryBudget already present — retry budget already installed, skipped."
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
    "[dry_run] Would create app/resilience/retry_budget.py (RetryBudget, BudgetExhaustedError),",
    "         app/resilience/retry_decorator.py (@with_retry_budget decorator),",
    "         app/api/routes/retry_status.py (GET /resilience/retry-budget).",
    "         Config: RETRY_BUDGET_RATIO=0.10, WINDOW_S=60.0, MIN_REQUESTS=10.",
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
