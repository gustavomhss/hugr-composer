# TOOL-100: add_graceful_shutdown

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_graceful_shutdown` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, pydantic-settings, starlette |
| Signature | `add_graceful_shutdown(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and optional `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_graceful_shutdown", "description": "Add three-phase graceful shutdown (drain, complete in-flight, cleanup) with SIGTERM/SIGINT handling to FastAPI services.", "tags": ["extend", "infrastructure"], "entry": "add_graceful_shutdown"}` |
| Files created (typical) | 4–5 — `app/lifecycle/__init__.py`, `app/lifecycle/shutdown.py`, `app/lifecycle/health_gate.py`, `app/middleware/__init__.py`, `app/middleware/shutdown.py` |
| Files modified (typical) | 1–2 — `app/core/config.py`, optionally `app/main.py` |

---

## 2. Purpose

The `fastapi_add_graceful_shutdown` tool installs a three-phase graceful shutdown infrastructure into a FastAPI project. Kubernetes and container orchestrators terminate pods by sending `SIGTERM` then `SIGKILL` after a configurable grace period (commonly 30 seconds). Without graceful shutdown, receiving `SIGTERM` kills the process immediately — every in-flight HTTP request is aborted mid-response, clients see random 5xx errors, and rolling deployments become noisy with false-positive alerts. Graceful shutdown transforms this abrupt termination into a controlled, observable wind-down that zero-downtimes require.

The design centers on three sequential phases. **Phase 1 — Drain**: on `SIGTERM` or `SIGINT`, `GracefulShutdown._on_signal()` sets `_draining = True` and records `_drain_started_at`. From this instant, `ShutdownMiddleware` returns `503 Service Unavailable + Retry-After: 10` for all newly arriving requests. `/healthz` and `/readyz` are excluded via `_PASS_THROUGH_PATHS = frozenset({"/healthz", "/readyz"})` — but `ShutdownHealthGate.is_healthy()` independently returns `False`, so load balancers that re-check health after seeing the first 503 will remove the pod from their pool within one probe interval. This dual-signal design ensures traffic is re-routed before the process exits. **Phase 2 — Complete**: `wait_complete()` loops polling `_in_flight > 0` every 100 ms until either all requests finish or `SHUTDOWN_TIMEOUT_SECONDS` elapses. `decrement_in_flight()` uses `max(0, self._in_flight - 1)` to prevent negative counts — a critical guard when exception paths skip the normal `try/finally` in middleware. **Phase 3 — Cleanup**: after draining, `wait_complete()` iterates `_cleanup_callbacks`, calling each in sequence. Callers register DB pool closes, Redis disconnects, and arq worker stops with `add_cleanup(cb)`.

The singleton `get_graceful_shutdown()` factory seeds configuration from `SHUTDOWN_DRAIN_SECONDS` and `SHUTDOWN_TIMEOUT_SECONDS` environment variables. Signal registration uses `loop.add_signal_handler(SIGTERM, ...)` on Unix and falls back to `signal.signal()` on Windows where the asyncio event loop does not support `add_signal_handler`. The entire system is designed so that the FastAPI lifespan context manager is the only integration point: call `shutdown.register()` on startup, and `await shutdown.wait_complete()` on teardown.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 3 | shutdown.py, health_gate.py, middleware/shutdown.py (CC-04) |
| Files modified | ≥ 1 | Config patch (CC-05) |
| Max function LOC | ≤ 50 | AST walk enforced |
| Drain detection latency | < 1 ms | In-process boolean check on `_draining` flag |
| 503 response for new requests during drain | < 1 ms | Short-circuit in `dispatch()` before `call_next` |
| `wait_complete()` poll interval | 100 ms | Low-overhead asyncio.sleep loop |
| `SHUTDOWN_TIMEOUT_SECONDS` default | 30.0 s | Covers most long-running requests |
| `SHUTDOWN_DRAIN_SECONDS` default | 5.0 s | Matches typical LB probe interval |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
app/
├── main.py              # No SIGTERM handler, no drain logic
├── core/
│   └── config.py        # No SHUTDOWN_* settings
└── (no lifecycle/ dir)
```

Pod receives `SIGTERM` → process killed instantly → all in-flight requests aborted → clients see HTTP 5xx during rolling deploys.

### 4.2 GracefulShutdown (three phases): AFTER

```python
# app/lifecycle/shutdown.py
"""Graceful shutdown coordinator — drain, complete, cleanup."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

logger = logging.getLogger(__name__)
_shutdown: "GracefulShutdown | None" = None


class GracefulShutdown:
    """Coordinates a clean process shutdown across three phases."""

    def __init__(self, drain_seconds: float = 5.0, timeout_seconds: float = 30.0) -> None:
        self.drain_seconds = drain_seconds
        self.timeout_seconds = timeout_seconds
        self._draining = False
        self._shutting_down = False
        self._in_flight = 0
        self._drain_started_at: float | None = None
        self._cleanup_callbacks: list = []

    def register(self) -> None:
        """Install SIGTERM and SIGINT handlers on the event loop."""
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGTERM, self._on_signal)
            loop.add_signal_handler(signal.SIGINT, self._on_signal)
        except NotImplementedError:
            # Windows — event loop doesn't support add_signal_handler
            signal.signal(signal.SIGTERM, lambda *_: self._on_signal())
            signal.signal(signal.SIGINT, lambda *_: self._on_signal())

    def _on_signal(self) -> None:
        """Called by OS signal — begin drain phase."""
        if self._draining:
            return
        self._draining = True
        self._drain_started_at = time.monotonic()

    def is_draining(self) -> bool:
        return self._draining

    def increment_in_flight(self) -> None:
        self._in_flight += 1

    def decrement_in_flight(self) -> None:
        self._in_flight = max(0, self._in_flight - 1)  # negative guard

    def add_cleanup(self, callback) -> None:
        self._cleanup_callbacks.append(callback)

    async def wait_complete(self) -> None:
        """Wait for drain + in-flight completion + run cleanup callbacks."""
        if not self._draining:
            return
        await asyncio.sleep(self.drain_seconds)  # Phase 1: drain window
        deadline = time.monotonic() + self.timeout_seconds
        while self._in_flight > 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.1)  # Phase 2: complete in-flight
        for cb in self._cleanup_callbacks:
            try:
                await cb()           # Phase 3: cleanup
            except Exception:
                logger.warning("Cleanup callback raised", exc_info=True)
        self._shutting_down = True


def get_graceful_shutdown() -> GracefulShutdown:
    """Return the global GracefulShutdown singleton."""
    global _shutdown
    if _shutdown is None:
        _shutdown = GracefulShutdown(
            drain_seconds=float(os.getenv("SHUTDOWN_DRAIN_SECONDS", "5")),
            timeout_seconds=float(os.getenv("SHUTDOWN_TIMEOUT_SECONDS", "30")),
        )
    return _shutdown
```

### 4.3 ShutdownHealthGate: AFTER

```python
# app/lifecycle/health_gate.py
"""ShutdownHealthGate — returns 503 on /healthz during drain."""
from __future__ import annotations

from fastapi import HTTPException
from app.lifecycle.shutdown import get_graceful_shutdown


class ShutdownHealthGate:
    """Health check gate: returns 503 during shutdown drain phase."""

    def check(self) -> None:
        """Raise HTTPException(503) if shutdown is in progress."""
        if get_graceful_shutdown().is_draining():
            raise HTTPException(
                status_code=503,
                detail="Service is shutting down — retry after drain completes.",
                headers={"Retry-After": "10"},
            )

    def is_healthy(self) -> bool:
        """Return False when shutdown drain phase is active."""
        return not get_graceful_shutdown().is_draining()
```

### 4.4 ShutdownMiddleware: AFTER

```python
# app/middleware/shutdown.py
"""ASGI middleware that rejects new requests during drain."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.lifecycle.shutdown import get_graceful_shutdown

# Always let health probes through — health gate handles their 503 separately
_PASS_THROUGH_PATHS = frozenset({"/healthz", "/readyz"})


class ShutdownMiddleware(BaseHTTPMiddleware):
    """Reject new inbound requests during shutdown drain phase.

    In-flight requests (already past this middleware) are unaffected —
    they complete normally. The middleware tracks in-flight count via
    increment_in_flight() / decrement_in_flight() in a try/finally block.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        sd = get_graceful_shutdown()
        if sd.is_draining() and request.url.path not in _PASS_THROUGH_PATHS:
            return JSONResponse(
                status_code=503,
                content={"detail": "Service is shutting down — please retry."},
                headers={"Retry-After": "10"},
            )
        sd.increment_in_flight()
        try:
            return await call_next(request)
        finally:
            sd.decrement_in_flight()
```

### 4.5 Config patch: AFTER

```python
# app/core/config.py (fragment — injected by tool)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Graceful shutdown (TOOL-100)
    SHUTDOWN_DRAIN_SECONDS: float = 5.0
    SHUTDOWN_TIMEOUT_SECONDS: float = 30.0
```

### 4.6 FastAPI lifespan integration (caller pattern)

```python
# app/main.py — after tool runs
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.lifecycle.shutdown import get_graceful_shutdown
from app.middleware.shutdown import ShutdownMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    shutdown = get_graceful_shutdown()
    shutdown.register()          # installs SIGTERM + SIGINT handlers
    # register cleanup callbacks
    shutdown.add_cleanup(db.disconnect)
    shutdown.add_cleanup(redis_pool.aclose)
    yield                        # application running
    await shutdown.wait_complete()  # drain → complete → cleanup


app = FastAPI(lifespan=lifespan)
app.add_middleware(ShutdownMiddleware)
```

### 4.7 Testing graceful shutdown with a shell signal

```bash
# Start the server
uvicorn app.main:app --port 8000 &
SERVER_PID=$!

# Confirm healthy
curl -s http://localhost:8000/healthz   # {"status": "ok"}

# Send SIGTERM
kill -SIGTERM $SERVER_PID

# Health gate should now return 503
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/healthz  # 503

# New business requests rejected
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/items  # 503

# After drain completes, process exits cleanly (exit code 0)
wait $SERVER_PID; echo "exit: $?"  # exit: 0
```

### 4.8 Registering cleanup callbacks

```python
# Registering DB and Redis cleanup
from app.lifecycle.shutdown import get_graceful_shutdown
from app.database import get_db_engine
from app.cache import get_redis

shutdown = get_graceful_shutdown()

async def close_db():
    engine = get_db_engine()
    await engine.dispose()

async def close_redis():
    redis = await get_redis()
    await redis.aclose()

shutdown.add_cleanup(close_db)
shutdown.add_cleanup(close_redis)
# Callbacks invoked in order during Phase 3
```

### 4.9 Windows fallback signal handling

```python
# On Windows, asyncio event loop doesn't support add_signal_handler.
# The register() method automatically falls back:

try:
    loop.add_signal_handler(signal.SIGTERM, self._on_signal)
    loop.add_signal_handler(signal.SIGINT, self._on_signal)
except NotImplementedError:
    # Windows path
    signal.signal(signal.SIGTERM, lambda *_: self._on_signal())
    signal.signal(signal.SIGINT, lambda *_: self._on_signal())
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent on second run | `"GracefulShutdown" in lifecycle/shutdown.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `Path.write_text()` |
| QS-3 | All `.py` AST-parse clean | `_assert_parses` loop after creation |
| QS-4 | No function > 50 LOC | AST walk over all generated files |
| QS-5 | `503 + Retry-After: 10` during drain | `ShutdownMiddleware.dispatch()` returns `JSONResponse(503, headers={"Retry-After": "10"})` |
| QS-6 | `/healthz` and `/readyz` always pass through | `_PASS_THROUGH_PATHS` frozenset check before drain logic |
| QS-7 | `decrement_in_flight()` never produces negative count | `max(0, self._in_flight - 1)` guard |
| QS-8 | Both `SIGTERM` and `SIGINT` handled | `loop.add_signal_handler` for both signals |
| QS-9 | Windows fallback via `signal.signal` | `except NotImplementedError` in `register()` |
| QS-10 | Config 4-space indent | `_patch_config` anchored on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-11 | `execution_time_ms` positive | `_elapsed_ms(start)` with `time.monotonic()` |
| QS-12 | `ShutdownHealthGate.is_healthy()` returns `False` during drain | `not get_graceful_shutdown().is_draining()` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run → `no_op` | `r2.status == "no_op"` | T-02 |
| CC-03 | `dry_run=True` → zero writes | `before_tree == after_tree` | T-03 |
| CC-04 | ≥ 3 files created | `len(files_created) >= 3` | T-04 |
| CC-05 | ≥ 1 file modified | `len(files_modified) >= 1` | T-05 |
| CC-06 | All `.py` in lifecycle + middleware parse | `ast.parse` loop | T-06 |
| CC-07 | No function > 50 LOC | AST walk | T-07 |
| CC-08 | `SHUTDOWN_DRAIN_SECONDS` in config, 4-space indent | Substring + indent check | T-08 |
| CC-09 | `shutdown.py` still parseable (parity check) | `ast.parse` on `shutdown.py` | T-09 |
| CC-10 | `health_gate.py` parseable | `ast.parse` on `health_gate.py` | T-10 |
| CC-11 | `class GracefulShutdown` defined | Symbol search in `shutdown.py` | T-11 |
| CC-12 | `SIGTERM`, `SIGINT`, `signal` all present in source | Substring checks | T-12 |
| CC-13 | `drain` or `is_draining` present in `shutdown.py` | Pattern check | T-13 |
| CC-14 | `ShutdownHealthGate` defined in `health_gate.py` | Symbol search | T-14 |
| CC-15 | `ShutdownMiddleware` defined in middleware file | Symbol search | T-15 |
| CC-16 | `503` and `Retry-After` in middleware source | Substring checks | T-16 |
| CC-17 | `in_flight` and `increment_in_flight` in `shutdown.py` | Pattern check | T-17 |
| CC-18 | `30` or `SHUTDOWN_TIMEOUT` present in `shutdown.py` | Timeout value check | T-18 |
| CC-19 | `execution_time_ms > 0` | Positive integer check | T-19 |
| CC-20 | `next_steps` list contains "shutdown" token | Token in joined string | T-20 |
| CC-21 | Second run leaves all `.py` parseable | `ast.parse` on all lifecycle + middleware files | T-21 |

---

## 7. Definition of Done (DoD)

- [ ] All CC-01 through CC-21 verified by `test_add_graceful_shutdown.py`
- [ ] `GracefulShutdown._on_signal()` sets `_draining = True`
- [ ] `ShutdownMiddleware` returns `503 + Retry-After: 10` for new requests during drain
- [ ] `/healthz` and `/readyz` always pass through `ShutdownMiddleware` regardless of drain state
- [ ] `decrement_in_flight()` uses `max(0, self._in_flight - 1)` — never negative
- [ ] Both `SIGTERM` and `SIGINT` handled in `register()`
- [ ] Windows fallback uses `signal.signal()` when `add_signal_handler` raises `NotImplementedError`
- [ ] `ShutdownHealthGate.is_healthy()` returns `False` when `is_draining() == True`
- [ ] `SHUTDOWN_TIMEOUT_SECONDS: float = 30.0` in generated `shutdown.py`
- [ ] Config fields use 4-space indent inside `class Settings` body
- [ ] `execution_time_ms` is a positive integer
- [ ] `MCP_TOOL` descriptor present in source module

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-GS-01 | Idempotent on re-run | Fingerprint `"GracefulShutdown"` in `lifecycle/shutdown.py` → `no_op` | T-02, T-21 |
| INV-GS-02 | `dry_run=True` never writes | Early return before `Path.write_text()` | T-03 |
| INV-GS-03 | All generated `.py` pass `ast.parse` | `_assert_parses` loop | T-06, T-21 |
| INV-GS-04 | `503 + Retry-After: 10` for new requests during drain | `ShutdownMiddleware.dispatch()` | T-16, B-03 |
| INV-GS-05 | `/healthz` and `/readyz` ALWAYS pass through | `_PASS_THROUGH_PATHS` frozenset | T-15, B-01 |
| INV-GS-06 | `_in_flight` counter never goes negative | `max(0, self._in_flight - 1)` in `decrement_in_flight()` | B-05 |
| INV-GS-07 | `ShutdownHealthGate.is_healthy()` returns `False` during drain | `not get_graceful_shutdown().is_draining()` | B-04 |
| INV-GS-08 | Config fields MUST be inside `class Settings` body | 4-space indent enforcement | T-08 |
| INV-GS-09 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` | T-19 |
| INV-GS-10 | Both SIGTERM and SIGINT handled | Two signal registrations in `register()` | T-12 |

---

## 9. User Stories

### 9.1 Core installation (US-01 .. US-05)

**US-01: Successful install on fresh project**
- **Given:** A valid FastAPI project without graceful shutdown infrastructure
- **When:** `add_graceful_shutdown(ToolInput(project_dir="/path"))` is called
- **Then:** `result.status == "success"`, `len(result.files_created) >= 3` (CC-01, CC-04)

**US-02: Idempotent CI re-run**
- **Given:** Graceful shutdown already installed (first run succeeded)
- **When:** The tool is called a second time
- **Then:** `result.status == "no_op"`, no files modified (INV-GS-01)

**US-03: Dry-run preview**
- **Given:** A valid project
- **When:** `add_graceful_shutdown(ToolInput(project_dir="/path", dry_run=True))` is called
- **Then:** `result.status == "success"`, filesystem is unchanged (INV-GS-02)

**US-04: All generated files are syntactically valid**
- **Given:** A tool run that returns `status="success"`
- **When:** Each `files_created` path is loaded with `ast.parse()`
- **Then:** No `SyntaxError` is raised (INV-GS-03)

**US-05: Config fields are properly indented**
- **Given:** Tool run succeeds
- **When:** `app/core/config.py` is read
- **Then:** `SHUTDOWN_DRAIN_SECONDS: float = 5.0` is present with 4-space indent inside `class Settings` body (CC-08)

### 9.2 Drain phase mechanics (US-06 .. US-10)

**US-06: Pod receives SIGTERM during rolling deploy**
- **Given:** Kubernetes sends `SIGTERM` to the pod
- **When:** `GracefulShutdown._on_signal()` fires
- **Then:** `is_draining()` returns `True`; new requests receive 503; in-flight requests complete (INV-GS-04)

**US-07: Load balancer health probe during drain passes through**
- **Given:** Service is draining
- **When:** `GET /healthz`
- **Then:** `ShutdownMiddleware` passes the request through — not blocked by drain 503 logic (INV-GS-05)

**US-08: Health gate signals load balancer to stop routing**
- **Given:** `is_draining() == True`
- **When:** Health endpoint calls `ShutdownHealthGate.is_healthy()`
- **Then:** Returns `False` → load balancer stops routing to this pod (INV-GS-07)

**US-09: Simultaneous SIGTERM and SIGINT — idempotent signal handler**
- **Given:** Both `SIGTERM` and then `SIGINT` are received in quick succession
- **When:** `_on_signal()` called twice
- **Then:** `_draining` is `True` after first call; second call is a no-op due to `if self._draining: return` guard

**US-10: New requests return 503 Retry-After during drain**
- **Given:** Service draining, new request arrives on a business route
- **When:** Request hits `ShutdownMiddleware`
- **Then:** `JSONResponse(503, headers={"Retry-After": "10"})` is returned immediately (INV-GS-04)

### 9.3 In-flight tracking and complete phase (US-11 .. US-15)

**US-11: In-flight counter incremented before `call_next`**
- **Given:** Service not draining, request arrives
- **When:** `ShutdownMiddleware.dispatch()` runs
- **Then:** `increment_in_flight()` is called before `call_next`, `decrement_in_flight()` called in `finally` block

**US-12: `decrement_in_flight()` never goes below zero**
- **Given:** `decrement_in_flight()` called more times than `increment_in_flight()`
- **When:** Counter is already at 0 and `decrement` is called again
- **Then:** `_in_flight` stays at 0 (INV-GS-06)

**US-13: `wait_complete()` waits for in-flight requests**
- **Given:** Service draining, 3 in-flight requests active
- **When:** `wait_complete()` is called concurrently
- **Then:** Function loops polling every 100 ms until `_in_flight == 0` or timeout

**US-14: `wait_complete()` enforces hard timeout**
- **Given:** `SHUTDOWN_TIMEOUT_SECONDS=1` and a long-running request
- **When:** `wait_complete()` is called
- **Then:** Loop exits after 1 s even if `_in_flight > 0`; warning is logged (CC-18)

**US-15: Cleanup callbacks invoked in Phase 3**
- **Given:** `add_cleanup(close_db)` and `add_cleanup(close_redis)` registered
- **When:** `wait_complete()` completes in-flight phase
- **Then:** `close_db()` runs first, then `close_redis()` — registration order preserved

### 9.4 Signal handling and platform compatibility (US-16 .. US-20)

**US-16: SIGTERM and SIGINT both registered on Unix**
- **Given:** Unix OS (Linux/macOS), event loop supports `add_signal_handler`
- **When:** `shutdown.register()` is called
- **Then:** Both `SIGTERM` and `SIGINT` are registered via `loop.add_signal_handler()` (CC-12)

**US-17: Windows fallback uses `signal.signal()`**
- **Given:** Windows OS where `loop.add_signal_handler()` raises `NotImplementedError`
- **When:** `shutdown.register()` is called
- **Then:** `signal.signal(SIGTERM, ...)` and `signal.signal(SIGINT, ...)` are used instead

**US-18: Singleton `get_graceful_shutdown()` returns same instance**
- **Given:** Multiple middleware and route handlers calling `get_graceful_shutdown()`
- **When:** All concurrent calls during the drain phase
- **Then:** All receive the same `GracefulShutdown` instance with consistent `_draining` state

**US-19: Environment variables configure drain and timeout**
- **Given:** `SHUTDOWN_DRAIN_SECONDS=10` and `SHUTDOWN_TIMEOUT_SECONDS=60` in environment
- **When:** `get_graceful_shutdown()` is called for the first time
- **Then:** `shutdown.drain_seconds == 10.0` and `shutdown.timeout_seconds == 60.0`

**US-20: `/readyz` passes through middleware like `/healthz`**
- **Given:** Service is draining
- **When:** `GET /readyz`
- **Then:** `ShutdownMiddleware` passes the request through — `_PASS_THROUGH_PATHS` includes both paths (INV-GS-05)

### 9.5 Ops and integration (US-21 .. US-25)

**US-21: `add_arq_worker` cleanup registered via `add_cleanup()`**
- **Given:** ARQ worker installed alongside graceful shutdown
- **When:** `shutdown.add_cleanup(worker_pool.aclose)` is called in lifespan
- **Then:** ARQ pool is closed during Phase 3 cleanup after all requests complete

**US-22: Second run is idempotent and leaves files parseable**
- **Given:** First run succeeded
- **When:** Tool runs a second time (no_op path), then all `.py` re-parsed
- **Then:** All lifecycle and middleware files pass `ast.parse()` (INV-GS-01, INV-GS-03)

**US-23: Compatible with `ChaosMiddleware`**
- **Given:** Both `ShutdownMiddleware` and `ChaosMiddleware` registered
- **When:** `SIGTERM` received and service drains
- **Then:** `ShutdownMiddleware` fires first (registered first), returning 503 before chaos can inject

**US-24: Load shedding compatibility**
- **Given:** `ShutdownMiddleware` and `LoadSheddingMiddleware` both active
- **When:** Service draining + high load
- **Then:** Shutdown 503 is returned by `ShutdownMiddleware` first; load shedding not reached

**US-25: `execution_time_ms` positive in all outcomes**
- **Given:** Tool called in any mode (success, no_op, dry_run, error)
- **When:** `result.execution_time_ms` is read
- **Then:** Value is an integer > 0 (INV-GS-09)

---

## 10. Test Plan

### 10.1 Structural tests (`test_add_graceful_shutdown.py`)

| # | Test ID | Test name | Expected |
|---|---------|-----------|----------|
| T-01 | CC-01 | `test_success_on_fresh_project` | `status="success"` |
| T-02 | CC-02 | `test_idempotent_second_run` | `status="no_op"` |
| T-03 | CC-03 | `test_dry_run_zero_writes` | Filesystem unchanged |
| T-04 | CC-04 | `test_files_created_count` | `len(files_created) >= 3` |
| T-05 | CC-05 | `test_files_modified_count` | `len(files_modified) >= 1` |
| T-06 | CC-06 | `test_lifecycle_py_files_parse` | All `.py` in `app/lifecycle/` parse |
| T-07 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk: max function body ≤ 50 |
| T-08 | CC-08 | `test_shutdown_config_fields_4space` | `SHUTDOWN_DRAIN_SECONDS` present, 4-space indent |
| T-09 | CC-09 | `test_shutdown_file_parseable` | `app/lifecycle/shutdown.py` parses |
| T-10 | CC-10 | `test_health_gate_parseable` | `app/lifecycle/health_gate.py` parses |
| T-11 | CC-11 | `test_graceful_shutdown_class` | `class GracefulShutdown` in `shutdown.py` |
| T-12 | CC-12 | `test_signal_handling` | `SIGTERM`, `SIGINT`, `signal` all in source |
| T-13 | CC-13 | `test_drain_detection` | `drain` and `is_draining` in `shutdown.py` |
| T-14 | CC-14 | `test_health_gate_class` | `ShutdownHealthGate` in `health_gate.py` |
| T-15 | CC-15 | `test_shutdown_middleware_class` | `ShutdownMiddleware` in `middleware/shutdown.py` |
| T-16 | CC-16 | `test_503_retry_after` | `503` and `Retry-After` in middleware source |
| T-17 | CC-17 | `test_in_flight_counter` | `in_flight` and `increment_in_flight` in source |
| T-18 | CC-18 | `test_timeout_constant` | `30` in `shutdown.py` |
| T-19 | CC-19 | `test_execution_time_positive` | `execution_time_ms > 0` |
| T-20 | CC-20 | `test_next_steps_mention_shutdown` | "shutdown" token in `" ".join(next_steps)` |
| T-21 | CC-21 | `test_second_run_files_still_parse` | All lifecycle + middleware `.py` parse after second invocation |

### 10.2 Behavior tests (`test_add_graceful_shutdown_behavior.py`)

| # | Test ID | Test name | Assertion |
|---|---------|-----------|-----------|
| B-01 | INV-GS-05 | `test_healthz_passes_through_during_drain` | `GET /healthz` → 200 even when `_draining=True` |
| B-02 | INV-GS-01 | `test_not_draining_on_startup` | `is_draining() == False` on fresh engine |
| B-03 | INV-GS-04 | `test_middleware_returns_503_during_drain` | Manually set `_draining=True`; next request → 503 |
| B-04 | INV-GS-07 | `test_health_gate_is_healthy_false_during_drain` | `is_healthy() == False` when `_draining=True` |
| B-05 | INV-GS-06 | `test_in_flight_counter_min_zero` | `decrement` below 0 → stays at 0 |
| B-06 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk on all generated files |
| B-07 | CC-08 | `test_config_4space_indent` | Fields inside `class Settings` body |
| B-08 | INV-GS-03 | `test_no_dead_imports_in_lifecycle_files` | AST walk for unused imports |
| B-09 | CC-12 | `test_both_signals_registered` | `SIGTERM` and `SIGINT` both in `register()` source |
| B-10 | QS-9 | `test_windows_fallback_in_source` | `NotImplementedError` in `register()` source |

---

## 11. Interaction Matrix

| Other tool | Interaction type | Notes |
|------------|-----------------|-------|
| `add_load_shedding` (TOOL-095) | ✅ Complementary | Both middleware; register `ShutdownMiddleware` before `LoadSheddingMiddleware` — drain checked first |
| `add_adaptive_timeouts` (TOOL-096) | ✅ Neutral | Timeout decorator wraps route handlers; unaffected by drain middleware |
| `add_bulkhead_isolation` (TOOL-097) | ✅ Complementary | Drain check runs before bulkhead semaphore acquisition |
| `add_retry_budget` (TOOL-098) | ✅ Neutral | Retry budget tracks outbound retries; unaffected by inbound drain logic |
| `add_chaos_testing` (TOOL-099) | ✅ Complementary | Chaos can test shutdown path — chaos errors confirm 503 returns correctly |
| `add_api_replay_debugger` (TOOL-101) | ✅ Neutral | Recorder middleware should be registered AFTER `ShutdownMiddleware` to avoid recording drain 503s |
| `add_anomaly_detector` (TOOL-102) | ✅ Complementary | 503 spike during drain detected as anomaly; validates alert suppression for planned shutdowns |
| `add_arq_worker` (TOOL-053) | ✅ Complementary | Register `worker_pool.aclose` via `add_cleanup()` in lifespan; ARQ pool closed in Phase 3 |
| `generate_project` | ✅ Prerequisite | Requires `app/core/config.py` with `class Settings` — generate project first |
| `add_healthcheck` | ✅ Required | `/healthz` and `/readyz` must exist for `_PASS_THROUGH_PATHS` exclusion to be meaningful |
| Second `add_graceful_shutdown` call | ✅ Idempotent | `no_op` — `GracefulShutdown` already present |
| Kubernetes rolling deploy | ✅ Target | `SIGTERM` → drain → complete → cleanup → process exit; LB removes pod during drain |
| Docker Compose `stop` | ✅ Target | Sends `SIGTERM` with grace period; graceful shutdown uses full grace window |

---

## 12. Rollback Procedure

### 12.1 Remove lifecycle package

```bash
rm -rf app/lifecycle/
```

### 12.2 Remove shutdown middleware

```bash
rm -f app/middleware/shutdown.py
# Remove __init__.py only if middleware/ dir is now empty:
[ -z "$(ls -A app/middleware/ 2>/dev/null)" ] && rm -rf app/middleware/
```

### 12.3 Restore config

```bash
git checkout HEAD -- app/core/config.py
```

Or manually remove `SHUTDOWN_DRAIN_SECONDS` and `SHUTDOWN_TIMEOUT_SECONDS` fields from `app/core/config.py`.

### 12.4 Remove wiring from `main.py`

```bash
git checkout HEAD -- app/main.py
```

Or manually remove:
- `from app.lifecycle.shutdown import get_graceful_shutdown`
- `from app.middleware.shutdown import ShutdownMiddleware`
- `app.add_middleware(ShutdownMiddleware)`
- The `shutdown.register()` and `await shutdown.wait_complete()` calls in lifespan

### 12.5 Verify rollback

```bash
python -c "from app.main import app; print('OK')"
pytest tests/ -x --tb=short
```

### 12.6 Re-run to restore

```bash
python -c "
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_graceful_shutdown import add_graceful_shutdown
r = add_graceful_shutdown(ToolInput(project_dir='$(pwd)'))
print(r.status, r.files_created)
"
```

---

## 13. Edge Cases

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| EC-01 | `"GracefulShutdown"` already in `app/lifecycle/shutdown.py` | `status="no_op"`, no files modified |
| EC-02 | `dry_run=True` on any valid project | `status="success"`, zero writes |
| EC-03 | `decrement_in_flight()` called more times than `increment` | `_in_flight` stays at 0 — `max(0, ...)` guard |
| EC-04 | `wait_complete()` timeout exceeded with in-flight > 0 | Loop exits; warning logged; process continues to Phase 3 cleanup |
| EC-05 | Windows process (`NotImplementedError`) | Falls back to `signal.signal()` for both SIGTERM and SIGINT |
| EC-06 | `app/core/config.py` missing `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | Fallback: append fields to end of `Settings` class body |
| EC-07 | Cleanup callback raises exception | Exception caught, warning logged, remaining callbacks still run |
| EC-08 | `SIGTERM` received while `_draining=True` (double signal) | `_on_signal()` guard `if self._draining: return` prevents duplicate drain start |
| EC-09 | `SHUTDOWN_DRAIN_SECONDS=0` set in environment | No drain sleep; drain phase completes immediately |
| EC-10 | `SHUTDOWN_TIMEOUT_SECONDS=0` set in environment | In-flight phase loop does not iterate; cleanup runs immediately |
| EC-11 | `app/main.py` already contains `graceful_shutdown` string | `_patch_main()` detects string and skips re-patching |
| EC-12 | `app/middleware/` directory does not exist | Tool creates it with `mkdir(parents=True, exist_ok=True)` |
| EC-13 | `/readyz` path not registered in app | `_PASS_THROUGH_PATHS` still excludes it from 503 drain; no route just means 404 |
| EC-14 | Concurrent requests during drain — race on `_in_flight` | GIL protects integer increment/decrement on CPython; PyPy needs explicit lock |
| EC-15 | Cleanup callback is synchronous (not `async def`) | `await cb()` raises `TypeError`; caught by `except Exception` in cleanup loop |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All CC-01 through CC-21 pass in `test_add_graceful_shutdown.py`
2. ✅ `GracefulShutdown._on_signal()` sets `_draining = True` on signal receipt
3. ✅ `ShutdownMiddleware` returns `503 + Retry-After: 10` for new non-passthrough requests during drain
4. ✅ `/healthz` and `/readyz` always pass through regardless of drain state
5. ✅ `decrement_in_flight()` uses `max(0, self._in_flight - 1)` — never negative
6. ✅ Both `SIGTERM` and `SIGINT` registered in `register()`
7. ✅ Windows fallback via `signal.signal()` present in `register()`
8. ✅ `ShutdownHealthGate.is_healthy()` returns `False` when `is_draining() == True`
9. ✅ `SHUTDOWN_TIMEOUT_SECONDS: float = 30.0` present in generated `shutdown.py`
10. ✅ Cleanup callbacks registered via `add_cleanup()` and called in Phase 3
11. ✅ All generated `.py` files pass `ast.parse()` with no `SyntaxError`
12. ✅ No generated function exceeds 50 LOC (AST walk)
13. ✅ Config fields have 4-space indent inside `class Settings` body
14. ✅ `execution_time_ms` is a positive integer in all result types

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks

- [ ] Validate `project_dir` with `validate_project_dir()` — return error if invalid
- [ ] Run `ensure_prerequisites(Prereq.CONFIG_SETTINGS, Prereq.REQUIREMENTS_TXT)` — return error if not met
- [ ] Check idempotency: `"GracefulShutdown" in (app/lifecycle/shutdown.py)` → return `no_op` if true
- [ ] If `dry_run=True`, return early success with note about what would be created

### 15.2 Lifecycle package creation

- [ ] Create `app/lifecycle/` directory with `mkdir(parents=True, exist_ok=True)`
- [ ] Create `app/lifecycle/__init__.py` if not exists (minimal docstring)
- [ ] Write `app/lifecycle/shutdown.py` via `_write_graceful_shutdown()`:
  - [ ] `GracefulShutdown` class with `drain_seconds`, `timeout_seconds`, `_draining`, `_in_flight`, `_cleanup_callbacks`
  - [ ] `register()` with `loop.add_signal_handler` + `NotImplementedError` Windows fallback
  - [ ] `_on_signal()` setting `_draining = True` with double-call guard
  - [ ] `is_draining()`, `increment_in_flight()`, `decrement_in_flight()` with `max(0, ...)` guard
  - [ ] `add_cleanup(callback)` and `wait_complete()` with 3-phase logic
  - [ ] `get_graceful_shutdown()` singleton seeding from environment vars
- [ ] Write `app/lifecycle/health_gate.py` via `_write_health_gate()`:
  - [ ] `ShutdownHealthGate.check()` raising `HTTPException(503)` when draining
  - [ ] `ShutdownHealthGate.is_healthy()` returning `not get_graceful_shutdown().is_draining()`

### 15.3 Middleware

- [ ] Create `app/middleware/` directory with `mkdir(parents=True, exist_ok=True)`
- [ ] Create `app/middleware/__init__.py` if not exists
- [ ] Write `app/middleware/shutdown.py` via `_write_shutdown_middleware()`:
  - [ ] `_PASS_THROUGH_PATHS = frozenset({"/healthz", "/readyz"})`
  - [ ] `ShutdownMiddleware(BaseHTTPMiddleware)` with `dispatch()` method
  - [ ] Drain check before pass-through: return `JSONResponse(503, headers={"Retry-After": "10"})`
  - [ ] `increment_in_flight()` before `call_next`, `decrement_in_flight()` in `finally`

### 15.4 Config and main.py patches

- [ ] Patch `app/core/config.py` via `_patch_config()`:
  - [ ] Skip if `"SHUTDOWN_DRAIN_SECONDS"` already in file
  - [ ] Inject `SHUTDOWN_DRAIN_SECONDS: float = 5.0` and `SHUTDOWN_TIMEOUT_SECONDS: float = 30.0`
  - [ ] Anchor insertion at `settings = Settings()` or append
- [ ] Patch `app/main.py` via `_patch_main()` (only if file exists):
  - [ ] Skip if `"GracefulShutdown"` or `"graceful_shutdown"` already in file
  - [ ] Append commented wiring instructions as code comments

### 15.5 Validation and result construction

- [ ] Loop over `files_created`: `ast.parse(path.read_text())` for all `.py` files — return error on `SyntaxError`
- [ ] Return `ToolResult` with `status="success"`, `files_created`, `files_modified`, `notes` (6 items), `next_steps` (6 items), `execution_time_ms`

---

## 16. Documentation Output

### 16.1 Success (fresh project)

```json
{
  "status": "success",
  "files_created": [
    "/project/app/lifecycle/__init__.py",
    "/project/app/lifecycle/shutdown.py",
    "/project/app/lifecycle/health_gate.py",
    "/project/app/middleware/__init__.py",
    "/project/app/middleware/shutdown.py"
  ],
  "files_modified": ["/project/app/core/config.py"],
  "notes": [
    "Graceful shutdown added: SIGTERM/SIGINT handled cleanly.",
    "Drain phase: ShutdownMiddleware returns 503 + Retry-After for new requests.",
    "ShutdownHealthGate: /healthz returns 503 during drain (stops LB traffic).",
    "Complete phase: waits up to SHUTDOWN_TIMEOUT_SECONDS for in-flight requests.",
    "Cleanup phase: closes DB pools, flushes queues, disconnects Redis.",
    "Config: SHUTDOWN_DRAIN_SECONDS (default 5), SHUTDOWN_TIMEOUT_SECONDS (default 30)."
  ],
  "next_steps": [
    "Set SHUTDOWN_DRAIN_SECONDS=5 in .env (time to drain new traffic).",
    "Set SHUTDOWN_TIMEOUT_SECONDS=30 in .env (max wait for in-flight).",
    "Wire GracefulShutdown.register() in the FastAPI lifespan context manager.",
    "Add ShutdownMiddleware to app.add_middleware() in main.py.",
    "Register ShutdownHealthGate with the existing /healthz endpoint.",
    "Test with: kill -SIGTERM <pid> and verify 503 on /healthz during drain."
  ],
  "execution_time_ms": 84
}
```

### 16.2 No-op (already installed)

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "GracefulShutdown already present — graceful shutdown already enabled, skipped."
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
    "[dry_run] Would create app/lifecycle/shutdown.py, app/lifecycle/health_gate.py, app/middleware/shutdown.py."
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
