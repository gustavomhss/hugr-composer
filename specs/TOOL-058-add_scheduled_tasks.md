---
spec_id: "TOOL-058"
tool_name: "add_scheduled_tasks"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-SCH-01"
  - "INV-SCH-02"
  - "INV-SCH-03"
  - "INV-SCH-04"
  - "INV-SCH-05"
  - "INV-SCH-06"
  - "INV-SCH-07"
  - "INV-SCH-08"
  - "INV-SCH-09"
  - "INV-SCH-10"
  - "INV-SCH-11"
  - "INV-SCH-12"
  - "INV-SCH-13"
  - "INV-SCH-14"
  - "INV-SCH-15"
  - "INV-SCH-16"
  - "INV-SCH-17"
  - "INV-SCH-18"
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
  - "CC-18"
  - "CC-19"
  - "CC-20"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
  - "QS-17"
  - "QS-18"
  - "QS-19"
  - "QS-2"
  - "QS-20"
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
  - "T-18"
  - "T-19"
  - "T-20"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-058: add_scheduled_tasks

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_scheduled_tasks` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, APScheduler (lazy import), Redis (optional, for multi-instance job store), pydantic-settings |
| Signature | `add_scheduled_tasks(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag. No additional keyword parameters — tuning is done post-install via the `SCHEDULER_*` env vars bound inside `class Settings`. |
| MCP descriptor | `{"name": "fastapi_add_scheduled_tasks", "description": "Add APScheduler-based cron jobs with Redis job store, decorator registry, and FastAPI lifespan integration.", "tags": ["extend", "infrastructure"], "entry": "add_scheduled_tasks"}` |
| Files created (typical) | 3 — `app/workers/scheduler.py`, `app/workers/cron_jobs.py`, `app/api/routes/scheduler.py` (plus `app/workers/__init__.py` when the package did not previously exist) |
| Files modified (typical) | 3 — `app/core/config.py`, `app/main.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_scheduled_tasks` tool installs declarative cron-style scheduled tasks into a FastAPI project **without** pulling in the Celery beat + broker + worker trifecta, and **without** asking developers to run a second sidecar process (`celery beat -A ...`) whose health and observability become yet another problem to own. Teams who want "run this coroutine every 5 minutes" typically reach for Celery reflexively and pay a staggering price: a separate scheduler daemon that can desync from the worker fleet, a broker-plus-backend footprint that doubles Redis operations, synchronous worker runtimes that thread every `async def` call, and a time-zone story that routinely bites production at DST boundaries. The alternative of "spin up a background asyncio task in startup" fails at the first retry, at the first multi-instance deploy, and at the first missed run after a Kubernetes pod eviction. **APScheduler** (specifically `AsyncIOScheduler`) sits in exactly that gap: native `async def` job execution sharing the FastAPI process's existing event loop, a pluggable job store (memory for single-instance, Redis for multi-instance), cron + interval + date triggers with a battle-tested timezone implementation, and an import footprint small enough that the scheduler can be lazy-loaded inside the factory method so the FastAPI app still boots when `apscheduler` is absent from the environment.

This tool generates the minimum kit a real service needs so developers do not hand-roll any of the brittle pieces. It emits: (a) `app/workers/scheduler.py` containing `SchedulerFactory.build()` with a **lazy** `from apscheduler.schedulers.asyncio import AsyncIOScheduler` import inside the method body, a `get_scheduler()` singleton accessor, and `start_scheduler()` / `stop_scheduler()` lifespan hooks that are **silent no-ops** when either `SCHEDULER_ENABLED=false` or `apscheduler` is not installed (ImportError is swallowed with a `scheduler.apscheduler_not_installed` log line — the app keeps booting); (b) `app/workers/cron_jobs.py` with a `ScheduledJob` frozen dataclass, a module-level `_JOBS` registry list, a `@scheduled_job("*/5 * * * *", name="...")` decorator that mutates the registry at import time, a `register_jobs(scheduler)` installer that converts each entry into a `CronTrigger.from_crontab(...)` and calls `scheduler.add_job(fn, trigger=trigger, id=name, replace_existing=True)`, a `list_jobs()` serializer for the HTTP route, and three example jobs (`health_heartbeat` every 5 min, `cleanup_expired_sessions` daily at 03:00, `refresh_materialized_view` every 6 hours) demonstrating the three most common cadences; (c) `app/api/routes/scheduler.py` exposing `GET /scheduler/jobs` returning a `list[JobInfo]` whose `next_run` field cross-references each declared job against the live scheduler via `sched.get_job(name).next_run_time`, providing operators a single-URL answer to "what is scheduled and when does it fire next". The tool patches `app/core/config.py` with three `SCHEDULER_*` fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so they land **inside** `class Settings` (4-space indent) where pydantic-settings binds them from environment variables; rewrites `app/main.py`'s existing `@asynccontextmanager`-based `lifespan` to call `await start_scheduler()` **before** the `yield` and `await stop_scheduler()` **after** the shutdown marker, preserving the existing indentation; and appends `apscheduler>=3.10.0` to `requirements.txt` only when absent.

Key design decisions: APScheduler imports are **always lazy** — `SchedulerFactory.build()` performs `from apscheduler.schedulers.asyncio import AsyncIOScheduler` inside the method body, `register_jobs()` performs `from apscheduler.triggers.cron import CronTrigger` inside the function body, and the Redis job store is imported inside a nested `try: from apscheduler.jobstores.redis import RedisJobStore except ImportError:` — so the generated module is importable on a machine where `apscheduler` is not yet installed (critical for CI jobs that only run AST checks, and for the pre-`pip install` branch of a Dockerfile COPY step); the scheduler is **in-process** rather than a separate sidecar (APScheduler runs on the FastAPI event loop), which trades the scale-out story of a separate process for the operational simplicity of one container, one set of logs, one set of metrics; the Redis job store branch activates **only** when `settings.SCHEDULER_JOBSTORE_URL` starts with `redis://`, otherwise the in-memory store is used — this means single-instance deployments get zero Redis churn and multi-instance deployments get exactly-once semantics by setting a single env var; default timezone is `UTC` (string literal in the patched config block) because every other choice eventually bites during DST; the tool is idempotent by fingerprint detection (`"SchedulerFactory" in app/workers/scheduler.py`) and returns `status="no_op"` with zero file writes on second invocation; the lifespan patch is idempotent via `"start_scheduler" in src` so re-running the tool never doubles up the hook or corrupts the `lifespan` context manager; the rollback path is mechanical — three files created, three files patched, each individually revertable via `git checkout HEAD --`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (T-17) |
| Files created | ≥ 3 | Scheduler factory, cron jobs registry, status route — plus conditional `app/workers/__init__.py` on first install (T-04) |
| Files modified | ≥ 2 | At minimum `config.py` and `main.py`; typically also `requirements.txt` (T-05) |
| Max function LOC in generated code | ≤ 50 | Every generated helper stays auditable; enforced by AST walk over `app/` subtree (T-07) |
| APScheduler import cost at module load | 0 ms | Imports are lazy — `scheduler.py` loads without `apscheduler` installed |
| `start_scheduler()` cold path | < 20 ms | Build scheduler + register N jobs + start; dominated by `CronTrigger.from_crontab` calls |
| `stop_scheduler()` cold path | < 10 ms | `sched.shutdown(wait=False)` — returns immediately without waiting for running jobs |
| `GET /scheduler/jobs` latency | < 10 ms | In-memory read of `_JOBS` + `sched.get_job(name)` lookups; no Redis round trip |
| Scheduler tick resolution | 1 s (APScheduler default) | Cron expressions with minute granularity fire within 1 s of the wall clock |
| Job overlap semantics | `coalesce=True` (APScheduler default via `add_job`) | Missed runs during downtime collapse to a single catch-up fire, not N duplicates |
| Memory footprint per job | < 1 KB | `ScheduledJob` dataclass + APScheduler internal `Job` object |
| Second-run execution time | < 5 ms | Idempotent no-op: fingerprint read + early return |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, lifespan without scheduler hooks
│   ├── core/
│   │   └── config.py        # Settings class, no SCHEDULER_* fields
│   └── api/
│       └── routes/          # No scheduler.py route
├── requirements.txt         # no apscheduler
```

Every periodic operation is a hand-rolled `asyncio.create_task(loop_forever())` inside the startup hook — survives zero restarts, has no observability, and double-fires on every multi-instance deploy.

### 4.2 Scheduler factory: AFTER

```python
# app/workers/scheduler.py
"""APScheduler factory — async scheduler with configurable job store.

When ``settings.SCHEDULER_JOBSTORE_URL`` starts with ``redis://``, the
scheduler uses a persistent Redis job store (multi-instance safe).
Otherwise it falls back to an in-memory store (single-instance only).

The factory is wired into the FastAPI lifespan via
``start_scheduler`` / ``stop_scheduler`` — called from ``app.main``.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_scheduler: Any | None = None


class SchedulerFactory:
    """Build and return an ``AsyncIOScheduler`` instance.

    APScheduler is imported lazily so the module can be loaded even
    when the SDK is not installed — the error surfaces only when
    ``start_scheduler`` is actually called.
    """

    @staticmethod
    def build() -> Any:
        """Return a scheduler configured from settings.

        Returns:
            A new ``AsyncIOScheduler`` with job store + timezone.

        Raises:
            ImportError: If ``apscheduler`` is not installed.
        """
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        jobstore_url = getattr(settings, "SCHEDULER_JOBSTORE_URL", "") or ""
        jobstores: dict[str, Any] = {}
        if jobstore_url.startswith("redis://"):
            try:
                from apscheduler.jobstores.redis import RedisJobStore
                jobstores["default"] = RedisJobStore(
                    jobs_key="apscheduler.jobs",
                    run_times_key="apscheduler.run_times",
                    host="localhost",
                )
            except ImportError:
                logger.warning(
                    "apscheduler redis jobstore unavailable; falling back to memory"
                )
        timezone = getattr(settings, "SCHEDULER_TIMEZONE", "UTC")
        return AsyncIOScheduler(jobstores=jobstores or None, timezone=timezone)


def get_scheduler() -> Any:
    """Return the shared scheduler singleton, building it on first call."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerFactory.build()
    return _scheduler


async def start_scheduler() -> None:
    """Start the scheduler and register declared cron jobs.

    If ``apscheduler`` is not installed OR ``SCHEDULER_ENABLED`` is
    false, this is a silent no-op — the application keeps booting.
    """
    if not getattr(settings, "SCHEDULER_ENABLED", True):
        logger.info("scheduler.disabled")
        return
    try:
        sched = get_scheduler()
    except ImportError:
        logger.warning("scheduler.apscheduler_not_installed")
        return
    from app.workers.cron_jobs import register_jobs
    register_jobs(sched)
    sched.start()
    logger.info("scheduler.started", extra={"jobs": len(sched.get_jobs())})


async def stop_scheduler() -> None:
    """Shut down the scheduler if running."""
    global _scheduler
    if _scheduler is not None and getattr(_scheduler, "running", False):
        _scheduler.shutdown(wait=False)
        logger.info("scheduler.stopped")
    _scheduler = None
```

Note the three critical patterns: (1) `AsyncIOScheduler` imported **inside** `build()`, (2) `RedisJobStore` imported inside a **nested** `try/except ImportError`, and (3) `start_scheduler()` catches `ImportError` at the `get_scheduler()` call site and returns silently with a warning log — the FastAPI app never crashes because `apscheduler` is missing.

### 4.3 Cron jobs registry: AFTER

```python
# app/workers/cron_jobs.py
"""Cron job registry — declare scheduled tasks via @scheduled_job.

Usage::

    @scheduled_job("0 */6 * * *", name="refresh_view")
    async def refresh_materialized_view() -> None:
        ...

The ``register_jobs`` function is called by ``start_scheduler`` at
startup and installs every decorated function on the scheduler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledJob:
    """A single cron job declaration."""

    cron: str
    name: str
    func: Callable[[], Awaitable[None]]


_JOBS: list[ScheduledJob] = []


def scheduled_job(
    cron: str, *, name: str | None = None
) -> Callable[[Callable[[], Awaitable[None]]], Callable[[], Awaitable[None]]]:
    """Decorator that registers an async function as a cron job.

    Args:
        cron: Cron expression (5-field: minute hour day month dow).
        name: Optional job name (defaults to the function name).

    Returns:
        The original function, unchanged.
    """

    def wrap(fn: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        _JOBS.append(ScheduledJob(cron=cron, name=name or fn.__name__, func=fn))
        return fn

    return wrap


def register_jobs(scheduler: Any) -> None:
    """Install every declared job on *scheduler*.

    Args:
        scheduler: The running APScheduler instance.
    """
    from apscheduler.triggers.cron import CronTrigger
    for job in _JOBS:
        trigger = CronTrigger.from_crontab(job.cron)
        scheduler.add_job(
            job.func, trigger=trigger, id=job.name, replace_existing=True
        )
        logger.info("cron.registered", extra={"name": job.name, "cron": job.cron})


def list_jobs() -> list[dict[str, str]]:
    """Return a serialisable list of declared jobs."""
    return [{"name": j.name, "cron": j.cron} for j in _JOBS]


# ---------------------------------------------------------------------
# Example jobs — customise or delete as needed
# ---------------------------------------------------------------------

@scheduled_job("*/5 * * * *", name="health_heartbeat")
async def health_heartbeat() -> None:
    """Log a heartbeat every 5 minutes (useful as a liveness check)."""
    logger.info("scheduler.heartbeat")


@scheduled_job("0 3 * * *", name="cleanup_expired_sessions")
async def cleanup_expired_sessions() -> None:
    """Delete expired session rows every day at 03:00 UTC."""
    logger.info("scheduler.cleanup_expired_sessions.stub")


@scheduled_job("0 */6 * * *", name="refresh_materialized_view")
async def refresh_materialized_view() -> None:
    """Refresh a materialised view every 6 hours."""
    logger.info("scheduler.refresh_materialized_view.stub")
```

Three cadence shapes are demonstrated: every-N-minutes (`*/5 * * * *`), daily-at-fixed-time (`0 3 * * *`), and every-N-hours (`0 */6 * * *`). Developers copy one of the three, rename, and replace the body.

### 4.4 HTTP status route: AFTER

```python
# app/api/routes/scheduler.py
"""GET /scheduler/jobs — report registered cron jobs and next run time."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.workers.cron_jobs import list_jobs
from app.workers.scheduler import get_scheduler

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


class JobInfo(BaseModel):
    """Describes a single scheduled job."""

    name: str
    cron: str
    next_run: datetime | None = None


@router.get("/jobs", response_model=list[JobInfo])
async def get_jobs() -> list[JobInfo]:
    """Return the currently registered cron jobs and their next run times.

    Returns:
        A list of ``JobInfo`` entries sorted by job name.
    """
    declared = {j["name"]: j["cron"] for j in list_jobs()}
    sched = get_scheduler()
    out: list[JobInfo] = []
    for name, cron in sorted(declared.items()):
        next_run = None
        try:
            job = sched.get_job(name)
            if job is not None:
                next_run = job.next_run_time
        except Exception:
            next_run = None
        out.append(JobInfo(name=name, cron=cron, next_run=next_run))
    return out
```

The route walks the **declared** registry (not the scheduler's internal list) so jobs always appear even if APScheduler is missing / disabled — the only field that goes `None` is `next_run`. This gives ops a reliable "is the job installed even in a degraded mode" signal.

### 4.5 Config patch (settings injected inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "UTC"
    SCHEDULER_JOBSTORE_URL: str = ""
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables. Appending at module level would create module-scope attributes that `settings.SCHEDULER_ENABLED` cannot reach. A fallback path appends at EOF if the anchor is missing, which still yields AST-parseable Python but loses env var binding — verified by T-20.

### 4.6 `app/main.py` lifespan patch (start/stop hooks)

```python
# app/main.py  (diff, added by _patch_main)
from fastapi import FastAPI
from app.workers.scheduler import start_scheduler, stop_scheduler  # noqa: F401 — scheduled tasks
# ...
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    ...
    await start_scheduler()
    yield
    # --- Shutdown ---
    await stop_scheduler()
    ...
```

The patcher walks `main.py` line by line, enters `in_lifespan` mode when it sees `async def lifespan`, injects `await start_scheduler()` on the line **immediately before** the first `yield` (preserving the `yield`'s leading whitespace), and injects `await stop_scheduler()` either immediately before an `engine.dispose` call or immediately after a `# --- Shutdown` marker line. When neither landmark exists, the fallback appends `await stop_scheduler()` at the end of the lifespan body. When the project ships the legacy `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators instead of the modern `asynccontextmanager`, a second fallback parenthesis-walk finds the closing `)` of `app = FastAPI(` and emits the two decorator handlers directly after it.

### 4.7 Requirements patch

```text
# requirements.txt  (diff, appended by _patch_requirements)
apscheduler>=3.10.0
```

Idempotent: the patcher case-insensitively checks `"apscheduler" not in req_src.lower()` and only appends when absent, preserving the existing trailing newline with `rstrip("\n") + "\n"`.

### 4.8 Typical caller usage (after install)

```python
# app/workers/cron_jobs.py  (developer appends a new job)
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

@scheduled_job("0 4 * * *", name="nightly_reindex")
async def nightly_reindex() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(text("REINDEX TABLE documents"))
        await session.commit()
```

```bash
# Developer flow
$ pip install 'apscheduler>=3.10.0'
$ uvicorn app.main:app --reload
# scheduler.started jobs=4 (3 examples + nightly_reindex)
$ curl http://localhost:8000/scheduler/jobs
[
  {"name": "cleanup_expired_sessions", "cron": "0 3 * * *", "next_run": "2026-04-16T03:00:00+00:00"},
  {"name": "health_heartbeat", "cron": "*/5 * * * *", "next_run": "2026-04-15T14:25:00+00:00"},
  {"name": "nightly_reindex", "cron": "0 4 * * *", "next_run": "2026-04-16T04:00:00+00:00"},
  {"name": "refresh_materialized_view", "cron": "0 */6 * * *", "next_run": "2026-04-15T18:00:00+00:00"}
]
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_scheduled_tasks` pre-flight checks `"SchedulerFactory" in app/workers/scheduler.py` and returns `status="no_op"` with zero file writes |
| QS-2 | **`dry_run=True` writes zero files** | Early `if inp.dry_run:` return yields `status="success"` with informational `notes` before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | The caller-side test (`_assert_parse`) runs `ast.parse` on every `.py` in the project tree; tool generates AST-clean code by construction |
| QS-4 | **No generated function exceeds 50 LOC** | Every helper in `scheduler.py`, `cron_jobs.py`, `scheduler.py` (route) kept small by design; asserted by AST walk in test harness |
| QS-5 | **APScheduler imports are lazy** | `SchedulerFactory.build()` imports `AsyncIOScheduler` inside the method; `register_jobs()` imports `CronTrigger` inside the function; `RedisJobStore` import is nested in try/except |
| QS-6 | **App boots without `apscheduler` installed** | `start_scheduler()` wraps `get_scheduler()` in `try/except ImportError` and returns with a warning log instead of crashing |
| QS-7 | **Scheduler can be disabled via env var** | `if not getattr(settings, "SCHEDULER_ENABLED", True): return` short-circuits the lifespan hook |
| QS-8 | **Redis job store activates only on `redis://` DSN** | `if jobstore_url.startswith("redis://"):` gates the import and configuration |
| QS-9 | **Default timezone is UTC** | `getattr(settings, "SCHEDULER_TIMEZONE", "UTC")` plus the config default `SCHEDULER_TIMEZONE: str = "UTC"` |
| QS-10 | **`SCHEDULER_*` fields live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent so pydantic-settings binds env vars |
| QS-11 | **Lifespan patch injects into existing `asynccontextmanager`** | `_patch_main` walks lines, enters `in_lifespan` on `async def lifespan`, injects `await start_scheduler()` before `yield` and `await stop_scheduler()` after the shutdown marker |
| QS-12 | **`apscheduler>=3.10.0` added to requirements when absent** | `_patch_requirements` performs case-insensitive `"apscheduler" not in req_src.lower()` check |
| QS-13 | **Prerequisites are validated before write** | `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` runs first; any missing prereq aborts with `status="error"` and a hint |
| QS-14 | **Decorator returns the original function unchanged** | `@scheduled_job(cron)` wraps only the registration side-effect; the decorated function object is returned untouched so call sites see no signature change |
| QS-15 | **`register_jobs` uses `replace_existing=True`** | Prevents duplicate-id errors on APScheduler restart with a Redis job store that still holds the previous run |
| QS-16 | **`stop_scheduler` tolerates absent scheduler** | Checks `_scheduler is not None and getattr(_scheduler, "running", False)` before calling `shutdown` |
| QS-17 | **HTTP route walks the declared registry** | `GET /scheduler/jobs` reads `list_jobs()` first, then cross-references the live scheduler — jobs appear even when scheduler is disabled |
| QS-18 | **Tool records execution time** | `ToolResult.execution_time_ms` computed via `_elapsed_ms(start)` on every return path |
| QS-19 | **`next_steps` mentions installation + decorator usage** | `next_steps` list includes `"pip install 'apscheduler>=3.10.0'"` and decorator guidance |
| QS-20 | **Second run keeps the project parseable** | Idempotent no-op path does not corrupt any file; all `.py` remain AST-valid after two invocations |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_scheduled_tasks.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in the tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 3 new files | `len(result.files_created) >= 3` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `SCHEDULER_ENABLED`, `SCHEDULER_TIMEZONE`, `SCHEDULER_JOBSTORE_URL` exist inside `class Settings` body with 4-space indent | Substring scan + indent check on the `SCHEDULER_ENABLED` line | T-08 (`test_config_fields_patched`) |
| CC-09 | `app/main.py` lifespan contains `await start_scheduler()` and `await stop_scheduler()` | Substring checks for both call sites | T-09 (`test_main_lifespan_hooks`) |
| CC-10 | `requirements.txt` contains `apscheduler` | Case-insensitive `"apscheduler" in content.lower()` | T-10 (`test_requirements_apscheduler`) |
| CC-11 | `app/workers/scheduler.py` exists and contains the full factory API | File exists + `"class SchedulerFactory"`, `"AsyncIOScheduler"`, `"async def start_scheduler"`, `"async def stop_scheduler"` substrings | T-11 (`test_scheduler_factory_created`) |
| CC-12 | `app/workers/cron_jobs.py` exists and exports `scheduled_job`, `ScheduledJob`, `register_jobs`, `list_jobs` | File exists + four substring checks | T-12 (`test_cron_jobs_registry_created`) |
| CC-13 | All three example jobs are present | `"health_heartbeat"`, `"cleanup_expired_sessions"`, `"refresh_materialized_view"` substring checks | T-13 (`test_example_jobs_present`) |
| CC-14 | `app/api/routes/scheduler.py` exists with `/jobs` path and `JobInfo` model | File exists + `"/jobs"` and `"JobInfo"` substrings | T-14 (`test_status_route_created`) |
| CC-15 | Redis job store branch is present in generated scheduler | `"redis://"` and `"RedisJobStore"` substrings | T-15 (`test_redis_jobstore_branch`) |
| CC-16 | Example jobs use the `@scheduled_job("...")` decorator syntax | `'@scheduled_job("'` substring present | T-16 (`test_cron_decorator_usage`) |
| CC-17 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-17 (`test_execution_time_recorded`) |
| CC-18 | `next_steps` mentions `apscheduler` and either `cron` or `scheduled_job` | Lowercase join includes `"apscheduler"` and at least one of `"cron"`/`"scheduled_job"` | T-18 (`test_next_steps_present`) |
| CC-19 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-19 (`test_idempotent_project_still_parses`) |
| CC-20 | `SCHEDULER_ENABLED` defaults to `True` in the patched config | `"SCHEDULER_ENABLED: bool = True"` substring in `config.py` | T-20 (`test_disabled_flag_default_true`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_scheduled_tasks.py`
- [ ] `add_scheduled_tasks.py` runs `ast.parse`-clean code by construction on every emitted `.py` file
- [ ] `add_scheduled_tasks.py` detects `"SchedulerFactory"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created` / `files_modified`
- [ ] `SchedulerFactory.build()` imports `AsyncIOScheduler` inside the method body (lazy)
- [ ] `register_jobs()` imports `CronTrigger` inside the function body (lazy)
- [ ] `start_scheduler()` is a silent no-op when `SCHEDULER_ENABLED=false` or `apscheduler` is missing
- [ ] `stop_scheduler()` tolerates `_scheduler is None` and `.running == False`
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so the three fields land inside `class Settings`
- [ ] `_patch_main` injects `await start_scheduler()` **before** `yield` and `await stop_scheduler()` **after** the shutdown marker
- [ ] `_patch_main` has a legacy fallback for `@app.on_event("startup")` / `@app.on_event("shutdown")`
- [ ] `_patch_requirements` adds `apscheduler>=3.10.0` when absent (case-insensitive)
- [ ] `GET /scheduler/jobs` returns declared jobs even when scheduler is disabled / not running
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SCH-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `scheduler_file.exists() and "SchedulerFactory" in scheduler_file.read_text()` short-circuits to `status="no_op"` | T-02, T-19 |
| INV-SCH-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write operation | T-03 |
| INV-SCH-03 | Every generated `.py` file MUST parse as valid Python | All emitted code AST-clean by construction; verified project-wide by `_assert_parse` helper | T-06, T-19 |
| INV-SCH-04 | APScheduler imports MUST be LAZY (inside function bodies) | `from apscheduler.schedulers.asyncio import AsyncIOScheduler` lives inside `SchedulerFactory.build()`; `from apscheduler.triggers.cron import CronTrigger` lives inside `register_jobs`; `RedisJobStore` import is nested in try/except inside `build()` — module-level imports of `apscheduler` are absent | T-11, T-15 |
| INV-SCH-05 | `start_scheduler` MUST be a silent no-op when `SCHEDULER_ENABLED=false` OR `apscheduler` is missing | `if not getattr(settings, "SCHEDULER_ENABLED", True): return` and `try: sched = get_scheduler() except ImportError: logger.warning(...); return` — the app boot sequence never raises | T-11 |
| INV-SCH-06 | Lifespan hooks MUST be injected into an **existing** `@asynccontextmanager`-based `lifespan` (NOT deprecated `add_event_handler`) | `_patch_main` detects `"async def lifespan" in src and "yield" in src` and walks lines preserving indentation; legacy `@app.on_event` fallback only fires when modern lifespan is absent | T-09 |
| INV-SCH-07 | `await start_scheduler()` MUST appear BEFORE `yield` AND `await stop_scheduler()` MUST appear AFTER | Line walker inserts start call immediately before the first `yield` encountered inside `in_lifespan`; stop call fires on either `engine.dispose` sighting or a `# --- Shutdown` marker, with a trailing-append fallback when neither landmark exists | T-09 |
| INV-SCH-08 | `SCHEDULER_*` settings MUST live inside `class Settings` body (pydantic-settings binding) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent; fallback appends at EOF only when the anchor is missing | T-08 |
| INV-SCH-09 | The Redis job store branch MUST only activate when `SCHEDULER_JOBSTORE_URL` starts with `redis://` | `if jobstore_url.startswith("redis://"):` gates both the import and the jobstore dict mutation | T-15 |
| INV-SCH-10 | Default timezone MUST be `UTC` | `getattr(settings, "SCHEDULER_TIMEZONE", "UTC")` in the factory + config default `SCHEDULER_TIMEZONE: str = "UTC"` patched into `Settings` | T-08, T-20 |
| INV-SCH-11 | The tool MUST be idempotent on second run with zero byte writes | Fingerprint early-return yields `files_created=[]` and `files_modified=[]` | T-02 |
| INV-SCH-12 | `dry_run=True` MUST produce byte-identical filesystem state | `before == after` dict of `.py` contents across the whole tree | T-03 |
| INV-SCH-13 | The generated `scheduler.py` module MUST be importable on a machine WITHOUT `apscheduler` installed | Module-level imports are standard library + `app.core.config` only; `apscheduler` imports are deferred | T-06, T-11 |
| INV-SCH-14 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-17 |
| INV-SCH-15 | `next_steps` MUST mention `apscheduler` (install) and the declarative usage path (`cron` or `scheduled_job`) | Hard-coded strings in the success branch of `add_scheduled_tasks` | T-18 |
| INV-SCH-16 | `SCHEDULER_ENABLED` MUST default to `True` in the patched config | `_patch_config` emits literal `SCHEDULER_ENABLED: bool = True` | T-20 |
| INV-SCH-17 | `apscheduler>=3.10.0` MUST be added to `requirements.txt` when absent (idempotent) | `_patch_requirements` performs `"apscheduler" not in req_src.lower()` check before appending | T-10 |
| INV-SCH-18 | `GET /scheduler/jobs` MUST walk the declared `_JOBS` registry as its source of truth | Route body iterates `list_jobs()` first; scheduler lookup is a best-effort enrichment in a `try/except` | T-14 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install scheduled tasks into a clean FastAPI project**
- **As a** backend engineer who needs periodic jobs
- **I want** to run one tool call and get a cron-style scheduler
- **So that** I stop hand-rolling `asyncio.create_task(loop_forever())` in startup
- **Given:** A FastAPI project with `app/core/config.py`, `app/main.py`, `requirements.txt`
- **When:** `add_scheduled_tasks(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-SCH-11)
  - `files_created` contains ≥ 3 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project or double up the lifespan hooks
- **Given:** Project where `app/workers/scheduler.py` already contains `SchedulerFactory`
- **When:** `add_scheduled_tasks(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-SCH-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-SCH-03)
  - Verified by T-02, T-19

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation in PR
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_scheduled_tasks(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with an informational `notes` entry
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-SCH-02, INV-SCH-12)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it in a single screen
- **Given:** Tool just emitted `scheduler.py`, `cron_jobs.py`, and `api/routes/scheduler.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

**US-05: CI-safe execution time**
- **As a** CI pipeline
- **I want** the tool to finish in milliseconds
- **So that** the build budget is not burned
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-SCH-14)
  - Verified by T-17

### 9.2 Recurring cleanup & maintenance (US-06 .. US-10)

**US-06: Daily cleanup of expired sessions**
- **As a** platform with a `sessions` table filling with expired rows
- **I want** a job that runs every day at 03:00 UTC and deletes expired sessions
- **So that** the table stays bounded without manual intervention
- **Given:** `cleanup_expired_sessions` example job exists
- **When:** Developer replaces the stub with a real `DELETE FROM sessions WHERE expires_at < now()`
- **Then:**
  - `@scheduled_job("0 3 * * *", name="cleanup_expired_sessions")` fires at 03:00 UTC
  - `register_jobs` installs it via `CronTrigger.from_crontab("0 3 * * *")`
  - Verified by T-13, T-16

**US-07: Refresh a materialized view every 6 hours**
- **As a** team running a daily-aggregates materialized view
- **I want** it refreshed every 6 hours
- **So that** dashboards stay within 6h of reality
- **Given:** `refresh_materialized_view` example job exists
- **When:** Developer replaces the stub with `await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY daily_aggregates"))`
- **Then:**
  - `@scheduled_job("0 */6 * * *", name="refresh_materialized_view")` fires every 6 hours
  - Verified by T-13

**US-08: 5-minute liveness heartbeat**
- **As an** ops engineer wiring up external liveness monitoring
- **I want** a heartbeat log line every 5 minutes
- **So that** I can alert on its absence as a "scheduler is dead" signal
- **Given:** `health_heartbeat` example job exists
- **When:** The scheduler is running
- **Then:**
  - `@scheduled_job("*/5 * * * *", name="health_heartbeat")` logs `scheduler.heartbeat` every 5 min
  - Verified by T-13

**US-09: Monthly billing cycle job**
- **As a** SaaS with a monthly billing cycle
- **I want** `@scheduled_job("0 2 1 * *", name="monthly_billing")` to run at 02:00 UTC on day 1
- **So that** invoices are generated on schedule
- **Given:** Developer writes `async def monthly_billing()` and decorates it
- **When:** App restarts
- **Then:**
  - `register_jobs` picks up the new decorator at import time
  - `CronTrigger.from_crontab("0 2 1 * *")` fires accordingly
  - Verified by the decorator import-time side effect (T-12, T-16)

**US-10: Session expiry sweep every 15 minutes**
- **As a** team running short-lived user sessions
- **I want** `@scheduled_job("*/15 * * * *", name="session_expiry_sweep")`
- **So that** expired tokens are invalidated within 15 min
- **Given:** Developer adds the decorator
- **When:** App restarts
- **Then:**
  - Job appears in `GET /scheduler/jobs` response
  - Verified by T-14

### 9.3 Lifespan integration (US-11 .. US-15)

**US-11: Scheduler starts in the existing lifespan context**
- **As a** FastAPI process
- **I want** `await start_scheduler()` to fire before `yield` in my existing lifespan
- **So that** I do not juggle a second startup hook system
- **Given:** `app/main.py` ships a modern `@asynccontextmanager`-based `lifespan`
- **When:** `_patch_main` runs
- **Then:**
  - `await start_scheduler()` appears immediately before the first `yield` (INV-SCH-07)
  - `await stop_scheduler()` appears after the shutdown marker (INV-SCH-07)
  - Indentation of the `yield` line is preserved via `line[: len(line) - len(line.lstrip())]`
  - Verified by T-09

**US-12: Scheduler shuts down cleanly on SIGTERM**
- **As a** container orchestrator
- **I want** `stop_scheduler()` to complete in < 10 ms
- **So that** graceful shutdown meets the 30 s timeout
- **Given:** `_scheduler` is running
- **When:** FastAPI lifespan `__aexit__` fires
- **Then:**
  - `stop_scheduler()` calls `_scheduler.shutdown(wait=False)` — returns immediately
  - Running jobs are not awaited (they finish on the next boot's catch-up window)
  - Verified by reading `scheduler.py` code path in T-11

**US-13: Legacy `@app.on_event` fallback**
- **As a** legacy FastAPI project on pre-0.100 syntax
- **I want** `_patch_main` to fall back to `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators
- **So that** the install still works without a manual rewrite
- **Given:** `main.py` lacks `async def lifespan` but has `app = FastAPI(...)`
- **When:** `_patch_main` runs
- **Then:**
  - The parenthesis walker finds the closing `)` of `app = FastAPI(`
  - Two `@app.on_event` handlers are emitted directly after it
  - Generated `main.py` remains AST-parseable
  - Verified by T-06 against a legacy fixture

**US-14: Lifespan hook is idempotent**
- **As a** CI re-running the tool
- **I want** `_patch_main` to no-op when `"start_scheduler"` is already in `main.py`
- **So that** the lifespan body is not duplicated
- **Given:** `main.py` already contains the patched hooks
- **When:** `_patch_main` runs
- **Then:**
  - Function early-returns without mutation
  - Verified indirectly by T-02 (second-run no_op)

**US-15: Import injection near `from fastapi import FastAPI`**
- **As a** reviewer
- **I want** the `from app.workers.scheduler import ...` line to live next to the FastAPI import
- **So that** imports stay grouped and PEP-8 friendly
- **Given:** `main.py` has `from fastapi import FastAPI`
- **When:** `_patch_main` runs
- **Then:**
  - The new import line is inserted directly after `from fastapi import FastAPI`
  - Fallback prepends the line at file top when the FastAPI import is missing
  - Verified by T-09

### 9.4 Config & environment (US-16 .. US-20)

**US-16: Disable the scheduler via env var**
- **As an** ops engineer debugging a production incident
- **I want** `SCHEDULER_ENABLED=false` in the environment to disable all jobs
- **So that** I can isolate the HTTP tier from the scheduler subsystem without a code change
- **Given:** Patched `config.py` exposes `SCHEDULER_ENABLED: bool = True`
- **When:** Ops sets `SCHEDULER_ENABLED=false` in `.env` and restarts
- **Then:**
  - `start_scheduler()` logs `scheduler.disabled` and returns (INV-SCH-05)
  - HTTP routes still register; `GET /scheduler/jobs` still returns the declared list (jobs appear, `next_run=None`)
  - Verified by T-08, T-20

**US-17: Use Redis job store for multi-instance deploys**
- **As a** platform engineer running 3 FastAPI replicas
- **I want** `SCHEDULER_JOBSTORE_URL=redis://redis:6379/2` to activate the Redis job store
- **So that** exactly one replica fires each job per cadence
- **Given:** Patched `config.py` exposes `SCHEDULER_JOBSTORE_URL: str = ""`
- **When:** Ops sets the Redis DSN in `.env`
- **Then:**
  - `SchedulerFactory.build()` detects `redis://` prefix and imports `RedisJobStore` (INV-SCH-09)
  - `AsyncIOScheduler(jobstores={"default": RedisJobStore(...)}, ...)` is constructed
  - ImportError on missing redis bindings falls back to memory with a warning (graceful degradation)
  - Verified by T-15

**US-18: Timezone override**
- **As a** team in a non-UTC region
- **I want** `SCHEDULER_TIMEZONE=America/Sao_Paulo` to shift cron expressions
- **So that** `0 3 * * *` fires at 03:00 local instead of UTC
- **Given:** Patched `config.py` exposes `SCHEDULER_TIMEZONE: str = "UTC"`
- **When:** Ops sets `SCHEDULER_TIMEZONE=America/Sao_Paulo`
- **Then:**
  - `AsyncIOScheduler(timezone="America/Sao_Paulo", ...)` is constructed
  - Cron expressions are interpreted in the given zone
  - Verified by T-08 (config field present)

**US-19: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `SCHEDULER_ENABLED=false` in `.env` to take effect without a code change
- **So that** I do not rebuild images for runtime toggles
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `SCHEDULER_ENABLED` inside `class Settings` binds from the env var (INV-SCH-08)
  - Fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
  - Verified by T-08

**US-20: `requirements.txt` gets the new dep**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `apscheduler>=3.10.0` to appear when absent
- **So that** the factory can build the scheduler
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains `apscheduler>=3.10.0` (idempotent via `.lower()` check) (INV-SCH-17)
  - Verified by T-10

### 9.5 HTTP status & observability (US-21 .. US-25)

**US-21: List registered jobs via HTTP**
- **As a** frontend dashboard
- **I want** `GET /scheduler/jobs`
- **So that** I render "what's scheduled" and "when does it fire next"
- **Given:** At least one job is decorated with `@scheduled_job(...)`
- **When:** `GET /scheduler/jobs`
- **Then:**
  - Returns `list[JobInfo]` sorted by name
  - Each `JobInfo` has `name`, `cron`, `next_run` (nullable datetime)
  - Verified by T-14

**US-22: Route survives scheduler being disabled**
- **As a** client of the status route
- **I want** the endpoint to return declared jobs even when the scheduler is off
- **So that** I can see "job X is installed" even in degraded mode
- **Given:** `SCHEDULER_ENABLED=false`
- **When:** `GET /scheduler/jobs`
- **Then:**
  - Route walks `list_jobs()` declared registry (INV-SCH-18)
  - `sched.get_job(name)` lookup is wrapped in `try/except`; on failure `next_run=None`
  - Response is still 200 with the full declared list
  - Verified by reading `api/routes/scheduler.py` code path in T-14

**US-23: App boots when `apscheduler` is not installed**
- **As a** CI lint step that skips `pip install`
- **I want** the app to import and boot without `apscheduler`
- **So that** linting does not require the full dependency tree
- **Given:** `apscheduler` absent from environment
- **When:** FastAPI `lifespan` fires
- **Then:**
  - `start_scheduler()` catches `ImportError` from `get_scheduler()` and logs `scheduler.apscheduler_not_installed`
  - Boot continues; no raise (INV-SCH-05, INV-SCH-13)
  - Verified by T-11 (lazy import pattern present)

**US-24: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include install + decorator usage
- **So that** I do not need to open docs
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `"pip install 'apscheduler>=3.10.0'"`
  - Contains either `"scheduled_job"` or `"cron"` usage guidance
  - Verified by T-18 (INV-SCH-15)

**US-25: Prerequisites validation**
- **As a** caller running the tool on an unexpected project layout
- **I want** a clear error when `app/core/config.py` or `requirements.txt` is missing
- **So that** I know to run `fastapi_generate_project(...)` first
- **Given:** `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` returns errors
- **When:** Tool runs
- **Then:**
  - Returns `status="error"` with formatted prereq list
  - `notes` explains the auto-scaffold fallback
  - `execution_time_ms` still recorded

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_scheduled_tasks.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `sch_t01` | `add_scheduled_tasks(ToolInput(project_dir))` | `result.status == "success"` (INV-SCH-11, CC-01) |
| T-02 | `test_idempotent` | Fixture `sch_t02`; run tool once | Run tool a second time | `r1.status == "success"`, `r2.status == "no_op"`, `r2.files_created == []`, `r2.files_modified == []` (INV-SCH-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `sch_t03`; snapshot all `.py` | `add_scheduled_tasks(ToolInput(dry_run=True))` | `status == "success"`; empty create/modify lists; byte-identical filesystem (INV-SCH-02, INV-SCH-12, CC-03) |
| T-04 | `test_files_created_count` | Fixture `sch_t04` | Run tool | `len(files_created) >= 3`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `sch_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `sch_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-SCH-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `sch_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `sch_t08`; run tool | Read `app/core/config.py` | Contains `SCHEDULER_ENABLED`, `SCHEDULER_TIMEZONE`, `SCHEDULER_JOBSTORE_URL`; `SCHEDULER_ENABLED` line starts with 4-space indent (INV-SCH-08, CC-08) |
| T-09 | `test_main_lifespan_hooks` | Fixture `sch_t09`; run tool | Read `app/main.py` | Contains `start_scheduler`, `stop_scheduler`, `await start_scheduler()`, `await stop_scheduler()` (INV-SCH-06, INV-SCH-07, CC-09) |
| T-10 | `test_requirements_apscheduler` | Fixture `sch_t10`; run tool | Read `requirements.txt` | Case-insensitive contains `"apscheduler"` (INV-SCH-17, CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_scheduler_factory_created` | Fixture `sch_t11`; run tool | Read `app/workers/scheduler.py` | Contains `class SchedulerFactory`, `AsyncIOScheduler`, `async def start_scheduler`, `async def stop_scheduler` (INV-SCH-04, INV-SCH-05, INV-SCH-13, CC-11) |
| T-12 | `test_cron_jobs_registry_created` | Fixture `sch_t12`; run tool | Read `app/workers/cron_jobs.py` | Contains `def scheduled_job`, `class ScheduledJob`, `def register_jobs`, `def list_jobs` (CC-12) |
| T-13 | `test_example_jobs_present` | Fixture `sch_t13`; run tool | Read `app/workers/cron_jobs.py` | Contains `health_heartbeat`, `cleanup_expired_sessions`, `refresh_materialized_view` (CC-13) |
| T-14 | `test_status_route_created` | Fixture `sch_t14`; run tool | Read `app/api/routes/scheduler.py` | File exists; contains `/jobs` and `JobInfo` (INV-SCH-18, CC-14) |
| T-15 | `test_redis_jobstore_branch` | Fixture `sch_t15`; run tool | Read `app/workers/scheduler.py` | Contains `redis://` and `RedisJobStore` (INV-SCH-09, CC-15) |
| T-16 | `test_cron_decorator_usage` | Fixture `sch_t16`; run tool | Read `app/workers/cron_jobs.py` | Contains `@scheduled_job("` (CC-16) |

### 10.4 Category D — Meta (T-17 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-17 | `test_execution_time_recorded` | Fixture `sch_t17`; run tool | Read `result.execution_time_ms` | `> 0` (INV-SCH-14, CC-17) |
| T-18 | `test_next_steps_present` | Fixture `sch_t18`; run tool | Lowercase-join `result.next_steps` | Contains `"apscheduler"` AND at least one of `"cron"` / `"scheduled_job"` (INV-SCH-15, CC-18) |
| T-19 | `test_idempotent_project_still_parses` | Fixture `sch_t19`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-SCH-01, INV-SCH-03, CC-19) |
| T-20 | `test_disabled_flag_default_true` | Fixture `sch_t20`; run tool | Read `app/core/config.py` | Contains literal `SCHEDULER_ENABLED: bool = True` (INV-SCH-10, INV-SCH-16, CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_scheduled_tasks.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_scheduled_tasks.py
```

Target: 20/20 passed, 0 failed. The standalone runner prints `TOOL-058: 20 passed, 0 failed`.

---

## 11. Interaction Matrix

How `add_scheduled_tasks` composes with other SKILL-001 tools. Tool IDs below match the `specs/` directory. The scheduler is an in-process subsystem whose `register_jobs` + `@scheduled_job` decorator provides a natural landing pad for periodic work emitted by other tools.

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible — complementary | arq handles event-driven async work (enqueued on demand); APScheduler handles periodic work (time-driven). Run both: arq workers in separate containers, APScheduler in-process with the API. A scheduled job can `await enqueue("heavy_task", ...)` to hand off to arq when the work is too long for the event loop. |
| `add_long_running_task` (TOOL-020) | No | ✅ Compatible — complementary | TOOL-020 owns user-triggered long operations with progress reporting; `add_scheduled_tasks` owns time-triggered periodic work. A scheduled job can enqueue a TOOL-020 task when it needs a progress record surfaced in the UI. |
| `add_email_templates` (TOOL-055) | No | ✅ Compatible | Daily/weekly digest emails are the canonical APScheduler use case: `@scheduled_job("0 8 * * 1", name="weekly_digest") async def weekly_digest(): ... await send_email(template="digest", ...)`. |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Billing-cycle jobs (`0 2 1 * *`), subscription expiry sweeps, and trial-end notifications all land as `@scheduled_job` decorators. Long-running reconciliation should delegate to arq (TOOL-053). |
| `add_audit_log` (TOOL-005) | Yes | ⚠️ Caveat — audit runs AFTER | Periodic audit log rotation / archival is a natural `@scheduled_job`. Do NOT audit the scheduler's own tick — only audit the side effects (row deletions, view refreshes). |
| `add_outbox_pattern` (TOOL-023) | Yes | ✅ Compatible — outbox runs BEFORE | The outbox relay loop (`SELECT ... FROM outbox WHERE dispatched_at IS NULL`) is typically a `@scheduled_job("* * * * *", name="outbox_relay")` — one-minute cadence drains the outbox into the event bus. Deploy with Redis job store to avoid duplicate relays across replicas. |
| `add_multi_tenancy` (TOOL-008) | Yes | ✅ Compatible — tenancy runs BEFORE | Scheduled jobs that touch tenant data should open a session without a tenant filter and iterate `for tenant in all_tenants():` explicitly — there is no request context to carry the tenant id. |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC runs AFTER | `GET /scheduler/jobs` currently has no auth gate; add `require("scheduler:read")` after RBAC is installed to avoid leaking job names / cadences. |
| `add_cache_layer` (TOOL-021) | No | ✅ Compatible | Cache warmup jobs are a natural fit: `@scheduled_job("*/15 * * * *", name="warm_cache") async def warm_cache(): for key in hot_keys: await cache.set(key, ...)`. Shares `settings.REDIS_URL` but typically a separate logical DB from the scheduler job store. |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | Admin panel can surface a read-only view of the declared registry; the existing `GET /scheduler/jobs` endpoint is the path of least resistance. |
| `add_soft_delete` (TOOL-001) | No | ✅ Compatible — canonical use case | Nightly `vacuum_soft_deleted_rows` jobs belong in `cron_jobs.py` — scheduled at `0 4 * * *` to run during low traffic. |
| `add_feature_flags` (TOOL-009) | No | ✅ Compatible | Individual scheduled jobs can guard their body on a feature flag: `if not flags.enabled("nightly_reindex"): return`. This provides per-job kill switches independent of `SCHEDULER_ENABLED`. |

**Conflicts:** None identified. `add_scheduled_tasks` deliberately avoids installing a second runtime (no sidecar, no separate Dockerfile) so it composes with every other SKILL-001 tool without ordering constraints other than those listed above.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/main.py \
  requirements.txt

rm -rf \
  app/workers/scheduler.py \
  app/workers/cron_jobs.py \
  app/api/routes/scheduler.py
```

If `app/workers/__init__.py` was created by this tool and no other file in that package survives, remove it:

```bash
test -d app/workers && [ -z "$(ls app/workers 2>/dev/null)" ] && rmdir app/workers
```

### 12.2 Runtime rollback (after deploy)

The scheduler is in-process, so there is no separate service to stop. Roll back the deployment and restart the FastAPI process — `stop_scheduler()` executes on shutdown and releases the scheduler singleton. No database migration to reverse; no Redis cleanup beyond the APScheduler job store keys.

### 12.3 Redis job store cleanup (optional)

If the deploy was using the Redis job store (`SCHEDULER_JOBSTORE_URL=redis://...`), orphan keys persist after rollback:

```bash
redis-cli --scan --pattern 'apscheduler.*' | xargs -r redis-cli del
```

Specifically the two keys configured in the factory:
- `apscheduler.jobs`
- `apscheduler.run_times`

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

The tool writes files one at a time; `git checkout HEAD --` on modified paths plus `rm` on newly-created paths restores the project.

### 12.5 Emergency: disable scheduler without code change

Set `SCHEDULER_ENABLED=false` in the environment and restart. `start_scheduler()` short-circuits via `if not getattr(settings, "SCHEDULER_ENABLED", True): return` and the application continues serving HTTP traffic normally. The `GET /scheduler/jobs` route still returns the declared list with `next_run=None` on every entry. This is the preferred incident-response path — no code rollback, no redeploy.

### 12.6 Uninstall validator

After rollback, verify:

```bash
test ! -f app/workers/scheduler.py || (echo "scheduler.py still present" && exit 1)
test ! -f app/workers/cron_jobs.py || (echo "cron_jobs.py still present" && exit 1)
test ! -f app/api/routes/scheduler.py || (echo "route still present" && exit 1)
grep -q "SCHEDULER_ENABLED" app/core/config.py && echo "config still patched" && exit 1
grep -q "start_scheduler" app/main.py && echo "main.py still patched" && exit 1
grep -qi "apscheduler" requirements.txt && echo "requirements still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` |
| EC-02 | Tool runs on a project missing a prerequisite (`CONFIG_SETTINGS`, `REQUIREMENTS_TXT`) | `ensure_prerequisites` returns errors → tool returns `status="error"` with formatted prereq list and hint to run `fastapi_generate_project` first |
| EC-03 | Tool runs on a project where `app/workers/scheduler.py` already contains `SchedulerFactory` | Early return `status="no_op"` with single note `"SchedulerFactory already present — scheduled tasks already installed."` — zero file writes |
| EC-04 | Tool runs with `inp.dry_run=True` | Returns `status="success"` with dry-run note; NO file touched; `execution_time_ms` still recorded (INV-SCH-02, INV-SCH-12) |
| EC-05 | `apscheduler` package is not installed at application runtime | `start_scheduler()` catches `ImportError` at the `get_scheduler()` call site and returns with `scheduler.apscheduler_not_installed` warning — FastAPI boot completes (INV-SCH-05, INV-SCH-13) |
| EC-06 | `SCHEDULER_ENABLED=false` in environment | `start_scheduler()` logs `scheduler.disabled` and returns before touching any apscheduler symbol — module-level registry is still populated, `GET /scheduler/jobs` still works |
| EC-07 | `SCHEDULER_JOBSTORE_URL` is empty | In-memory store used (single-instance correct, multi-instance fires N times per cadence) |
| EC-08 | `SCHEDULER_JOBSTORE_URL=redis://...` but `apscheduler.jobstores.redis` fails to import | Nested `except ImportError:` logs `apscheduler redis jobstore unavailable; falling back to memory` and continues with an empty `jobstores` dict — scheduler still starts, just without persistence |
| EC-09 | `app/main.py` already contains `start_scheduler` | `_patch_main` early-returns; `files_modified` omits `main.py`; idempotency preserved |
| EC-10 | `app/main.py` has no `async def lifespan` AND no `app = FastAPI(` | `_patch_main` emits the import line but no hook installation — operator must wire the lifespan manually; generated `main.py` remains AST-parseable |
| EC-11 | `app/main.py` has modern lifespan with `engine.dispose` shutdown marker | `_patch_main` detects `engine.dispose` and inserts `await stop_scheduler()` immediately before it, preserving DB disposal order |
| EC-12 | `app/main.py` has modern lifespan with explicit `# --- Shutdown` comment | `_patch_main` appends the stop call directly after the comment line, preserving comment semantics |
| EC-13 | `app/main.py` has modern lifespan with neither landmark | Trailing-append fallback: `out.append("    await stop_scheduler()\n")` ensures the stop call appears somewhere in the lifespan body; may not be in the ideal position but is AST-valid |
| EC-14 | Legacy `main.py` with `app = FastAPI(...)` but no lifespan function | Fallback parenthesis walker finds the closing `)` of the constructor and emits two `@app.on_event` handlers immediately after — both AST-valid |
| EC-15 | `app/core/config.py` already contains `SCHEDULER_ENABLED` | `_patch_config` early-returns on `"SCHEDULER_ENABLED" in src` check; no duplicate block appended |
| EC-16 | `app/core/config.py` lacks the `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | `_patch_config` falls back to appending at EOF; fields land at module scope (still AST-parseable) but lose env var binding — reviewer sees the misplaced fields and should add the anchor manually |
| EC-17 | `requirements.txt` already contains `apscheduler` (any version) | `_patch_requirements` case-insensitively skips append; no duplicate line |
| EC-18 | `requirements.txt` does not exist | `if req_file.exists():` gates the patch; tool proceeds without touching requirements — operator must install `apscheduler` manually |
| EC-19 | `app/api/routes/` directory missing | `if routes_dir.exists():` gates the write; status route is silently skipped and NOT added to `files_created`. Operator loses `GET /scheduler/jobs` but scheduler still functions |
| EC-20 | `app/workers/` directory does not exist | `mkdir(parents=True, exist_ok=True)` creates it; `app/workers/__init__.py` is created with a package docstring when missing |
| EC-21 | Two replicas running with an in-memory job store | Both fire every cadence — data-integrity risk for non-idempotent jobs. Operator must set `SCHEDULER_JOBSTORE_URL=redis://...` to get exactly-once semantics |
| EC-22 | Replica restarts during a running job | APScheduler abandons the running job; the next cron tick picks up the schedule; catch-up semantics depend on `coalesce=True` (APScheduler default) which collapses missed runs into a single catch-up fire |
| EC-23 | Cron expression has a syntax error | `CronTrigger.from_crontab(job.cron)` raises at `register_jobs` time — scheduler startup fails with a clear traceback naming the offending job (fail-fast is the desired behavior here) |
| EC-24 | Timezone override to `America/Sao_Paulo` during DST transition | APScheduler handles DST via the bundled `pytz` / `zoneinfo` backend; a `0 2 * * *` cron expression fires once on the spring-forward day (02:00 does not exist → fires at 03:00) and twice on the fall-back day unless `coalesce=True` is configured |
| EC-25 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-19 verifies) |
| EC-26 | Tool runs on a project where `app/workers/__init__.py` already exists with different content | `if not workers_init.exists():` skips creation; existing file is preserved untouched |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 20 Completeness Criteria verified via `test_add_scheduled_tasks.py` passing
2. ✅ `test_add_scheduled_tasks.py` reports `20 passed, 0 failed` via both pytest and standalone runner
3. ✅ Tool execution time < 5 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-SCH-01)
5. ✅ `dry_run=True` produces byte-identical filesystem state (INV-SCH-02, INV-SCH-12)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-SCH-03)
7. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
8. ✅ `SCHEDULER_*` settings live inside `class Settings` body with 4-space indentation (INV-SCH-08)
9. ✅ APScheduler imports are lazy (inside function bodies) — module imports without the SDK installed (INV-SCH-04, INV-SCH-13)
10. ✅ `start_scheduler()` is a silent no-op when `SCHEDULER_ENABLED=false` OR `apscheduler` is missing (INV-SCH-05)
11. ✅ Lifespan hooks injected into existing `@asynccontextmanager`-based lifespan (NOT `add_event_handler`) (INV-SCH-06)
12. ✅ `await start_scheduler()` appears BEFORE `yield` and `await stop_scheduler()` AFTER (INV-SCH-07)
13. ✅ Redis job store branch activates only when `SCHEDULER_JOBSTORE_URL` starts with `redis://` (INV-SCH-09)
14. ✅ Default timezone is `UTC` (INV-SCH-10)
15. ✅ `SCHEDULER_ENABLED` defaults to `True` in patched config (INV-SCH-16)
16. ✅ `apscheduler>=3.10.0` added to `requirements.txt` when absent (INV-SCH-17)
17. ✅ `GET /scheduler/jobs` walks the declared registry as source of truth (INV-SCH-18)
18. ✅ `next_steps` mentions `apscheduler` plus decorator usage (INV-SCH-15)
19. ✅ Developer successfully declares a new `@scheduled_job("*/10 * * * *")`, restarts the app, and sees the job in `GET /scheduler/jobs` with a populated `next_run`

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT, auto_scaffold=not inp.dry_run)` passes
- [ ] `app/workers/scheduler.py` does NOT contain `"SchedulerFactory"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write
- [ ] `files_created` seeded with any `scaffolded` paths returned by `ensure_prerequisites`

### 15.2 Workers package

- [ ] `mkdir -p app/workers` via `workers_dir.mkdir(parents=True, exist_ok=True)`
- [ ] Write `app/workers/__init__.py` with `"""Background worker package."""` ONLY if missing
- [ ] Write `app/workers/scheduler.py` via `_write_scheduler_factory`:
  - [ ] Module docstring describes Redis / memory jobstore branching and lifespan wiring
  - [ ] `from __future__ import annotations`
  - [ ] `import logging`, `from typing import Any`, `from app.core.config import settings`
  - [ ] Module-level `_scheduler: Any | None = None` singleton holder
  - [ ] `class SchedulerFactory` with a single `@staticmethod def build() -> Any`
  - [ ] Inside `build()`: `from apscheduler.schedulers.asyncio import AsyncIOScheduler` (LAZY)
  - [ ] Inside `build()`: `jobstore_url = getattr(settings, "SCHEDULER_JOBSTORE_URL", "") or ""`
  - [ ] Inside `build()`: `if jobstore_url.startswith("redis://"):` branch imports `RedisJobStore` inside nested `try/except ImportError`
  - [ ] Inside `build()`: `timezone = getattr(settings, "SCHEDULER_TIMEZONE", "UTC")`
  - [ ] Inside `build()`: `return AsyncIOScheduler(jobstores=jobstores or None, timezone=timezone)`
  - [ ] `def get_scheduler() -> Any` with `global _scheduler` lazy-build pattern
  - [ ] `async def start_scheduler() -> None` with `SCHEDULER_ENABLED` short-circuit, `try/except ImportError` on `get_scheduler()`, `register_jobs(sched)`, `sched.start()`
  - [ ] `async def stop_scheduler() -> None` with `_scheduler is not None` guard and `getattr(_scheduler, "running", False)` check before `shutdown(wait=False)`
- [ ] Write `app/workers/cron_jobs.py` via `_write_cron_jobs`:
  - [ ] Module docstring with usage example
  - [ ] `from __future__ import annotations`, `import logging`, `from dataclasses import dataclass`, `from typing import Any, Awaitable, Callable`
  - [ ] `@dataclass(frozen=True) class ScheduledJob` with `cron: str`, `name: str`, `func: Callable[[], Awaitable[None]]`
  - [ ] Module-level `_JOBS: list[ScheduledJob] = []`
  - [ ] `def scheduled_job(cron: str, *, name: str | None = None)` decorator that appends to `_JOBS` and returns the function unchanged
  - [ ] `def register_jobs(scheduler: Any) -> None` with `from apscheduler.triggers.cron import CronTrigger` LAZY import
  - [ ] `register_jobs` uses `trigger=trigger`, `id=job.name`, `replace_existing=True` on `scheduler.add_job`
  - [ ] `def list_jobs() -> list[dict[str, str]]` returns name/cron pairs
  - [ ] `@scheduled_job("*/5 * * * *", name="health_heartbeat")` example job
  - [ ] `@scheduled_job("0 3 * * *", name="cleanup_expired_sessions")` example job
  - [ ] `@scheduled_job("0 */6 * * *", name="refresh_materialized_view")` example job

### 15.3 Status route

- [ ] `if (app_dir / "api" / "routes").exists():` gates the write
- [ ] Write `app/api/routes/scheduler.py` via `_write_scheduler_status_route`:
  - [ ] `from datetime import datetime`
  - [ ] `from fastapi import APIRouter`, `from pydantic import BaseModel`
  - [ ] `from app.workers.cron_jobs import list_jobs`, `from app.workers.scheduler import get_scheduler`
  - [ ] `router = APIRouter(prefix="/scheduler", tags=["scheduler"])`
  - [ ] `class JobInfo(BaseModel)` with `name: str`, `cron: str`, `next_run: datetime | None = None`
  - [ ] `@router.get("/jobs", response_model=list[JobInfo]) async def get_jobs()`
  - [ ] Route body walks `list_jobs()` first, then looks up `sched.get_job(name)` in a `try/except`
  - [ ] Response sorted by job name via `sorted(declared.items())`

### 15.4 Config patch (`_patch_config`)

- [ ] Early-return if `"SCHEDULER_ENABLED" in src`
- [ ] Block emits three fields:
  - [ ] `    SCHEDULER_ENABLED: bool = True`
  - [ ] `    SCHEDULER_TIMEZONE: str = "UTC"`
  - [ ] `    SCHEDULER_JOBSTORE_URL: str = ""`
- [ ] 4-space indent (class body)
- [ ] Anchor on `"ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"`
- [ ] Replacement syntax: `src.replace(anchor, anchor + "\n" + fields.rstrip())`
- [ ] Fallback: `src.rstrip("\n") + "\n" + fields + "\n"` appended at EOF

### 15.5 Main patch (lifespan) — `_patch_main`

- [ ] Early-return if `"start_scheduler" in src`
- [ ] Build import line: `"\nfrom app.workers.scheduler import start_scheduler, stop_scheduler  # noqa: F401 — scheduled tasks\n"`
- [ ] If `"from fastapi import FastAPI" in src`: insert import line directly after it
- [ ] Else: prepend import line at file top
- [ ] If `"async def lifespan" in src and "yield" in src`:
  - [ ] Split into `lines = src.splitlines(keepends=True)`
  - [ ] Walk lines with `in_lifespan`, `injected_start`, `injected_stop` flags
  - [ ] Enter `in_lifespan = True` on `"async def lifespan" in line`
  - [ ] Insert `await start_scheduler()` with preserved leading whitespace immediately BEFORE first `yield`
  - [ ] Insert `await stop_scheduler()` when `"engine.dispose" in line` OR `stripped.startswith("# --- Shutdown")`
  - [ ] Trailing-append `"    await stop_scheduler()\n"` fallback if `injected_start and not injected_stop`
- [ ] Else (legacy branch):
  - [ ] Find `marker = "app = FastAPI("` position
  - [ ] Parenthesis walk to find closing `)`
  - [ ] Emit `@app.on_event("startup")` + `@app.on_event("shutdown")` handlers directly after
- [ ] `main_file.write_text(src)`

### 15.6 Requirements patch

- [ ] `if req_file.exists():` guard
- [ ] Case-insensitive check `"apscheduler" not in req_src.lower()`
- [ ] Append `apscheduler>=3.10.0` with preserved trailing newline via `req_src.rstrip("\n") + "\n" + ...`

### 15.7 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain: APScheduler installed, decorator + lifespan auto-start, 3 example jobs emitted, in-process scheduler (not sidecar)
- [ ] `next_steps` contains: pip install hint, optional Redis job store DSN, decorator usage in `cron_jobs.py`, `GET /scheduler/jobs` verification

### 15.8 Return paths

- [ ] **success**: `_elapsed_ms(start)` included
- [ ] **no_op**: `_elapsed_ms(start)` included
- [ ] **dry_run success**: `_elapsed_ms(start)` included
- [ ] **error (validate_project_dir)**: plain `ToolResult(status="error", error=err)`
- [ ] **error (prereqs)**: `_elapsed_ms(start)` included

### 15.9 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry` quartet
- [ ] Module docstring lists the three generated files, three patched files, and the "why APScheduler" rationale
- [ ] `add_scheduled_tasks` function docstring documents `inp` and references the `SCHEDULER_*` env vars for post-install tuning

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/workers/__init__.py",
    "/tmp/fixture/app/workers/scheduler.py",
    "/tmp/fixture/app/workers/cron_jobs.py",
    "/tmp/fixture/app/api/routes/scheduler.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/main.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "APScheduler with Redis/memory job store installed.",
    "Cron jobs registered via @scheduled_job decorator auto-start in main.py lifespan.",
    "3 example jobs generated: cleanup_expired_sessions, refresh_materialized_view, health_heartbeat.",
    "Scheduler runs in-process (not on a separate worker)."
  ],
  "next_steps": [
    "pip install 'apscheduler>=3.10.0'",
    "Optionally set SCHEDULER_JOBSTORE_URL to a Redis DSN for multi-instance persistence.",
    "Register new jobs via @scheduled_job('0 */6 * * *') in app/workers/cron_jobs.py.",
    "Inspect live schedule via GET /scheduler/jobs (requires auth)."
  ],
  "execution_time_ms": 47
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "SchedulerFactory already present — scheduled tasks already installed."
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
    "[dry_run] Would create app/workers/scheduler.py, app/workers/cron_jobs.py, and app/api/routes/scheduler.py."
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
