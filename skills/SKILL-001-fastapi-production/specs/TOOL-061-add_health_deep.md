# TOOL-061: add_health_deep

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_health_deep` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, pydantic-settings, psutil>=6.0.0, redis[hiredis]>=5.0.0 (for Redis check), SQLAlchemy 2.0 (for DB check) |
| Signature | `add_health_deep(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_health_deep", "description": "Upgrade to production-grade deep health checks with HealthRegistry, dependency matrix, per-check latency, circuit-breaker degraded state, and /health/live + /health/ready + /health/deep endpoints.", "tags": ["extend", "infrastructure"], "entry": "add_health_deep"}` |
| Files created (typical) | 9 — `app/health/__init__.py`, `app/health/registry.py`, `app/health/models.py`, `app/health/checks/__init__.py`, `app/health/checks/database.py`, `app/health/checks/redis.py`, `app/health/checks/disk.py`, `app/health/checks/memory.py`, `app/api/routes/health_deep.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/main.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_health_deep` tool replaces the basic liveness stub (`/healthz` returning `{"status": "ok"}`) that most scaffolded FastAPI projects ship with a full production-grade health-check system. The typical scaffold endpoint returns 200 regardless of whether the database pool is exhausted, Redis has been unreachable for ten minutes, or the filesystem has no remaining inodes. Kubernetes uses `/health/ready` as the readiness gate: if that endpoint always returns 200, Kubernetes routes traffic to a pod that cannot actually serve requests, causing request failures to pile up until the pod's in-flight queue saturates and a cascading timeout occurs. The tool corrects this class of operational failure by generating a layered system of three endpoints backed by a real dependency-checking registry.

The `HealthRegistry` singleton holds a dictionary of named async check functions, each returning a `DependencyCheck` (name, status, latency_ms, details). Every check runs inside `asyncio.wait_for(timeout=timeout_ms/1000)` — no check can hang the readiness probe indefinitely. A circuit-breaker counter (`_failure_counts`) tracks consecutive failures per check and promotes the status from `unhealthy` to `degraded` after three consecutive failures, preventing alert flapping when a dependency is intermittently slow.

The three endpoints serve distinct consumers: `/health/live` is the liveness probe — it runs `run_liveness()` which always returns healthy unless the event loop is blocked, so Kubernetes restarts the pod only when the process is genuinely unresponsive. `/health/ready` runs only checks marked `critical=True` via `registry.register_check(..., critical=True)`, returning 503 if any critical dependency is unhealthy or degraded; this gates traffic routing. `/health/deep` runs all checks and returns the full dependency matrix with per-check latency, intended for dashboards, on-call tooling, and manual debugging; it also returns 503 if any check is `unhealthy`.

Four built-in checks are generated: `database_check` (executes `SELECT 1` and reads pool stats via the SQLAlchemy async engine), `redis_check` (pings Redis and collects `used_memory_human`, `connected_clients`, `redis_version` via `INFO`), `disk_check` (reads `psutil.disk_usage("/")` against `HEALTH_DISK_THRESHOLD_PCT`), and `memory_check` (reads `psutil.Process().memory_info().rss` against `HEALTH_MEMORY_THRESHOLD_MB`). All four are `async def` functions using deferred imports so they do not crash at module load if the dependency is unavailable.

The tool patches `app/core/config.py` with three tuning knobs (`HEALTH_CHECK_TIMEOUT_MS`, `HEALTH_DISK_THRESHOLD_PCT`, `HEALTH_MEMORY_THRESHOLD_MB`) anchored on the `settings = Settings()` sentinel, registers the `health_deep_router` in `app/main.py`, and adds `psutil>=6.0.0` to `requirements.txt`. The tool is idempotent: it detects `"HealthRegistry" in app/health/registry.py` on second run and returns `status="no_op"` without touching any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (T-20) |
| Files created | ≥ 9 | Health package (8 files) + deep route (1 file) — minimum required for a functional system (T-04) |
| Files modified | ≥ 2 | Config, main, requirements — at least two of these must exist (T-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/health/` subtree (T-07) |
| `/health/live` latency | < 5 ms | No I/O; pure event-loop liveness returning hardcoded `HealthStatus.HEALTHY` |
| `/health/ready` latency | < `HEALTH_CHECK_TIMEOUT_MS` + 1 s | Bounded by `asyncio.wait_for(timeout=timeout_ms/1000)` per critical check |
| `/health/deep` latency | < `HEALTH_CHECK_TIMEOUT_MS` + 1 s | All checks run concurrently via `asyncio.gather`; bounded by slowest check's timeout |
| Check timeout enforcement | = `HEALTH_CHECK_TIMEOUT_MS` / 1000 s | `asyncio.wait_for` hard wall-clock timeout per check; never blocks probe indefinitely |
| Circuit-breaker threshold | 3 failures | Status transitions from `unhealthy` to `degraded` after `_CIRCUIT_BREAKER_THRESHOLD = 3` consecutive failures |
| `database_check` latency | < 20 ms on healthy pool | Single `SELECT 1` roundtrip over existing pool connection |
| `redis_check` latency | < 20 ms on healthy Redis | `PING` + three `INFO` calls over existing Redis connection |
| `disk_check` latency | < 5 ms | `psutil.disk_usage` is a syscall; no network I/O |
| `memory_check` latency | < 2 ms | `psutil.Process().memory_info()` is a `/proc` read; no network I/O |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, basic /healthz stub or no health routes
│   ├── core/
│   │   └── config.py        # Settings class, no HEALTH_* fields
│   ├── api/
│   │   └── routes/          # No health_deep.py
│   └── ...
└── requirements.txt         # No psutil
```

Every health endpoint returns `{"status": "ok"}` unconditionally. Kubernetes readiness probe is satisfied even when the database pool is saturated, Redis is unreachable, or disk is 99% full. No per-dependency latency data is available. On-call engineers run `kubectl exec` to diagnose what is actually broken.

### 4.2 HealthRegistry (app/health/registry.py): AFTER

```python
# app/health/registry.py
"""HealthRegistry: register async checks and run them with timeouts."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from app.health.models import DependencyCheck, HealthReport, HealthStatus

logger = logging.getLogger(__name__)

_registry: "HealthRegistry | None" = None

_CIRCUIT_BREAKER_THRESHOLD = 3  # failures before marking degraded


class HealthRegistry:
    """Singleton registry for async health-check functions.

    Args:
        timeout_ms: Default per-check timeout in milliseconds.
    """

    def __init__(self, timeout_ms: int = 5000) -> None:
        self._checks: dict[str, dict[str, Any]] = {}
        self._failure_counts: dict[str, int] = {}
        self.timeout_ms = timeout_ms

    def register_check(
        self,
        name: str,
        check_fn: Callable[[], Coroutine[Any, Any, DependencyCheck]],
        *,
        critical: bool = False,
    ) -> None:
        """Register a named async check.

        Args:
            name: Unique check name (e.g. 'database', 'redis').
            check_fn: Async callable returning a DependencyCheck.
            critical: When True, failure blocks readiness probe.
        """
        self._checks[name] = {"fn": check_fn, "critical": critical}
        self._failure_counts.setdefault(name, 0)

    async def _run_one(self, name: str) -> DependencyCheck:
        """Execute a single check with timeout and circuit-breaker logic."""
        entry = self._checks[name]
        t0 = time.monotonic()
        try:
            result: DependencyCheck = await asyncio.wait_for(
                entry["fn"](),
                timeout=self.timeout_ms / 1000,
            )
            self._failure_counts[name] = 0
            return result
        except asyncio.TimeoutError:
            self._failure_counts[name] += 1
            lat = int((time.monotonic() - t0) * 1000)
            logger.warning("Health check '%s' timed out after %d ms", name, lat)
            status = self._circuit_status(name)
            return DependencyCheck(
                name=name, status=status, latency_ms=lat,
                details={"error": "timeout"},
            )
        except Exception as exc:  # noqa: BLE001
            self._failure_counts[name] += 1
            lat = int((time.monotonic() - t0) * 1000)
            logger.warning("Health check '%s' raised: %s", name, exc, exc_info=True)
            status = self._circuit_status(name)
            return DependencyCheck(
                name=name, status=status, latency_ms=lat,
                details={"error": str(exc)},
            )

    def _circuit_status(self, name: str) -> HealthStatus:
        """Return 'degraded' after threshold, else 'unhealthy'."""
        if self._failure_counts.get(name, 0) >= _CIRCUIT_BREAKER_THRESHOLD:
            return HealthStatus.DEGRADED
        return HealthStatus.UNHEALTHY

    async def run_all(self) -> HealthReport:
        """Run every registered check and return a full HealthReport."""
        results = await asyncio.gather(
            *[self._run_one(n) for n in self._checks],
            return_exceptions=False,
        )
        checks = list(results)
        overall = _aggregate_status(checks)
        return HealthReport(status=overall, checks=checks)

    async def run_readiness(self) -> HealthReport:
        """Run only critical checks (for /health/ready probe)."""
        names = [n for n, e in self._checks.items() if e["critical"]]
        results = await asyncio.gather(
            *[self._run_one(n) for n in names],
            return_exceptions=False,
        )
        checks = list(results)
        overall = _aggregate_status(checks)
        return HealthReport(status=overall, checks=checks)

    async def run_liveness(self) -> HealthReport:
        """Liveness check — always healthy unless process is stuck."""
        return HealthReport(status=HealthStatus.HEALTHY, checks=[])


def get_registry() -> HealthRegistry:
    """Return the process-wide HealthRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = HealthRegistry()
    return _registry
```

### 4.3 Health models (app/health/models.py): AFTER

```python
# app/health/models.py
"""Pydantic models for health-check API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthStatus(str):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DependencyCheck(BaseModel):
    """Result of a single dependency health check.

    Attributes:
        name: Dependency name (e.g. 'database', 'redis').
        status: One of 'healthy', 'degraded', 'unhealthy'.
        latency_ms: Round-trip time in milliseconds.
        details: Optional key/value metadata (pool stats, memory, etc.).
    """

    name: str
    status: str = HealthStatus.HEALTHY
    latency_ms: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class HealthReport(BaseModel):
    """Aggregated health report returned by /health endpoints.

    Attributes:
        status: Worst-case status across all checks.
        checks: Ordered list of individual DependencyCheck results.
    """

    status: str = HealthStatus.HEALTHY
    checks: list[DependencyCheck] = Field(default_factory=list)
```

### 4.4 Database check (app/health/checks/database.py): AFTER

```python
# app/health/checks/database.py
"""PostgreSQL connectivity + connection pool stats check."""

from __future__ import annotations

import logging
import time

from app.health.models import DependencyCheck, HealthStatus

logger = logging.getLogger(__name__)


async def database_check() -> DependencyCheck:
    """Check PostgreSQL connectivity and pool utilisation.

    Executes ``SELECT 1`` and collects active/idle/overflow counts
    from the SQLAlchemy async engine pool.

    Returns:
        DependencyCheck with pool stats in ``details``.
    """
    t0 = time.monotonic()
    try:
        from app.core.db import engine  # deferred to avoid import cycles

        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))

        pool = engine.pool
        details: dict = {
            "pool_size": getattr(pool, "size", lambda: 0)(),
            "checked_out": getattr(pool, "checkedout", lambda: 0)(),
            "overflow": getattr(pool, "overflow", lambda: 0)(),
            "checked_in": getattr(pool, "checkedin", lambda: 0)(),
        }
        latency = int((time.monotonic() - t0) * 1000)
        return DependencyCheck(
            name="database",
            status=HealthStatus.HEALTHY,
            latency_ms=latency,
            details=details,
        )
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning("Database health check failed: %s", exc)
        return DependencyCheck(
            name="database",
            status=HealthStatus.UNHEALTHY,
            latency_ms=latency,
            details={"error": str(exc)},
        )
```

### 4.5 Redis check (app/health/checks/redis.py): AFTER

```python
# app/health/checks/redis.py
"""Redis ping, memory usage, and connected-clients health check."""

from __future__ import annotations

import logging
import os
import time

from app.health.models import DependencyCheck, HealthStatus

logger = logging.getLogger(__name__)


async def redis_check() -> DependencyCheck:
    """Ping Redis and collect memory + client stats.

    Returns:
        DependencyCheck with ``used_memory_human``, ``connected_clients``,
        and ``redis_version`` in ``details``.
    """
    t0 = time.monotonic()
    try:
        from redis.asyncio import Redis  # deferred import

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = Redis.from_url(redis_url, decode_responses=True)
        try:
            await client.ping()
            info = await client.info("server")
            mem_info = await client.info("memory")
            client_info = await client.info("clients")
            details = {
                "redis_version": info.get("redis_version", "unknown"),
                "used_memory_human": mem_info.get("used_memory_human", "N/A"),
                "connected_clients": client_info.get("connected_clients", 0),
            }
        finally:
            await client.aclose()

        latency = int((time.monotonic() - t0) * 1000)
        return DependencyCheck(
            name="redis",
            status=HealthStatus.HEALTHY,
            latency_ms=latency,
            details=details,
        )
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning("Redis health check failed: %s", exc)
        return DependencyCheck(
            name="redis",
            status=HealthStatus.UNHEALTHY,
            latency_ms=latency,
            details={"error": str(exc)},
        )
```

### 4.6 Disk check (app/health/checks/disk.py): AFTER

```python
# app/health/checks/disk.py
"""Disk space health check using psutil."""

from __future__ import annotations

import logging
import os
import time

from app.health.models import DependencyCheck, HealthStatus

logger = logging.getLogger(__name__)


async def disk_check() -> DependencyCheck:
    """Check available disk space against a configured threshold.

    Uses ``psutil.disk_usage`` on the filesystem root.  Marks check as
    ``unhealthy`` when used percentage exceeds
    ``HEALTH_DISK_THRESHOLD_PCT`` (default 90 %).

    Returns:
        DependencyCheck with ``total_gb``, ``used_pct``, and ``free_gb``
        in ``details``.
    """
    t0 = time.monotonic()
    try:
        import psutil  # noqa: PLC0415

        threshold = int(os.getenv("HEALTH_DISK_THRESHOLD_PCT", "90"))
        usage = psutil.disk_usage("/")
        used_pct = usage.percent
        details = {
            "total_gb": round(usage.total / 1_073_741_824, 2),
            "used_pct": used_pct,
            "free_gb": round(usage.free / 1_073_741_824, 2),
            "threshold_pct": threshold,
        }
        status = HealthStatus.UNHEALTHY if used_pct >= threshold else HealthStatus.HEALTHY
        latency = int((time.monotonic() - t0) * 1000)
        return DependencyCheck(
            name="disk",
            status=status,
            latency_ms=latency,
            details=details,
        )
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning("Disk health check failed: %s", exc)
        return DependencyCheck(
            name="disk",
            status=HealthStatus.UNHEALTHY,
            latency_ms=latency,
            details={"error": str(exc)},
        )
```

### 4.7 Memory check (app/health/checks/memory.py): AFTER

```python
# app/health/checks/memory.py
"""Process memory (RSS) health check using psutil."""

from __future__ import annotations

import logging
import os
import time

from app.health.models import DependencyCheck, HealthStatus

logger = logging.getLogger(__name__)


async def memory_check() -> DependencyCheck:
    """Check process RSS against a configured threshold.

    Marks check as ``unhealthy`` when RSS exceeds
    ``HEALTH_MEMORY_THRESHOLD_MB`` (default 512 MB).

    Returns:
        DependencyCheck with ``rss_mb``, ``vms_mb``, and
        ``threshold_mb`` in ``details``.
    """
    t0 = time.monotonic()
    try:
        import os as _os

        import psutil  # noqa: PLC0415

        threshold_mb = int(_os.getenv("HEALTH_MEMORY_THRESHOLD_MB", "512"))
        proc = psutil.Process()
        mem = proc.memory_info()
        rss_mb = round(mem.rss / 1_048_576, 2)
        vms_mb = round(mem.vms / 1_048_576, 2)
        details = {
            "rss_mb": rss_mb,
            "vms_mb": vms_mb,
            "threshold_mb": threshold_mb,
        }
        status = (
            HealthStatus.UNHEALTHY if rss_mb >= threshold_mb else HealthStatus.HEALTHY
        )
        latency = int((time.monotonic() - t0) * 1000)
        return DependencyCheck(
            name="memory",
            status=status,
            latency_ms=latency,
            details=details,
        )
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning("Memory health check failed: %s", exc)
        return DependencyCheck(
            name="memory",
            status=HealthStatus.UNHEALTHY,
            latency_ms=latency,
            details={"error": str(exc)},
        )
```

### 4.8 Deep health route (app/api/routes/health_deep.py): AFTER

```python
# app/api/routes/health_deep.py
"""Deep health endpoints: /health/live, /health/ready, /health/deep."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.health.models import HealthReport, HealthStatus
from app.health.registry import get_registry

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthReport, summary="Liveness probe")
async def liveness() -> HealthReport:
    """Liveness probe — always 200 unless the process is stuck."""
    registry = get_registry()
    return await registry.run_liveness()


@router.get("/ready", response_model=HealthReport, summary="Readiness probe")
async def readiness(response: Response) -> HealthReport:
    """Readiness probe — checks all critical dependencies.

    Returns 503 when any critical check is unhealthy or degraded.
    """
    registry = get_registry()
    report = await registry.run_readiness()
    if report.status != HealthStatus.HEALTHY:
        response.status_code = 503
    return report


@router.get("/deep", response_model=HealthReport, summary="Full dependency matrix")
async def deep_check(response: Response) -> HealthReport:
    """Full dependency matrix — all checks with per-check latency."""
    registry = get_registry()
    report = await registry.run_all()
    if report.status == HealthStatus.UNHEALTHY:
        response.status_code = 503
    return report
```

### 4.9 Config patch (HEALTH_* fields injected)

```python
# app/core/config.py  (diff, added by _patch_config)
    # Health check tuning — added by add_health_deep tool
    HEALTH_CHECK_TIMEOUT_MS: int = 5000
    HEALTH_DISK_THRESHOLD_PCT: int = 90
    HEALTH_MEMORY_THRESHOLD_MB: int = 512
```

Anchored on `settings = Settings()` sentinel so the fields land inside the `Settings` class body with correct indentation and pydantic-settings picks them up from environment variables.

### 4.10 app/main.py patch (router import + include_router)

```python
# app/main.py  (diff, added by _patch_main)
from fastapi import FastAPI
from app.api.routes.health_deep import router as health_deep_router  # noqa: E402 — deep health

# Deep health checks — added by add_health_deep tool
app.include_router(health_deep_router)
```

### 4.11 Typical caller usage (after install)

```python
# app/startup.py — register checks at application boot
from app.health.registry import get_registry
from app.health.checks import database_check, redis_check, disk_check, memory_check

async def register_health_checks() -> None:
    registry = get_registry()
    registry.register_check("database", database_check, critical=True)
    registry.register_check("redis", redis_check, critical=True)
    registry.register_check("disk", disk_check, critical=False)
    registry.register_check("memory", memory_check, critical=False)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_health_deep` pre-flight checks `"HealthRegistry" in app/health/registry.py` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero files** | `add_health_deep` returns success+notes before any filesystem write when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` run on each created `.py` file; tool returns `status="error"` on `SyntaxError` |
| QS-4 | **No generated function exceeds 50 LOC** | Every function in `app/health/` and `app/api/routes/health_deep.py` kept small by construction; asserted by AST walk in test harness (T-07) |
| QS-5 | **All checks run with `asyncio.wait_for` timeout** | `_run_one` wraps every check call in `asyncio.wait_for(entry["fn"](), timeout=self.timeout_ms/1000)` — no check hangs indefinitely |
| QS-6 | **Circuit-breaker escalates `unhealthy` → `degraded` after 3 failures** | `_failure_counts[name]` increments on every exception; `_circuit_status` returns `DEGRADED` when count >= `_CIRCUIT_BREAKER_THRESHOLD` (3) |
| QS-7 | **`/health/ready` calls `run_readiness` (not `run_all`)** | `readiness` handler calls `registry.run_readiness()` which filters to `critical=True` checks only; verified by T-17 AST parse |
| QS-8 | **`/health/ready` and `/health/deep` return 503 on failure** | Both handlers set `response.status_code = 503` when `report.status != HealthStatus.HEALTHY` |
| QS-9 | **All checks use deferred imports** | `from app.core.db import engine` and `from redis.asyncio import Redis` are inside the `try` block to avoid crash at module load |
| QS-10 | **psutil is added to requirements.txt** | `_patch_requirements` appends `psutil>=6.0.0` if `"psutil"` absent; idempotent |
| QS-11 | **`HEALTH_*` config fields anchored on `settings = Settings()` sentinel** | `_patch_config` inserts block before `settings = Settings()` line so fields land inside `Settings` class body |
| QS-12 | **`app/health/__init__.py` re-exports all public symbols** | `_write_health_init` emits `from app.health.registry import HealthRegistry, get_registry` and model exports in `__all__` |
| QS-13 | **Failure counts reset to zero on success** | `_run_one` sets `self._failure_counts[name] = 0` on successful check return before returning the `DependencyCheck` |
| QS-14 | **`HealthReport.status` reflects worst-case across all checks** | `_aggregate_status` returns `UNHEALTHY` if any check is `UNHEALTHY`, then `DEGRADED` if any is `DEGRADED`, else `HEALTHY` |
| QS-15 | **Tool records execution time on every return path** | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches |
| QS-16 | **Next-steps mention psutil and env config** | `next_steps` list includes `"pip install 'psutil>=6.0.0'"` and env var guidance |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_health_deep.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent_returns_no_op`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run_writes_nothing`) |
| CC-04 | Tool creates at least 9 new files | `len(result.files_created) >= 9` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function in `app/health/` exceeds 50 LOC | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `app/core/config.py` gains `HEALTH_CHECK_TIMEOUT_MS`, `HEALTH_DISK_THRESHOLD_PCT`, `HEALTH_MEMORY_THRESHOLD_MB` | String scan on `config.py` | T-08 (`test_config_fields_patched`) |
| CC-09 | `requirements.txt` contains `psutil` | `"psutil" in content` of `requirements.txt` | T-09 (`test_requirements_patched`) |
| CC-10 | `app/health/registry.py` exists with `HealthRegistry`, `register_check`, `run_all`, `run_readiness`, `run_liveness` | File exists + substring checks | T-10 (`test_health_registry_created`) |
| CC-11 | `app/health/checks/database.py` contains `async def database_check` with `SELECT 1` | File exists + substring checks | T-11 (`test_db_check_created`) |
| CC-12 | `app/health/checks/redis.py` contains `async def redis_check` with `ping` and memory stats | File exists + substring checks | T-12 (`test_redis_check_created`) |
| CC-13 | `app/health/checks/disk.py` uses `psutil` and reads `HEALTH_DISK_THRESHOLD_PCT` | File exists + `"psutil" in content` + threshold check | T-13 (`test_disk_check_created`) |
| CC-14 | `app/health/checks/memory.py` uses `psutil.Process` and reads RSS | File exists + `"psutil" in content` + `"rss"` substring check | T-14 (`test_memory_check_created`) |
| CC-15 | `app/health/models.py` defines `HealthStatus`, `DependencyCheck`, `HealthReport` with `latency_ms` field | File exists + substring checks | T-15 (`test_health_models_created`) |
| CC-16 | `app/api/routes/health_deep.py` exposes `/live`, `/ready`, `/deep` | File exists + `"/live"`, `"/ready"`, `"/deep"` substring checks | T-16 (`test_deep_route_created`) |
| CC-17 | `/health/ready` handler calls `run_readiness`, NOT `run_all` | AST parse of `readiness` function body; `"run_all"` absent from function source | T-17 (`test_ready_route_runs_critical_only`) |
| CC-18 | `HealthRegistry._run_one` uses `asyncio.wait_for` with timeout | `"asyncio.wait_for" in content` of `registry.py` | T-18 (`test_timeout_in_checks`) |
| CC-19 | `app/main.py` references `health_deep` after patching | `"health_deep" in content` of `main.py` | T-19 (`test_routes_registered_in_main`) |
| CC-20 | `execution_time_ms` is a positive integer on success path | `result.execution_time_ms > 0` | T-20 (`test_execution_time_recorded`) |
| CC-21 | `next_steps` has ≥ 3 items and mentions `psutil` and env config | `len(result.next_steps) >= 3` and both tokens present | T-21 (`test_next_steps_present`) |
| CC-22 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-22 (`test_idempotent_project_still_parses`) |
| CC-23 | `HealthRegistry` implements circuit-breaker `degraded` state on repeated failures | `"degraded" in content.lower()` and `"_failure_counts"` present | T-23 (`test_circuit_breaker_in_registry`) |
| CC-24 | `app/health/__init__.py` re-exports `HealthRegistry`, `DependencyCheck`, `HealthReport` | File exists + all three names present | T-24 (`test_health_init_re_exports`) |

---

## 7. Definition of Done (DoD)

- [ ] All 24 Completeness Criteria verified by `test_add_health_deep.py`
- [ ] `add_health_deep.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_health_deep.py` detects `"HealthRegistry"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `HealthRegistry._run_one` wraps every check in `asyncio.wait_for(timeout=self.timeout_ms/1000)`
- [ ] Circuit-breaker: `_failure_counts[name]` increments on failure; resets to 0 on success; returns `DEGRADED` after 3 failures
- [ ] `/health/ready` handler calls `run_readiness()` — NOT `run_all()`
- [ ] `/health/ready` and `/health/deep` set `response.status_code = 503` when status is not `HEALTHY`
- [ ] All four built-in checks use deferred imports inside `try` block
- [ ] `_patch_config` anchors on `settings = Settings()` sentinel so fields land inside `Settings` class body
- [ ] `_patch_main` injects `health_deep_router` import and `app.include_router(health_deep_router)` idempotently
- [ ] `_patch_requirements` adds `psutil>=6.0.0` when absent
- [ ] `app/health/__init__.py` exports `HealthRegistry`, `get_registry`, `DependencyCheck`, `HealthReport`, `HealthStatus`
- [ ] `app/health/checks/__init__.py` exports all four check functions
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-HD-01 | Tool is ALWAYS idempotent on second invocation | Fingerprint check `"HealthRegistry" in registry_file.read_text()` short-circuits to `status="no_op"` | T-02, T-22 |
| INV-HD-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-HD-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path_str in files_created: if .py: ast.parse(p.read_text())` | T-06, T-22 |
| INV-HD-04 | Every registered check MUST run inside `asyncio.wait_for(timeout)` — no infinite hang | `_run_one` wraps `entry["fn"]()` in `asyncio.wait_for(entry["fn"](), timeout=self.timeout_ms / 1000)` | T-18 |
| INV-HD-05 | `/health/ready` MUST only run critical checks, NEVER `run_all` | `readiness` handler calls `registry.run_readiness()` exclusively | T-17 |
| INV-HD-06 | Failure count MUST increment on every exception and reset on success | `_run_one` increments `_failure_counts[name]` in both `TimeoutError` and generic `Exception` handlers; resets to 0 on success | T-23 |
| INV-HD-07 | `HEALTH_*` settings MUST live inside `class Settings` body | `_patch_config` inserts block before `settings = Settings()` sentinel | T-08 |
| INV-HD-08 | `HealthReport.status` MUST reflect worst-case across all child checks | `_aggregate_status` returns `UNHEALTHY` > `DEGRADED` > `HEALTHY` | T-10 |
| INV-HD-09 | `psutil>=6.0.0` MUST be added to `requirements.txt` | `_patch_requirements` appends when `"psutil"` absent | T-09 |
| INV-HD-10 | `app/health/__init__.py` MUST re-export all public symbols | `_write_health_init` emits `HealthRegistry`, `get_registry`, `DependencyCheck`, `HealthReport`, `HealthStatus` in `__all__` | T-24 |
| INV-HD-11 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-20 |
| INV-HD-12 | `next_steps` MUST reference `psutil` and env config so operators know post-install steps | Hard-coded strings in the `success` branch of `add_health_deep` | T-21 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install deep health checks into a clean FastAPI project**
- **As a** backend engineer preparing for production
- **I want** to run one tool call and get a full health-check system
- **So that** Kubernetes readiness probes gate traffic on real dependency health
- **Given:** A FastAPI project with `app/core/config.py` and `requirements.txt`
- **When:** `add_health_deep(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-HD-01)
  - `files_created` contains ≥ 9 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/health/registry.py` already contains `HealthRegistry`
- **When:** `add_health_deep(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-HD-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-HD-03)
  - Verified by T-02, T-22

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_health_deep(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-HD-02)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it
- **Given:** Tool just emitted `registry.py`, `checks/*.py`, `health_deep.py`
- **When:** I AST-walk `app/health/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

**US-05: Post-install operator knows what to do**
- **As a** developer who just ran the tool
- **I want** `next_steps` to list concrete actions
- **So that** I do not forget to install psutil or set env vars
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - `len(next_steps) >= 3` (CC-21)
  - Contains `"psutil"` and env guidance
  - Verified by T-21

### 9.2 Kubernetes integration (US-06 .. US-10)

**US-06: Liveness probe returns 200 always**
- **As a** Kubernetes operator
- **I want** `/health/live` to return 200 as long as the process runs
- **So that** Kubernetes restarts the pod only when the process is truly unresponsive
- **Given:** `HealthRegistry.run_liveness()` is called
- **When:** GET `/health/live`
- **Then:**
  - Returns `HealthReport(status="healthy", checks=[])` (QS-5)
  - HTTP 200 always
  - Verified by T-16

**US-07: Readiness probe returns 503 on critical dependency failure**
- **As a** Kubernetes operator
- **I want** `/health/ready` to return 503 when the database is down
- **So that** traffic is not routed to a pod that cannot serve requests
- **Given:** Database check registered as `critical=True`; database unreachable
- **When:** GET `/health/ready`
- **Then:**
  - `run_readiness()` runs only critical checks (INV-HD-05)
  - `report.status == "unhealthy"` → `response.status_code = 503` (QS-8)
  - Verified by T-17

**US-08: Deep endpoint exposes full dependency matrix**
- **As an** on-call engineer debugging a production issue
- **I want** GET `/health/deep` to show every dependency's status and latency
- **So that** I immediately see which dependency is the bottleneck
- **Given:** All four checks registered
- **When:** GET `/health/deep`
- **Then:**
  - Returns `HealthReport` with `checks` list containing all registered dependencies
  - Each `DependencyCheck` has non-zero `latency_ms` and a populated `details` dict
  - Verified by T-16

**US-09: Timeout prevents probe from hanging**
- **As a** platform engineer
- **I want** every check to have a hard wall-clock timeout
- **So that** a slow database query does not block the readiness probe for 30 seconds
- **Given:** `HealthRegistry(timeout_ms=5000)` (default)
- **When:** A check takes longer than 5 s
- **Then:**
  - `asyncio.wait_for` raises `TimeoutError`; check returns `DependencyCheck(status="unhealthy", details={"error": "timeout"})` (INV-HD-04)
  - Verified by T-18

**US-10: Circuit breaker prevents alert flapping**
- **As an** on-call engineer receiving alerts
- **I want** repeated failures to escalate from `unhealthy` to `degraded`
- **So that** I distinguish "just started failing" from "has been down for a while"
- **Given:** A check has failed 3+ times consecutively
- **When:** `_circuit_status` is called
- **Then:**
  - `_failure_counts[name] >= 3` → returns `HealthStatus.DEGRADED` (INV-HD-06)
  - Verified by T-23

### 9.3 Built-in checks (US-11 .. US-15)

**US-11: Database check reports pool stats**
- **As an** SRE investigating slow queries
- **I want** to see `pool_size`, `checked_out`, `overflow`, `checked_in` in the health response
- **So that** I can diagnose connection pool exhaustion without querying the DB directly
- **Given:** `database_check` registered in the registry
- **When:** GET `/health/deep`
- **Then:**
  - `DependencyCheck(name="database", details={"pool_size": ..., "checked_out": ..., ...})`
  - Verified by T-11

**US-12: Redis check reports memory and client stats**
- **As a** platform engineer monitoring Redis capacity
- **I want** `used_memory_human` and `connected_clients` in the health response
- **So that** I see memory pressure before it causes eviction
- **Given:** `redis_check` registered in the registry
- **When:** GET `/health/deep`
- **Then:**
  - `DependencyCheck(name="redis", details={"used_memory_human": ..., "connected_clients": ..., "redis_version": ...})`
  - Verified by T-12

**US-13: Disk check fires when filesystem is near capacity**
- **As a** platform engineer
- **I want** `/health/ready` to return 503 when disk usage exceeds the configured threshold
- **So that** I get an alert before log rotation fails and the service crashes
- **Given:** `disk_check` registered as `critical=True`; `HEALTH_DISK_THRESHOLD_PCT=90`; disk at 95% usage
- **When:** GET `/health/ready`
- **Then:**
  - `DependencyCheck(name="disk", status="unhealthy", details={"used_pct": 95, ...})`
  - Readiness probe returns 503
  - Verified by T-13

**US-14: Memory check fires when process RSS exceeds threshold**
- **As a** platform engineer fighting a memory leak
- **I want** the health endpoint to surface RSS before OOM kills the pod
- **So that** I can alert and restart gracefully
- **Given:** `memory_check` registered; `HEALTH_MEMORY_THRESHOLD_MB=512`; process RSS at 600 MB
- **When:** GET `/health/deep`
- **Then:**
  - `DependencyCheck(name="memory", status="unhealthy", details={"rss_mb": 600.0, ...})`
  - Verified by T-14

**US-15: Health models carry structured data for dashboards**
- **As a** dashboard developer
- **I want** `HealthReport` to be a typed Pydantic model
- **So that** my frontend can parse `checks[*].latency_ms` without fragile string parsing
- **Given:** `HealthReport` and `DependencyCheck` models generated
- **When:** Health endpoint returns JSON
- **Then:**
  - `HealthReport.status` is a string (`"healthy"` | `"degraded"` | `"unhealthy"`)
  - `DependencyCheck.latency_ms` is an `int`
  - Verified by T-15

---

## 10. Test Plan

All 24 tests live in `adapt/extend/infrastructure/test_add_health_deep.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `health_t01` | `add_health_deep(ToolInput(project_dir))` | `result.status == "success"` (INV-HD-01, CC-01) |
| T-02 | `test_idempotent_returns_no_op` | Fixture `health_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; both lists empty (INV-HD-01, CC-02) |
| T-03 | `test_dry_run_writes_nothing` | Fixture `health_t03`; snapshot all `.py` | `add_health_deep(ToolInput(dry_run=True))` | `status == "success"`; empty create/modify lists; byte-identical filesystem (INV-HD-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `health_t04` | Run tool | `len(files_created) >= 9`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `health_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-09)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `health_t06`; run tool | `ast.parse` every `.py` in project | No `SyntaxError` (INV-HD-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `health_t07`; run tool | AST walk over `app/health/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `health_t08`; run tool | Read `app/core/config.py` | Contains `HEALTH_CHECK_TIMEOUT_MS`, `HEALTH_DISK_THRESHOLD_PCT`, `HEALTH_MEMORY_THRESHOLD_MB` (INV-HD-07, CC-08) |
| T-09 | `test_requirements_patched` | Fixture `health_t09`; run tool | Read `requirements.txt` | Contains `"psutil"` (INV-HD-09, CC-09) |

### 10.3 Category C — Domain-specific modules (T-10 .. T-19)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-10 | `test_health_registry_created` | Fixture `health_t10`; run tool | Read `app/health/registry.py` | Contains `HealthRegistry`, `register_check`, `run_all`, `run_readiness`, `run_liveness` (CC-10) |
| T-11 | `test_db_check_created` | Fixture `health_t11`; run tool | Read `app/health/checks/database.py` | Contains `async def database_check`; `"SELECT 1"` or `"select"` present (CC-11) |
| T-12 | `test_redis_check_created` | Fixture `health_t12`; run tool | Read `app/health/checks/redis.py` | Contains `async def redis_check`; `"ping"` and `"memory"` present (CC-12) |
| T-13 | `test_disk_check_created` | Fixture `health_t13`; run tool | Read `app/health/checks/disk.py` | Contains `async def disk_check`; `"psutil"` and `"HEALTH_DISK_THRESHOLD_PCT"` present (CC-13) |
| T-14 | `test_memory_check_created` | Fixture `health_t14`; run tool | Read `app/health/checks/memory.py` | Contains `async def memory_check`; `"psutil"` and `"rss"` present (CC-14) |
| T-15 | `test_health_models_created` | Fixture `health_t15`; run tool | Read `app/health/models.py` | Contains `HealthStatus`, `DependencyCheck`, `HealthReport`, `latency_ms` (CC-15) |
| T-16 | `test_deep_route_created` | Fixture `health_t16`; run tool | Read `app/api/routes/health_deep.py` | Contains `"/live"`, `"/ready"`, `"/deep"` (CC-16) |
| T-17 | `test_ready_route_runs_critical_only` | Fixture `health_t17`; run tool | AST parse `readiness` function body | `"run_readiness" in content`; `"run_all"` absent from `readiness` function source (QS-7, CC-17) |
| T-18 | `test_timeout_in_checks` | Fixture `health_t18`; run tool | Read `app/health/registry.py` | Contains `"asyncio.wait_for"` and `"timeout"` (INV-HD-04, CC-18) |
| T-19 | `test_routes_registered_in_main` | Fixture `health_t19`; run tool | Read `app/main.py` if exists | Contains `"health_deep"` (CC-19) |

### 10.4 Category D — Meta (T-20 .. T-24)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-20 | `test_execution_time_recorded` | Fixture `health_t20`; run tool | Read `result.execution_time_ms` | `> 0` (INV-HD-11, CC-20) |
| T-21 | `test_next_steps_present` | Fixture `health_t21`; run tool | Inspect `result.next_steps` | `len >= 3`; `"psutil"` and `"env"` present (CC-21) |
| T-22 | `test_idempotent_project_still_parses` | Fixture `health_t22`; run tool twice | `ast.parse` every `.py` | No `SyntaxError` (INV-HD-01, INV-HD-03, CC-22) |
| T-23 | `test_circuit_breaker_in_registry` | Fixture `health_t23`; run tool | Read `app/health/registry.py` | `"degraded"` and `"_failure_counts"` or `"failure"` present (INV-HD-06, CC-23) |
| T-24 | `test_health_init_re_exports` | Fixture `health_t24`; run tool | Read `app/health/__init__.py` | Contains `HealthRegistry`, `DependencyCheck`, `HealthReport` (INV-HD-10, CC-24) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_health_deep.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_health_deep.py
```

Target: 24/24 passed, 0 failed. The standalone runner prints `TOOL-061 add_health_deep: 24 passed, 0 failed`.

---

## 11. Interaction Matrix

How `add_health_deep` composes with other SKILL-001 tools. Tool IDs match `specs/` directory entries.

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | Yes | ✅ Compatible — health runs AFTER | `database_check` and `redis_check` benefit from the arq Redis pool already being configured; `add_arq_worker` establishes `REDIS_URL` in `config.py` which `redis_check` reads via `os.getenv` |
| `add_cache_layer` (TOOL-021) | No | ✅ Compatible | Both use `REDIS_URL`; `redis_check` pings the same Redis instance used for caching; separate logical DBs recommended for cache vs ephemeral health state |
| `add_rate_limiting` (TOOL-057) | No | ✅ Compatible | Health endpoints (`/health/live`, `/health/ready`, `/health/deep`) MUST be excluded from rate limiting — they are invoked by Kubernetes infrastructure, not end users |
| `add_circuit_breaker` (TOOL-022) | No | ✅ Compatible | The `HealthRegistry` circuit-breaker (failure count → degraded) is complementary to TOOL-022's circuit-breaker for outgoing HTTP calls; they operate at different layers |
| `add_multi_tenancy` (TOOL-008) | No | ✅ Compatible | Health checks are process-level, not tenant-scoped; the `/health/*` routes require no tenant context and carry no tenant data |
| `add_rbac` (TOOL-012) | No | ⚠️ Caveat | `/health/live` and `/health/ready` MUST remain unauthenticated for Kubernetes probes. `/health/deep` MAY be protected with RBAC for security; add `current_user: CurrentUser` only to `/health/deep` |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | Same caveat as RBAC — API key auth must not gate liveness/readiness probes |
| `add_oauth2_provider` (TOOL-011) | No | ✅ Compatible | OAuth2 auth must not gate liveness/readiness probes |
| `add_audit_log` (TOOL-005) | No | ⚠️ Caveat | Do NOT audit-log health check calls — the volume (every 10 s per Kubernetes probe) would flood the audit table |
| `add_scheduled_tasks` (TOOL-058) | No | ✅ Compatible | Scheduled tasks can call `registry.run_all()` on a 1-minute cron to write health snapshots to a time-series table for SLA reporting |
| `add_sse` (TOOL-014) | No | ✅ Compatible | SSE endpoint can push `health.changed` events to admin dashboards when overall status transitions between `healthy` / `degraded` / `unhealthy` |
| `add_webhook_sender` (TOOL-015) | No | ✅ Compatible | A `health.status_changed` webhook can fire when circuit-breaker state transitions; wire in `HealthRegistry.run_all()` on a cron |
| `add_long_running_task` (TOOL-020) | No | ✅ Compatible | Long-running task endpoints can be monitored via a custom `HealthRegistry` check that reads task-queue depth |
| `fastapi_doctor` (TOOL-051) | Yes | ✅ Compatible — doctor runs AFTER | `fastapi_doctor` validates route correctness; it should report `/health/live`, `/health/ready`, `/health/deep` as properly registered |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | Admin panel can render health history if `HealthReport` snapshots are persisted to a table by a cron job |
| `add_load_profile` (TOOL-027) | No | ✅ Compatible | Load profiling should EXCLUDE `/health/*` routes — they have flat response profiles and skew percentile reports |
| `detect_n_plus_one` (TOOL-028) | No | ✅ Compatible | `database_check` executes a single `SELECT 1` — no N+1 risk; include_router injection does not affect N+1 detection logic |

**Conflicts:** None identified. The `add_health_deep` tool does not interfere with existing authentication, routing, or database layer tooling so long as `/health/live` and `/health/ready` remain unauthenticated for infrastructure probes.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/main.py \
  requirements.txt

rm -rf \
  app/health/ \
  app/api/routes/health_deep.py
```

### 12.2 No database rollback required

`add_health_deep` does not write any Alembic migration. No `alembic downgrade` step is needed.

### 12.3 Partial-write recovery

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name 'health_deep.py' -path '*/routes/*' -delete
rm -rf app/health/
```

Because `_assert_parses` runs at the end of the success path, a mid-execution failure leaves partially-written files. Modified files are recoverable from git; newly-created files must be removed manually.

### 12.4 Configuration rollback

Remove the injected block from `app/core/config.py`:

```bash
# Remove the three HEALTH_* lines injected after the Settings block
# or restore from git:
git checkout HEAD -- app/core/config.py
```

### 12.5 Router unregistration

Remove the `health_deep_router` from `app/main.py`:

```python
# Remove these two lines added by the tool:
# from app.api.routes.health_deep import router as health_deep_router  # noqa: E402
# app.include_router(health_deep_router)
```

### 12.6 Uninstall validator

```bash
test ! -d app/health || (echo "app/health still present" && exit 1)
test ! -f app/api/routes/health_deep.py || (echo "health_deep.py still present" && exit 1)
grep -q "HEALTH_CHECK_TIMEOUT_MS" app/core/config.py && echo "config still patched" && exit 1
grep -q "health_deep" app/main.py && echo "main.py still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing `CONFIG_SETTINGS` prerequisite | `ensure_prerequisites` returns errors → tool returns `status="error"` with list of missing prereqs and hint to run `fastapi_generate_project` first |
| EC-03 | Tool runs on a project with `app/health/registry.py` already containing `HealthRegistry` | Early return `status="no_op"` with single note — zero file writes |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-HD-02) |
| EC-05 | `app/api/routes/` directory does not exist | `_write_health_deep_route` step is skipped (condition `if routes_dir.exists():`); health package files still written; operator must register router manually — noted in `next_steps` |
| EC-06 | `app/core/config.py` already contains `HEALTH_CHECK_TIMEOUT_MS` | `_patch_config` early-returns (`"HEALTH_CHECK_TIMEOUT_MS" in src` check); no duplicate block appended |
| EC-07 | `app/core/config.py` lacks `settings = Settings()` sentinel | `_patch_config` falls back to appending at EOF; fields may land at module scope with a warning comment |
| EC-08 | `app/main.py` already contains `health_deep` | `_patch_main` early-returns (`"health_deep" in src` check); `files_modified` does NOT include `main.py`; idempotency preserved |
| EC-09 | `app/main.py` missing `from fastapi import FastAPI` import line | `_patch_main` prepends the import at the top of the file instead; router include appended at EOF |
| EC-10 | `requirements.txt` already contains `psutil` | `_patch_requirements` skips the append; trailing newline preserved |
| EC-11 | `app/health/checks/` directory creation fails due to permissions | `mkdir(parents=True, exist_ok=True)` raises `PermissionError`; propagates as uncaught exception; tool should be re-run with correct permissions |
| EC-12 | Generated `registry.py` fails `ast.parse` | `ast.parse` loop raises `SyntaxError`; tool returns `ToolResult(status="error", error=f"Generated file has syntax error: {p}: {exc}")` |
| EC-13 | Project has no `requirements.txt` | `_patch_requirements` step conditional on `req_file.exists()`; skipped silently; `psutil` must be installed manually |
| EC-14 | `psutil` import inside `disk_check` or `memory_check` raises `ImportError` (not installed yet) | Both checks use `try/except Exception` wrapping; `ImportError` returns `DependencyCheck(status="unhealthy", details={"error": "No module named 'psutil'"})` at runtime |
| EC-15 | `app/core/db.py` (engine) does not exist in target project | `database_check` deferred import `from app.core.db import engine` raises `ImportError` at check runtime; caught by `except Exception`; returns `DependencyCheck(status="unhealthy", details={"error": "..."})` — tool itself succeeds regardless |
| EC-16 | Redis is unavailable at the time of `redis_check` execution | `client.ping()` raises `ConnectionError`; caught by `except Exception`; returns `DependencyCheck(status="unhealthy", details={"error": str(exc)})` |
| EC-17 | `HEALTH_DISK_THRESHOLD_PCT` env var set to `0` | All disks with any usage (> 0%) report `unhealthy`; valid operational misconfiguration; no special handling by the tool |
| EC-18 | `HEALTH_MEMORY_THRESHOLD_MB` env var set to a value below current RSS | `memory_check` immediately returns `unhealthy`; forces operator attention to an undersized threshold |
| EC-19 | Tool runs on a project that already has an `app/health/` directory but without `registry.py` | Idempotency guard only checks `registry_file.exists() and "HealthRegistry" in registry_file.read_text()`; tool proceeds and writes all files |
| EC-20 | Second run when `app/health/registry.py` exists but does not contain `HealthRegistry` | Tool is NOT idempotent in this case (fingerprint missing); tool proceeds to rewrite the file |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 24 Completeness Criteria verified via `test_add_health_deep.py` passing
2. ✅ `test_add_health_deep.py` reports `24 passed, 0 failed` via both pytest and standalone runner
3. ✅ Tool execution time < 5 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-HD-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-HD-02)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-HD-03)
7. ✅ No generated function in `app/health/` exceeds 50 LOC (QS-4)
8. ✅ Every registered check runs inside `asyncio.wait_for(timeout=timeout_ms/1000)` (INV-HD-04)
9. ✅ `/health/ready` calls `run_readiness()` exclusively — never `run_all()` (INV-HD-05)
10. ✅ Circuit-breaker `_failure_counts` increments on failure, resets on success, escalates to `degraded` at threshold 3 (INV-HD-06)
11. ✅ `HEALTH_*` settings appear inside `class Settings` body with correct indentation (INV-HD-07)
12. ✅ `/health/ready` and `/health/deep` return HTTP 503 when report status is not `healthy` (QS-8)
13. ✅ `app/health/__init__.py` re-exports `HealthRegistry`, `get_registry`, `DependencyCheck`, `HealthReport`, `HealthStatus` (INV-HD-10)
14. ✅ `psutil>=6.0.0` added to `requirements.txt` (INV-HD-09)
15. ✅ `next_steps` includes `pip install psutil` and env var guidance (INV-HD-12)
16. ✅ Developer successfully hits `GET /health/deep`, sees all four checks with `latency_ms` and `details`, and configures Kubernetes probes to use `/health/live` and `/health/ready`

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` passes
- [ ] `app/health/registry.py` does NOT contain `"HealthRegistry"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Health package

- [ ] `mkdir -p app/health/checks`
- [ ] Write `app/health/__init__.py` via `_write_health_init` (exports `HealthRegistry`, `get_registry`, models)
- [ ] Write `app/health/registry.py` via `_write_health_registry` (`HealthRegistry`, `_aggregate_status`, `get_registry`)
- [ ] Write `app/health/models.py` via `_write_health_models` (`HealthStatus`, `DependencyCheck`, `HealthReport`)
- [ ] Write `app/health/checks/__init__.py` via `_write_checks_init` (exports all four check functions)
- [ ] Write `app/health/checks/database.py` via `_write_check_database` (`async def database_check`)
- [ ] Write `app/health/checks/redis.py` via `_write_check_redis` (`async def redis_check`)
- [ ] Write `app/health/checks/disk.py` via `_write_check_disk` (`async def disk_check`)
- [ ] Write `app/health/checks/memory.py` via `_write_check_memory` (`async def memory_check`)

### 15.3 Registry implementation

- [ ] `HealthRegistry.__init__` initialises `_checks`, `_failure_counts`, `timeout_ms`
- [ ] `register_check(name, check_fn, *, critical=False)` stores entry and initialises failure count
- [ ] `_run_one(name)` wraps call in `asyncio.wait_for(timeout=self.timeout_ms / 1000)`
- [ ] `_run_one` increments `_failure_counts[name]` on `TimeoutError`
- [ ] `_run_one` increments `_failure_counts[name]` on generic `Exception`
- [ ] `_run_one` resets `_failure_counts[name] = 0` on success
- [ ] `_circuit_status(name)` returns `DEGRADED` when count >= `_CIRCUIT_BREAKER_THRESHOLD` (3)
- [ ] `_circuit_status(name)` returns `UNHEALTHY` when count < threshold
- [ ] `run_all()` gathers all checks via `asyncio.gather`
- [ ] `run_readiness()` filters to `critical=True` checks only
- [ ] `run_liveness()` returns `HealthReport(status=HEALTHY, checks=[])` immediately
- [ ] `_aggregate_status(checks)` returns `UNHEALTHY` if any; `DEGRADED` if any; `HEALTHY` otherwise
- [ ] `get_registry()` returns global `_registry` singleton (lazy init)

### 15.4 Built-in checks

- [ ] `database_check` defers `from app.core.db import engine` inside `try`
- [ ] `database_check` executes `SELECT 1`; reads `pool.size()`, `checkedout()`, `overflow()`, `checkedin()`
- [ ] `redis_check` defers `from redis.asyncio import Redis` inside `try`
- [ ] `redis_check` reads `REDIS_URL` from `os.getenv`
- [ ] `redis_check` calls `ping()`, `info("server")`, `info("memory")`, `info("clients")`
- [ ] `redis_check` calls `aclose()` in `finally` block
- [ ] `disk_check` reads `HEALTH_DISK_THRESHOLD_PCT` from `os.getenv("HEALTH_DISK_THRESHOLD_PCT", "90")`
- [ ] `disk_check` marks `UNHEALTHY` when `usage.percent >= threshold`
- [ ] `memory_check` reads `HEALTH_MEMORY_THRESHOLD_MB` from `os.getenv("HEALTH_MEMORY_THRESHOLD_MB", "512")`
- [ ] `memory_check` marks `UNHEALTHY` when `rss_mb >= threshold_mb`
- [ ] All four checks return `DependencyCheck` on both success and failure paths
- [ ] All four checks record `latency_ms = int((time.monotonic() - t0) * 1000)` before returning

### 15.5 HTTP routes

- [ ] Write `app/api/routes/health_deep.py` via `_write_health_deep_route` when `routes_dir.exists()`
- [ ] `router = APIRouter(prefix="/health", tags=["health"])`
- [ ] `GET /live` calls `registry.run_liveness()`; always 200
- [ ] `GET /ready` calls `registry.run_readiness()`; sets 503 when `report.status != HEALTHY`
- [ ] `GET /deep` calls `registry.run_all()`; sets 503 when `report.status == UNHEALTHY`
- [ ] All three handlers import `get_registry` from `app.health.registry`

### 15.6 Config patch

- [ ] Early-return if `"HEALTH_CHECK_TIMEOUT_MS" in src`
- [ ] Block emits `HEALTH_CHECK_TIMEOUT_MS`, `HEALTH_DISK_THRESHOLD_PCT`, `HEALTH_MEMORY_THRESHOLD_MB`
- [ ] Anchor on `settings = Settings()` sentinel; insert block before that line
- [ ] Last-resort fallback: append at EOF

### 15.7 Main patch (router injection)

- [ ] Early-return if `"health_deep" in src`
- [ ] Insert `from app.api.routes.health_deep import router as health_deep_router` import after `from fastapi import FastAPI`
- [ ] Append `app.include_router(health_deep_router)` at end of file
- [ ] Preserve trailing newline

### 15.8 Requirements patch

- [ ] Add `psutil>=6.0.0` if `"psutil"` absent
- [ ] Preserve trailing newline

### 15.9 Validation

- [ ] Loop over `files_created`; for every `.py` call `ast.parse(p.read_text())`
- [ ] Return `ToolResult(status="error", error=...)` on `SyntaxError`

### 15.10 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain three endpoints, four checks, circuit-breaker, timeout
- [ ] `next_steps` contains psutil install, env var guidance, check registration snippet, Kubernetes probe config

### 15.11 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring describes all 9 created files and replaces basic `/healthz` rationale
- [ ] `add_health_deep` docstring documents `inp` parameter and return value

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/health/__init__.py",
    "/tmp/fixture/app/health/registry.py",
    "/tmp/fixture/app/health/models.py",
    "/tmp/fixture/app/health/checks/__init__.py",
    "/tmp/fixture/app/health/checks/database.py",
    "/tmp/fixture/app/health/checks/redis.py",
    "/tmp/fixture/app/health/checks/disk.py",
    "/tmp/fixture/app/health/checks/memory.py",
    "/tmp/fixture/app/api/routes/health_deep.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/main.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "Deep health checks enabled: HealthRegistry with per-dependency latency tracking.",
    "Three endpoints: /health/live (liveness), /health/ready (critical deps), /health/deep (full dependency matrix).",
    "Checks: PostgreSQL pool stats, Redis ping+memory, disk space, process RSS.",
    "Circuit-breaker: checks failing N times are marked 'degraded' to avoid flapping.",
    "All checks run with asyncio.wait_for(timeout) — never hang the readiness probe."
  ],
  "next_steps": [
    "pip install 'psutil>=6.0.0'",
    "Set HEALTH_CHECK_TIMEOUT_MS in .env (default: 5000).",
    "Set HEALTH_DISK_THRESHOLD_PCT in .env (default: 90).",
    "Set HEALTH_MEMORY_THRESHOLD_MB in .env (default: 512).",
    "Register your checks in app startup: registry.register_check('db', db_check, critical=True)",
    "Point your k8s liveness probe at /health/live and readiness probe at /health/ready."
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
    "HealthRegistry already present — deep health checks already enabled, skipped."
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
    "[dry_run] Would create app/health/ package with registry, checks, and models.",
    "[dry_run] Would create app/api/routes/health_deep.py with /health/live+ready+deep.",
    "[dry_run] Would patch app/core/config.py and app/main.py."
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
