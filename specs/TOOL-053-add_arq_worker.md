---
spec_id: "TOOL-053"
tool_name: "add_arq_worker"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-ARQ-01"
  - "INV-ARQ-02"
  - "INV-ARQ-03"
  - "INV-ARQ-04"
  - "INV-ARQ-05"
  - "INV-ARQ-06"
  - "INV-ARQ-07"
  - "INV-ARQ-08"
  - "INV-ARQ-09"
  - "INV-ARQ-10"
  - "INV-ARQ-11"
  - "INV-ARQ-12"
  - "INV-ARQ-13"
  - "INV-ARQ-14"
  - "INV-ARQ-15"
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
# TOOL-053: add_arq_worker

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_arq_worker` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, Redis, arq, SQLAlchemy 2.0, Alembic, pydantic-settings |
| Signature | `add_arq_worker(inp: ToolInput, *, max_jobs: int = 10, job_timeout_seconds: int = 300, max_tries: int = 3, keep_results_seconds: int = 86400) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag<br>`max_jobs`: Maximum concurrent jobs per worker process (default: 10, maps to `WorkerSettings.max_jobs`)<br>`job_timeout_seconds`: Per-job hard wall-clock timeout in seconds (default: 300, maps to `WorkerSettings.job_timeout`)<br>`max_tries`: Maximum attempts per job before permanent failure (default: 3, maps to `WorkerSettings.max_tries`)<br>`keep_results_seconds`: Retention period for completed job results in Redis (default: 86400, maps to `WorkerSettings.keep_result`) |
| MCP descriptor | `{"name": "fastapi_add_arq_worker", "description": "Add an arq (Redis-backed async) job queue with worker, task registry, and HTTP status routes.", "tags": ["extend", "infrastructure"], "entry": "add_arq_worker"}` |
| Files created (typical) | 9 — `app/workers/__init__.py`, `app/workers/arq_worker.py`, `app/workers/tasks.py`, `app/workers/enqueue.py`, `app/models/job.py`, `app/schemas/job.py`, `app/crud/job.py`, `app/api/routes/jobs.py`, `alembic/versions/add_arq_worker.py`, `Dockerfile.worker` |
| Files modified (typical) | 4 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py`, `app/main.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_arq_worker` tool installs a production-grade asynchronous job queue into a FastAPI project using **arq** (Redis-backed async runner) **without** dragging in the Celery ecosystem (brokers, result backends, eventlet/gevent monkey-patching, kombu, billiard, and the half-decade of CVE-prone C-extension transitive deps that come with them). Teams reach for Celery reflexively because it is the name they know, but a modern `async def` FastAPI application pays a brutal impedance tax running a synchronous worker runtime: every I/O call becomes a thread, every Redis/DB client is duplicated (sync + async), and the mental model of "queue vs broker vs backend vs beat" has three more moving parts than a small service actually needs. The alternative — "just use `BackgroundTasks`" — fails the moment a worker dies mid-job, a retry must survive a deploy, or operators need to see what is running. arq sits exactly in that gap: one Redis for queue AND result storage, `async def` tasks that share the FastAPI process's existing async libraries, declarative retries and timeouts, and a surface area small enough (`WorkerSettings`, `functions`, `on_startup`, `on_shutdown`) to audit in an afternoon.

This tool generates the entire kit a real service needs so developers do not assemble it by hand (and get 60% of it wrong on the first try). It emits: (a) an `app/workers/` package with `arq_worker.py` exposing `WorkerSettings` and a `python -m app.workers.arq_worker` CLI entry point for `Dockerfile.worker` to invoke; (b) `tasks.py` containing `startup`/`shutdown` hooks plus three example tasks (`send_email_task`, `cleanup_task`, `webhook_retry_task`) demonstrating I/O, scheduled, and retry patterns, all wired into a single `TASK_REGISTRY` list that `WorkerSettings.functions` references; (c) `enqueue.py` with a process-wide `ArqRedis` pool (cached on `app.state.arq_pool` via FastAPI lifespan — **not** per-request), `get_pool()` singleton fallback for non-HTTP callers, and an `enqueue(task_name, *args, _defer_by=None, **kwargs) -> str` helper that raises `RuntimeError` if arq refuses the job (queue full / duplicate id) instead of silently losing work; (d) a durable `Job` SQLAlchemy audit model with `tenant_id`, `task_name`, `status`, `payload` (JSONB), `result` (JSONB), `error`, and timestamp lifecycle columns, automatically tenant-aware when `app/models/tenant.py` is detected in the target project; (e) matching Pydantic schemas (`JobStatus` enum, `JobPublic`, `JobListResponse`), async CRUD helpers (`record_job`, `update_job_started`, `update_job_completed`, `update_job_failed`, `list_user_jobs`), HTTP companion routes (`GET /jobs/{job_id}/status`, `GET /jobs/active`) guarded by `CurrentUser` so job state cannot be probed anonymously, an Alembic migration wired to the current migration head with conditional tenant FK, and a `Dockerfile.worker` that runs as non-root `USER 1000` and invokes the worker via `python -m app.workers.arq_worker`. The tool patches `app/core/config.py` with four `ARQ_*` settings anchored on the existing `ACCESS_TOKEN_EXPIRE_MINUTES` field (so they land **inside** `class Settings` and pydantic-settings picks them up from env vars), injects `arq>=0.25.0` and `redis[hiredis]>=5.0.0` into `requirements.txt`, and rewrites `app/main.py`'s FastAPI lifespan to create/close the arq pool exactly once per process.

Key design decisions: Redis DSN is **always** read from `settings.REDIS_URL` — the worker never invents a new DSN or hard-codes a host, which means rotating Redis credentials is a pure env-var operation; the arq pool is created **once** per FastAPI worker process and cached on `app.state.arq_pool` (per-request connection churn is the number-one cause of "works in dev, melts in prod" arq deployments); audit persistence to the `jobs` table is a **second** source of truth for **critical** jobs (payments, webhooks) where operators need a permanent record surviving Redis eviction, while non-critical jobs rely on arq's native Redis-backed result storage; task handlers are plain `async def` functions accepting a `ctx: dict[str, Any]` first positional (arq's worker context carrying `job_id`, `job_try`, `redis`) — no class hierarchies, no decorators, no hidden registration magic; the worker process is **containerized separately** from the API process (`Dockerfile.worker`) so ops can scale HTTP traffic and background throughput independently and a memory leak in one task class cannot take down the API tier; the tool is idempotent by fingerprint detection (`"WorkerSettings" in app/workers/arq_worker.py`) and returns `status="no_op"` on second invocation without touching any file, so it is safe to re-run in CI. The rollback path is mechanical: nine files created + four patched, all of them bounded and individually revertable.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (T-18) |
| Files created | ≥ 8 | Worker kit requires workers package, tasks, worker module, enqueue, Job model, schemas, CRUD, routes, migration, Dockerfile (T-04) |
| Files modified | ≥ 2 | Config, models `__init__`, main, requirements — at least two of these must exist (T-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (T-07) |
| arq pool creation | 1 per process | Cached on `app.state.arq_pool` via lifespan — no per-request allocation |
| `enqueue()` latency | < 10 ms | Single Redis `LPUSH` via arq; bounded by network RTT to Redis |
| `GET /jobs/{job_id}/status` latency | < 20 ms | Single arq `Job(job_id, pool).status()` + `.info()` Redis round trip |
| `GET /jobs/active` latency | < 50 ms | `pool.queued_jobs()` scan bounded by queue depth |
| Worker pickup delay | < 1 s | arq polls the queue every 500 ms by default |
| Job timeout enforcement | ≤ `job_timeout_seconds` + 1 s | arq wraps task execution in `asyncio.wait_for` |
| Result TTL | = `keep_results_seconds` | Redis `EXPIRE` set by arq on job result hash |
| Migration runtime | < 1 s | Single `CREATE TABLE` + 2 indexes |
| Dockerfile worker cold start | < 30 s | Slim Python 3.12 base + `pip install -r requirements.txt` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no arq pool in lifespan
│   ├── core/
│   │   └── config.py        # Settings class, no ARQ_* fields
│   ├── models/
│   │   ├── __init__.py      # Base + User imports only
│   │   └── base.py
│   ├── routes/
│   │   └── __init__.py      # api_router, no jobs router
│   └── api/
│       └── deps.py          # CurrentUser dependency
├── alembic/versions/
│   └── 0001_initial.py
└── requirements.txt         # no arq, no redis
```

Every background operation blocks the request handler. A 30-second PDF render holds a worker until it finishes; three concurrent renders consume the entire Gunicorn pool; retries on failure require bespoke `try/except` ladders with ad-hoc exponential backoff; there is no operator visibility into what is pending.

### 4.2 Worker runtime module: AFTER

```python
# app/workers/arq_worker.py
"""arq worker runtime.

Provides ``WorkerSettings`` consumed by the arq CLI and a
``python -m app.workers.arq_worker`` entry point so the worker can be
started directly (used by ``Dockerfile.worker``).

Redis DSN, concurrency, per-job timeout, max retries, and result
retention are read from ``app.core.config.settings`` — the worker
does not invent its own config.
"""
from __future__ import annotations

from arq.connections import RedisSettings

from app.core.config import settings
from app.workers.tasks import TASK_REGISTRY, shutdown, startup


class WorkerSettings:
    """arq worker configuration.

    Attributes:
        functions: Task functions registered for execution.
        redis_settings: Redis connection parameters (derived from
            ``settings.REDIS_URL``).
        max_jobs: Maximum concurrent jobs per worker process.
        job_timeout: Per-job hard wall-clock timeout in seconds.
        max_tries: Maximum retry attempts before permanent failure.
        keep_result: How long to retain completed job results in Redis.
        on_startup: Async callable invoked once when the worker boots.
        on_shutdown: Async callable invoked once when the worker exits.
    """

    functions = TASK_REGISTRY
    redis_settings = RedisSettings.from_dsn(str(settings.REDIS_URL))
    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = settings.ARQ_JOB_TIMEOUT_SECONDS
    max_tries = settings.ARQ_MAX_TRIES
    keep_result = settings.ARQ_KEEP_RESULTS_SECONDS
    on_startup = startup
    on_shutdown = shutdown


def main() -> None:
    """Run the arq worker until interrupted.

    Delegates to ``arq.worker.run_worker`` which handles signal
    trapping, graceful shutdown, and job draining.
    """
    from arq.worker import run_worker

    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
```

### 4.3 Task registry module: AFTER

```python
# app/workers/tasks.py
"""arq task registry and example tasks.

Every task here must be ``async def`` and must accept ``ctx`` (an
arq-provided dict with ``job_id``, ``job_try``, ``redis``, etc.) as
its first positional argument.

To register a new task:

1. Write your ``async def my_task(ctx, ...): ...`` function.
2. Append it to ``TASK_REGISTRY``.
3. Restart the worker (or roll-restart in production).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    """Worker startup hook.

    Runs once per worker process. Use this hook to open long-lived
    resources (database pools, HTTP clients) and stash them on
    ``ctx`` for task access.

    Args:
        ctx: arq worker context dict. Mutated in-place.
    """
    logger.info("arq worker starting up", extra={"worker": "arq"})
    ctx["started_at"] = True


async def shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown hook.

    Runs once per worker process on graceful exit. Close any
    resources opened in ``startup``.

    Args:
        ctx: arq worker context dict.
    """
    logger.info("arq worker shutting down", extra={"worker": "arq"})


async def send_email_task(
    ctx: dict[str, Any],
    to: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """Example I/O task: send a transactional email.

    Replace the body with a real email client (``aiosmtplib``,
    Postmark, SES, ...) in production.
    """
    job_id = ctx.get("job_id", "unknown")
    logger.info(
        "send_email_task executing",
        extra={"job_id": job_id, "to": to, "subject": subject},
    )
    _ = body
    return {"status": "sent", "to": to, "job_id": job_id}


async def cleanup_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Example scheduled cleanup task (no task arguments)."""
    job_id = ctx.get("job_id", "unknown")
    logger.info("cleanup_task executing", extra={"job_id": job_id})
    return {"status": "ok", "cleaned": 0, "job_id": job_id}


async def webhook_retry_task(
    ctx: dict[str, Any],
    delivery_id: str,
    url: str,
    payload: dict[str, Any],
    signature: str,
) -> dict[str, Any]:
    """Retry a failed webhook delivery."""
    job_id = ctx.get("job_id", "unknown")
    logger.info(
        "webhook_retry_task executing",
        extra={
            "job_id": job_id,
            "delivery_id": delivery_id,
            "url": url,
            "payload_keys": list(payload.keys()),
            "signature_len": len(signature),
        },
    )
    return {
        "status": "retried",
        "delivery_id": delivery_id,
        "job_id": job_id,
    }


TASK_REGISTRY: list[Any] = [
    send_email_task,
    cleanup_task,
    webhook_retry_task,
]
```

### 4.4 Enqueue helper (pool + `enqueue()`): AFTER

```python
# app/workers/enqueue.py
"""FastAPI-friendly enqueue helpers for the arq worker.

The arq Redis pool is expensive to create; we want exactly ONE per
FastAPI worker process. ``create_arq_pool`` is called from the
FastAPI lifespan hook in ``app/main.py`` and the resulting pool is
cached on ``app.state.arq_pool``.
"""
from __future__ import annotations

import logging
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


async def create_arq_pool() -> ArqRedis:
    """Create a fresh arq Redis pool.

    Called from the FastAPI lifespan startup hook exactly once per
    process. The returned pool is stored on ``app.state.arq_pool``.
    """
    pool = await create_pool(
        RedisSettings.from_dsn(str(settings.REDIS_URL))
    )
    return pool


async def close_arq_pool(pool: ArqRedis) -> None:
    """Close the given arq Redis pool on shutdown."""
    try:
        await pool.close(close_connection_pool=True)
    except Exception:  # noqa: BLE001
        logger.warning("arq pool close failed", exc_info=True)


async def get_pool() -> ArqRedis:
    """Return the singleton arq Redis pool, creating it lazily.

    Convenience for code paths that do not have access to
    ``request.app.state.arq_pool`` (e.g. background scripts).
    """
    global _pool
    if _pool is None:
        _pool = await create_arq_pool()
    return _pool


async def enqueue(
    task_name: str,
    *args: Any,
    _defer_by: int | None = None,
    **kwargs: Any,
) -> str:
    """Enqueue *task_name* on the arq queue and return the job id.

    Args:
        task_name: Registered function name (must appear in
            ``TASK_REGISTRY``).
        *args: Positional arguments forwarded to the task function.
        _defer_by: Optional delay in seconds before the job becomes
            eligible for execution. ``None`` means run ASAP.
        **kwargs: Keyword arguments forwarded to the task function.

    Returns:
        The arq job id (string). Callers can use this id to poll
        ``GET /jobs/{job_id}/status``.

    Raises:
        RuntimeError: If arq returns no job (enqueue rejected).
    """
    pool = await get_pool()
    kw: dict[str, Any] = {}
    if _defer_by is not None:
        kw["_defer_by"] = _defer_by
    job = await pool.enqueue_job(task_name, *args, **kwargs, **kw)
    if job is None:
        raise RuntimeError(
            f"arq refused to enqueue task={task_name} (queue full or duplicate job id)"
        )
    return job.job_id
```

### 4.5 Job audit model (tenant-aware): AFTER

```python
# app/models/job.py
"""SQLAlchemy model for durable audit of arq background jobs.

The arq library already persists job state in Redis with a TTL. This
table is a SECOND source of truth for CRITICAL jobs where auditors
or operators need a permanent record that survives Redis eviction.
Non-critical jobs should rely on Redis alone.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Job(Base):
    """A durable audit record of a background job execution."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),  # omitted when no tenant model
        nullable=True,
        index=True,
        comment="Tenant owning this job record",
    )
    task_name: Mapped[str] = mapped_column(String(127), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        Index("ix_jobs_status_enqueued", "status", "enqueued_at"),
        Index("ix_jobs_user_enqueued", "user_id", "enqueued_at"),
    )
```

### 4.6 HTTP companion routes (status polling): AFTER

```python
# app/api/routes/jobs.py
"""HTTP companion routes for the arq background job queue.

Provides job introspection endpoints for UI dashboards and operators.
Both endpoints require authentication so job state cannot be probed
by unauthenticated clients.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _require_pool(request: Request):
    """Return the arq pool from app state or raise 503."""
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="arq pool not initialised",
        )
    return pool


async def _fetch_job(job_id: str, pool) -> tuple:
    """Fetch (status, info) for *job_id* or raise 404 on lookup failure."""
    try:
        from arq.jobs import Job as ArqJob
        job = ArqJob(job_id, pool)
        return await job.status(), await job.info()
    except Exception as exc:  # noqa: BLE001
        logger.warning("arq job lookup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        ) from exc


def _extract_outcome(info) -> tuple:
    """Return (result, error) from an arq JobResult info object."""
    if info is None:
        return None, None
    success = getattr(info, "success", None)
    if success is True:
        return getattr(info, "result", None), None
    if success is False:
        return None, str(getattr(info, "result", "") or "job failed")
    return None, None


@router.get("/{job_id}/status")
async def get_job_status(
    job_id: str,
    request: Request,
    current_user: CurrentUser,
) -> dict:
    """Return the current status (and result/error) of *job_id*.

    Reads job state from the live arq Redis pool attached to
    ``request.app.state.arq_pool``.
    """
    _ = current_user  # auth gate only
    pool = _require_pool(request)
    job_status, info = await _fetch_job(job_id, pool)
    result_value, error_value = _extract_outcome(info)
    return {
        "job_id": job_id,
        "status": str(job_status).split(".")[-1].lower(),
        "result": result_value,
        "error": error_value,
    }


@router.get("/active")
async def list_active_jobs(
    request: Request,
    current_user: CurrentUser,
) -> dict:
    """Return currently-queued job ids for ops dashboards."""
    _ = current_user  # auth gate only
    pool = _require_pool(request)
    try:
        jobs = await pool.queued_jobs()
        ids = [getattr(j, "job_id", "") for j in jobs]
    except Exception as exc:  # noqa: BLE001
        logger.warning("arq queued_jobs lookup failed: %s", exc)
        ids = []
    return {"data": ids, "count": len(ids)}
```

### 4.7 Dockerfile.worker (CLI entry, non-root): AFTER

```dockerfile
# Dockerfile.worker — arq background job worker
# Built and run SEPARATELY from the FastAPI API container so workers
# can be scaled independently of HTTP traffic.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Run as non-root for least-privilege execution.
USER 1000

CMD ["python", "-m", "app.workers.arq_worker"]
```

### 4.8 Config patch (settings injected inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- arq worker settings — added by add_arq_worker tool ---
    ARQ_MAX_JOBS: int = 10
    ARQ_JOB_TIMEOUT_SECONDS: int = 300
    ARQ_MAX_TRIES: int = 3
    ARQ_KEEP_RESULTS_SECONDS: int = 86400
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables. Appending at module level would create module-scope attributes the generated worker code cannot reach.

### 4.9 `app/main.py` lifespan patch (pool create/close)

```python
# app/main.py  (diff, added by _patch_main)
from app.workers.enqueue import close_arq_pool, create_arq_pool
# ...
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq_pool = await create_arq_pool()
    yield
    await close_arq_pool(app.state.arq_pool)
```

### 4.10 Alembic migration (tenant-aware conditional)

```python
# alembic/versions/add_arq_worker.py
"""Add jobs table for durable audit of arq background jobs.

Revision ID: add_arq_worker
Revises: <current_head>
Create Date: auto-generated by add_arq_worker tool
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "add_arq_worker"
down_revision = "<current_head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the jobs table with status + user_id indexes."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),  # omitted when no tenant model
            nullable=True,
        ),
        sa.Column("task_name", sa.String(127), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_jobs_status_enqueued",
        "jobs",
        ["status", sa.text("enqueued_at DESC")],
    )
    op.create_index(
        "ix_jobs_user_enqueued",
        "jobs",
        ["user_id", sa.text("enqueued_at DESC")],
    )


def downgrade() -> None:
    """Drop the jobs table and its indexes."""
    op.drop_index("ix_jobs_user_enqueued", table_name="jobs")
    op.drop_index("ix_jobs_status_enqueued", table_name="jobs")
    op.drop_table("jobs")
```

### 4.11 Typical caller usage (after install)

```python
# app/api/routes/example.py
from fastapi import APIRouter
from app.workers.enqueue import enqueue

router = APIRouter()


@router.post("/reports/generate")
async def generate_report() -> dict:
    job_id = await enqueue(
        "send_email_task",
        to="user@example.com",
        subject="Your report is ready",
        body="...",
    )
    return {"job_id": job_id}  # client polls GET /jobs/{job_id}/status
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_arq_worker` pre-flight checks `"WorkerSettings" in app/workers/arq_worker.py` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero files** | `add_arq_worker` returns success+notes before any filesystem write when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | `_assert_parses` runs `ast.parse` on each created `.py` file; tool raises `SyntaxError` otherwise |
| QS-4 | **No generated function exceeds 50 LOC** | Every helper in `tasks.py`, `enqueue.py`, `arq_worker.py`, `crud/job.py`, `routes/jobs.py` kept small by construction; asserted by AST walk in test harness |
| QS-5 | **Redis DSN is never hard-coded** | `_write_worker_module` emits `RedisSettings.from_dsn(str(settings.REDIS_URL))` — always read from `settings` |
| QS-6 | **Task handlers must be `async def` accepting `ctx` first** | Documented in `tasks.py` module docstring; three example tasks all conform; `TASK_REGISTRY` referenced by `WorkerSettings.functions` |
| QS-7 | **arq pool is created once per process** | `_patch_main` inserts `app.state.arq_pool = await create_arq_pool()` **before** `yield` in the lifespan and `await close_arq_pool(...)` **after** `yield` |
| QS-8 | **HTTP companion routes require authentication** | Both `get_job_status` and `list_active_jobs` declare `current_user: CurrentUser` from `app.api.deps` |
| QS-9 | **Worker runs as non-root in its container** | `Dockerfile.worker` declares `USER 1000` before `CMD` |
| QS-10 | **`enqueue()` raises on rejection — never silently drops** | `enqueue` checks `if job is None: raise RuntimeError(...)` |
| QS-11 | **`ARQ_*` fields live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent so pydantic-settings binds env vars |
| QS-12 | **Alembic migration is chained to current head** | `_write_job_migration` calls `find_migration_head(versions_dir)` and emits `down_revision = "<head>"` |
| QS-13 | **`Job` model is tenant-aware when tenant model exists** | `_write_job_model` and `_write_job_migration` detect `app/models/tenant.py` and emit conditional FK to `tenants.id` |
| QS-14 | **`Job` model is registered in `app/models/__init__.py`** | `_patch_models_init` appends `from app.models.job import Job  # noqa: F401` idempotently |
| QS-15 | **`arq>=0.25.0` and `redis[hiredis]>=5.0.0` are added to requirements** | `_patch_requirements` appends only if tokens absent |
| QS-16 | **Prerequisites are validated before write** | `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` runs first |
| QS-17 | **Worker module provides a `python -m` CLI entry** | `arq_worker.py` defines `main()` + `if __name__ == "__main__": main()` invoking `arq.worker.run_worker` |
| QS-18 | **Tool records execution time** | `ToolResult.execution_time_ms` is computed via `_elapsed_ms(start)` on every return path |
| QS-19 | **Next-steps mention `alembic` and Redis** | `next_steps` list includes `"alembic upgrade head"` and `"Set REDIS_URL in .env ..."` |
| QS-20 | **Second run keeps the project parseable** | Idempotent no-op path does not corrupt any file; all `.py` remain AST-valid after two invocations |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_arq_worker.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 8 new files | `len(result.files_created) >= 8` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `ARQ_MAX_JOBS` and `ARQ_JOB_TIMEOUT` exist inside `class Settings` body with 4-space indent | String scan + indent check on line containing `ARQ_MAX_JOBS` | T-08 (`test_config_fields_patched`) |
| CC-09 | `Job` is registered in `app/models/__init__.py` | `"Job" in content` of `models/__init__.py` | T-09 (`test_models_init_patched`) |
| CC-10 | Jobs router is registered in `app/routes/__init__.py` when that file exists | `"job" in content.lower()` of `routes/__init__.py` | T-10 (`test_routes_registered`) |
| CC-11 | `app/workers/arq_worker.py` exists and contains `WorkerSettings` | File exists + `"WorkerSettings" in content` | T-11 (`test_worker_module_created`) |
| CC-12 | `app/workers/tasks.py` exists and contains `TASK_REGISTRY` + all three example tasks | File exists + substring checks for `TASK_REGISTRY`, `send_email_task`, `cleanup_task`, `webhook_retry_task` | T-12 (`test_tasks_module_created`) |
| CC-13 | `app/workers/enqueue.py` exists with `create_arq_pool` and `enqueue` symbols | File exists + substring checks | T-13 (`test_enqueue_module_created`) |
| CC-14 | `app/models/job.py` exists and declares `class Job` | File exists + `"class Job" in content` | T-14 (`test_job_model_created`) |
| CC-15 | `Dockerfile.worker` exists at project root and runs as non-root (`USER` directive) | File exists + `"USER" in content` | T-15 (`test_dockerfile_worker_created`) |
| CC-16 | `app/main.py` lifespan references `create_arq_pool` and `close_arq_pool` | Substring checks in `main.py` | T-16 (`test_lifespan_patched`) |
| CC-17 | `requirements.txt` contains `arq>=` pin | `"arq>=" in content` of `requirements.txt` | T-17 (`test_requirements_arq`) |
| CC-18 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` includes `alembic` and `redis` guidance | Lowercased join of `next_steps` contains both tokens | T-19 (`test_next_steps_mention_alembic_and_redis`) |
| CC-20 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-20 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_arq_worker.py`
- [ ] `add_arq_worker.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_arq_worker.py` detects `"WorkerSettings"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `WorkerSettings.redis_settings` derived from `settings.REDIS_URL` — never hard-coded
- [ ] `WorkerSettings.functions` points at `TASK_REGISTRY` containing `send_email_task`, `cleanup_task`, `webhook_retry_task`
- [ ] `Dockerfile.worker` declares `USER 1000` before `CMD`
- [ ] `_patch_main` inserts pool create/close around `yield` in lifespan
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so fields land inside `Settings` class body
- [ ] `_patch_models_init` idempotently appends `Job` import
- [ ] `_patch_requirements` adds `arq>=0.25.0` and `redis[hiredis]>=5.0.0` when absent
- [ ] `find_migration_head` is used to chain the migration to the current head
- [ ] `has_tenants` branch emits FK to `tenants.id` in both model and migration when `app/models/tenant.py` exists
- [ ] `get_job_status` and `list_active_jobs` both declare `current_user: CurrentUser` gate
- [ ] `enqueue()` raises `RuntimeError` on `None` return from `pool.enqueue_job`
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-ARQ-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"WorkerSettings" in worker_file.read_text()` short-circuits to `status="no_op"` | T-02, T-20 |
| INV-ARQ-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-ARQ-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: if .py: _assert_parses(p)` | T-06, T-20 |
| INV-ARQ-04 | Redis DSN MUST be read from `settings.REDIS_URL` — never invented | `_write_worker_module` and `_write_enqueue_module` emit `RedisSettings.from_dsn(str(settings.REDIS_URL))` | T-11, T-13 |
| INV-ARQ-05 | arq pool MUST be created exactly once per FastAPI process via lifespan | `_patch_main` inserts pool create before `yield` and close after — guarded by `"arq_pool" in src` idempotency check | T-16 |
| INV-ARQ-06 | HTTP companion routes MUST require authentication | `CurrentUser` is a required parameter on `get_job_status` and `list_active_jobs` | T-10 |
| INV-ARQ-07 | `Job` audit model MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends `from app.models.job import Job  # noqa: F401` idempotently | T-09 |
| INV-ARQ-08 | `ARQ_*` settings MUST live inside `class Settings` body (pydantic-settings binding) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-08 |
| INV-ARQ-09 | Worker process MUST run as non-root (`USER 1000`) | `_write_dockerfile_worker` emits `USER 1000` before `CMD` | T-15 |
| INV-ARQ-10 | Task registry MUST contain `send_email_task`, `cleanup_task`, `webhook_retry_task` | `_write_tasks_module` emits all three plus `TASK_REGISTRY` list | T-12 |
| INV-ARQ-11 | `enqueue()` MUST raise `RuntimeError` when arq refuses the job | `if job is None: raise RuntimeError(...)` | T-13 |
| INV-ARQ-12 | Alembic migration MUST be chained to the current head | `find_migration_head(versions_dir) or "0001_initial"` | T-05 |
| INV-ARQ-13 | `tenant_id` column MUST have FK to `tenants.id` iff `app/models/tenant.py` exists | `has_tenants = (app_dir / "models" / "tenant.py").exists()` branches model + migration | T-14 |
| INV-ARQ-14 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-18 |
| INV-ARQ-15 | `next_steps` MUST reference `alembic` and `redis` so operators know the post-install steps | Hard-coded strings in the `success` branch of `add_arq_worker` | T-19 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install arq into a clean FastAPI project**
- **As a** backend engineer who needs background jobs
- **I want** to run one tool call and get a worker kit
- **So that** I stop hand-rolling queue glue
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_arq_worker(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-ARQ-01)
  - `files_created` contains ≥ 8 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/workers/arq_worker.py` already contains `WorkerSettings`
- **When:** `add_arq_worker(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-ARQ-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-ARQ-03)
  - Verified by T-02, T-20

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_arq_worker(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-ARQ-02)
  - Verified by T-03

**US-04: Configure concurrency via tool arguments**
- **As a** platform engineer sizing the worker
- **I want** to pass `max_jobs`, `job_timeout_seconds`, `max_tries`, `keep_results_seconds`
- **So that** I can tune per-deployment
- **Given:** Product with strict per-job SLO
- **When:** `add_arq_worker(inp, max_jobs=20, job_timeout_seconds=60, max_tries=5, keep_results_seconds=3600)`
- **Then:**
  - `app/core/config.py` contains `ARQ_MAX_JOBS: int = 20` etc. inside `class Settings` (INV-ARQ-08)
  - `WorkerSettings` in `arq_worker.py` reads those via `settings.*`
  - Verified by T-08

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it
- **Given:** Tool just emitted `tasks.py`, `enqueue.py`, `crud/job.py`, `routes/jobs.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

### 9.2 Worker runtime & task registry (US-06 .. US-10)

**US-06: Start the worker from a Docker container**
- **As an** ops engineer
- **I want** a one-line container command
- **So that** I can scale workers with `kubectl scale`
- **Given:** `Dockerfile.worker` generated
- **When:** `docker build -f Dockerfile.worker -t worker . && docker run --env-file .env worker`
- **Then:**
  - Container runs `python -m app.workers.arq_worker` as `USER 1000` (INV-ARQ-09)
  - `main()` delegates to `arq.worker.run_worker(WorkerSettings)` (QS-17)
  - Verified by T-15

**US-07: Register a new task**
- **As a** developer adding a new async job
- **I want** to write an `async def` and append it to `TASK_REGISTRY`
- **So that** the worker picks it up on next restart
- **Given:** `app/workers/tasks.py` exists with `TASK_REGISTRY`
- **When:** I add `async def my_task(ctx, ...): ...` and append to the list
- **Then:**
  - `WorkerSettings.functions = TASK_REGISTRY` picks it up automatically (QS-6)
  - No worker file changes required
  - Verified by T-12

**US-08: Enqueue from an HTTP handler**
- **As an** API developer
- **I want** `from app.workers.enqueue import enqueue; job_id = await enqueue("send_email_task", ...)`
- **So that** a POST handler returns in milliseconds
- **Given:** arq pool on `app.state.arq_pool` via lifespan (INV-ARQ-05)
- **When:** Handler calls `await enqueue(...)`
- **Then:**
  - `get_pool()` returns singleton pool — no per-request allocation
  - `pool.enqueue_job(task_name, *args, **kwargs)` returns a `Job` object
  - `enqueue()` returns `job.job_id` string
  - Verified by T-13, T-16

**US-09: Defer a task to run later**
- **As a** developer building a reminder feature
- **I want** `await enqueue("send_email_task", ..., _defer_by=3600)`
- **So that** the email sends one hour from now
- **Given:** `enqueue()` accepts `_defer_by: int | None`
- **When:** Caller passes `_defer_by=3600`
- **Then:**
  - `kw["_defer_by"] = 3600` is forwarded to `pool.enqueue_job`
  - arq defers execution by 3600 s
  - Verified by T-13

**US-10: Detect enqueue rejection**
- **As a** caller of `enqueue()`
- **I want** an exception if arq refuses the job (queue full / duplicate id)
- **So that** I never silently lose work
- **Given:** `pool.enqueue_job` returns `None`
- **When:** `enqueue()` receives `job is None`
- **Then:**
  - Raises `RuntimeError("arq refused to enqueue task=... (queue full or duplicate job id)")` (INV-ARQ-11)
  - Verified by T-13

### 9.3 HTTP companion routes (US-11 .. US-15)

**US-11: Poll a job's status**
- **As a** frontend developer
- **I want** `GET /jobs/{job_id}/status`
- **So that** users see "running / success / failed"
- **Given:** A job is enqueued and `app.state.arq_pool` is initialised
- **When:** `GET /jobs/abc123/status` with a valid user token
- **Then:**
  - `_require_pool(request)` returns the pool or 503
  - `_fetch_job(job_id, pool)` returns `(status, info)` or 404
  - Response body is `{"job_id", "status", "result", "error"}`
  - Verified by T-10

**US-12: List currently-queued jobs**
- **As an** ops dashboard
- **I want** `GET /jobs/active`
- **So that** I see queue depth live
- **Given:** Multiple jobs pending in Redis
- **When:** `GET /jobs/active` with admin token
- **Then:**
  - Returns `{"data": [job_ids...], "count": n}`
  - Requires `CurrentUser` auth gate (INV-ARQ-06)
  - Verified by T-10

**US-13: 503 when pool is not initialised**
- **As a** resilient client
- **I want** a clear error when the app booted without Redis
- **So that** I do not get a mystery crash
- **Given:** `app.state.arq_pool` is `None`
- **When:** `GET /jobs/abc/status`
- **Then:**
  - `_require_pool` raises `HTTPException(503, "arq pool not initialised")`
  - Verified via `getattr(request.app.state, "arq_pool", None)` check

**US-14: 404 when job_id is unknown**
- **As a** client that polls too late
- **I want** a 404 not a 500
- **So that** my error handler is simple
- **Given:** `job_id` not present in Redis (TTL expired)
- **When:** `GET /jobs/expired/status`
- **Then:**
  - arq `Job(...)` raises on lookup; handler catches → 404 "job not found"
  - Verified in `_fetch_job` try/except

**US-15: Unauthenticated access is denied**
- **As a** security reviewer
- **I want** no anonymous job state probing
- **So that** job IDs are not an enumeration oracle
- **Given:** Routes declare `current_user: CurrentUser`
- **When:** Anonymous request hits `/jobs/{id}/status`
- **Then:**
  - FastAPI DI resolves `CurrentUser`, missing auth → 401
  - Verified by route signature (INV-ARQ-06)

### 9.4 Durable audit model (US-16 .. US-20)

**US-16: Record critical jobs in PostgreSQL**
- **As a** compliance officer
- **I want** a permanent row per payment job
- **So that** auditors can reconstruct history after Redis eviction
- **Given:** `app/crud/job.py` and `jobs` table
- **When:** Worker calls `record_job(session, task_name="charge", payload=..., user_id=...)`
- **Then:**
  - Row inserted with `status="queued"` and `enqueued_at=now()`
  - Returns the `Job` instance for caller to track
  - Verified by T-14

**US-17: Lifecycle transitions: queued → running → success|failed**
- **As a** worker runtime
- **I want** clean CRUD helpers for each transition
- **So that** I do not write ad-hoc SQL
- **Given:** `update_job_started`, `update_job_completed`, `update_job_failed`
- **When:** Worker wraps task execution in `update_job_started` → task → `update_job_completed`/`update_job_failed`
- **Then:**
  - `started_at` / `completed_at` stamped with `datetime.now(timezone.utc)`
  - `result` (success) or `error` (failure, truncated to 4000 chars) persisted
  - Verified by T-14

**US-18: List a user's recent jobs**
- **As a** UI that shows "your jobs"
- **I want** `list_user_jobs(session, user_id=..., limit=50)`
- **So that** I render a personal history
- **Given:** `ix_jobs_user_enqueued` index exists
- **When:** Query runs
- **Then:**
  - `SELECT ... FROM jobs WHERE user_id=? ORDER BY enqueued_at DESC LIMIT 50` — index-backed
  - Verified in `_write_job_crud` + migration

**US-19: Tenant-aware audit in multi-tenant deploys**
- **As a** platform with `app/models/tenant.py`
- **I want** `jobs.tenant_id` FK-referenced to `tenants.id`
- **So that** row-level isolation is enforced
- **Given:** `has_tenants == True`
- **When:** Tool emits `Job` model and migration
- **Then:**
  - `tenant_id Mapped[uuid.UUID | None]` with `ForeignKey("tenants.id", ondelete="CASCADE")`
  - Migration emits matching `sa.ForeignKey("tenants.id", ondelete="CASCADE")`
  - Verified by T-14 (INV-ARQ-13)

**US-20: Tenant-blind install when no tenant model exists**
- **As a** single-tenant app
- **I want** `tenant_id` as a nullable column without FK
- **So that** I can adopt multi-tenancy later without schema churn
- **Given:** `has_tenants == False`
- **When:** Tool emits `Job` model
- **Then:**
  - `tenant_id` column is plain `Uuid, nullable=True, index=True`
  - Migration emits `sa.Column("tenant_id", sa.Uuid(), nullable=True)`
  - Verified by T-14

### 9.5 Lifespan, config, and operator experience (US-21 .. US-25)

**US-21: Lifespan creates/closes the pool exactly once**
- **As a** FastAPI process
- **I want** `app.state.arq_pool` set before `yield` and closed after
- **So that** all requests share one pool
- **Given:** `_patch_main` inserted both calls
- **When:** Uvicorn boots the app
- **Then:**
  - Pool created exactly once; closed on graceful shutdown
  - Idempotency guard: `if "arq_pool" in src: return False`
  - Verified by T-16 (INV-ARQ-05)

**US-22: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `ARQ_MAX_JOBS=20` in `.env` to take effect
- **So that** I do not rebuild images for tuning
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `ARQ_MAX_JOBS` inside `class Settings` picks up env var (INV-ARQ-08)
  - Fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
  - Verified by T-08

**US-23: `requirements.txt` gets the new deps**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `arq>=0.25.0` and `redis[hiredis]>=5.0.0` to appear
- **So that** the worker module can import
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains `arq>=0.25.0` (idempotent: only appended if absent)
  - Contains `redis[hiredis]>=5.0.0`
  - Verified by T-17

**US-24: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include migration + Redis guidance
- **So that** I do not forget to `alembic upgrade head`
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `"alembic upgrade head"` and Redis guidance
  - Verified by T-19 (INV-ARQ-15)

**US-25: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **So that** the build does not blow the budget
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-ARQ-14)
  - Verified by T-18

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_arq_worker.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `arq_t01` | `add_arq_worker(ToolInput(project_dir))` | `result.status == "success"` (INV-ARQ-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `arq_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; `r2.files_created == []`; `r2.files_modified == []` (INV-ARQ-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `arq_t03`; snapshot all `.py` | `add_arq_worker(ToolInput(dry_run=True))` | `status == "success"`; empty create/modify lists; byte-identical filesystem (INV-ARQ-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `arq_t04` | Run tool | `len(files_created) >= 8`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `arq_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `arq_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-ARQ-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `arq_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `arq_t08`; run tool | Read `app/core/config.py` | Contains `ARQ_MAX_JOBS` and `ARQ_JOB_TIMEOUT`; `ARQ_MAX_JOBS` line starts with 4-space indent (INV-ARQ-08, CC-08) |
| T-09 | `test_models_init_patched` | Fixture `arq_t09`; run tool | Read `app/models/__init__.py` | Contains `"Job"` (INV-ARQ-07, CC-09) |
| T-10 | `test_routes_registered` | Fixture `arq_t10`; run tool | Read `app/routes/__init__.py` if it exists | Contains `"job"` (case-insensitive) (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_worker_module_created` | Fixture `arq_t11`; run tool | Read `app/workers/arq_worker.py` | File exists; contains `"WorkerSettings"` (INV-ARQ-04, CC-11) |
| T-12 | `test_tasks_module_created` | Fixture `arq_t12`; run tool | Read `app/workers/tasks.py` | Contains `TASK_REGISTRY`, `send_email_task`, `cleanup_task`, `webhook_retry_task` (INV-ARQ-10, CC-12) |
| T-13 | `test_enqueue_module_created` | Fixture `arq_t13`; run tool | Read `app/workers/enqueue.py` | Contains `create_arq_pool` and `enqueue` (INV-ARQ-04, INV-ARQ-11, CC-13) |
| T-14 | `test_job_model_created` | Fixture `arq_t14`; run tool | Read `app/models/job.py` | File exists; contains `"class Job"` (INV-ARQ-13, CC-14) |
| T-15 | `test_dockerfile_worker_created` | Fixture `arq_t15`; run tool | Read `Dockerfile.worker` | File exists; contains `"USER"` (INV-ARQ-09, CC-15) |
| T-16 | `test_lifespan_patched` | Fixture `arq_t16`; run tool | Read `app/main.py` | Contains `create_arq_pool` and `close_arq_pool` (INV-ARQ-05, CC-16) |
| T-17 | `test_requirements_arq` | Fixture `arq_t17`; run tool | Read `requirements.txt` | Contains `"arq>="` (CC-17) |

### 10.4 Category D — Meta (T-18 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `arq_t18`; run tool | Read `result.execution_time_ms` | `> 0` (INV-ARQ-14, CC-18) |
| T-19 | `test_next_steps_mention_alembic_and_redis` | Fixture `arq_t19`; run tool | Lowercase-join `result.next_steps` | Contains `"alembic"` and `"redis"` (INV-ARQ-15, CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `arq_t20`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-ARQ-01, INV-ARQ-03, CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_arq_worker.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_arq_worker.py
```

Target: 20/20 passed, 0 failed. The standalone runner prints `TOOL-022 add_arq_worker: 20 passed, 0 failed`.

---

## 11. Interaction Matrix

How `add_arq_worker` composes with other SKILL-001 tools. Order matters when the other tool needs to see the `jobs` table / `app.state.arq_pool` to function. Tool IDs below match `specs/` directory (`find specs -name 'TOOL-*'`).

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_long_running_task` (TOOL-020) | Yes | ✅ Compatible — `add_arq_worker` runs FIRST | TOOL-020's worker pipeline reuses the `app/workers/` package and `enqueue()` helper; TOOL-020 registers its own task types in `TASK_REGISTRY` |
| `add_email_templates` (TOOL-055) | No | ✅ Compatible | `send_email_task` in `TASK_REGISTRY` is the natural enqueue target for template-rendered emails; the arq worker invokes `send_email` from `app/email/service.py` |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Webhook handlers can enqueue long-running reconciliation via `enqueue("stripe_reconcile_task", event_id=...)` to keep the 200 OK fast |
| `add_outbox_pattern` (TOOL-023) | Yes | ✅ Compatible — outbox relay reads from `jobs` table OR enqueues via `enqueue()` | Outbox dispatcher can `await enqueue("webhook_retry_task", ...)`; avoids double-persistence by letting arq own the retry loop |
| `add_event_driven` (TOOL-046) | No | ✅ Compatible | Task state transitions can publish `task.queued` / `task.completed` events via the event bus in `update_job_*` CRUD wrappers |
| `add_webhook_sender` (TOOL-015) | Yes | ✅ Compatible — webhook sender runs AFTER | Failed outbound deliveries re-enqueue via `enqueue("webhook_retry_task", delivery_id=..., url=..., payload=..., signature=...)` |
| `add_webhook_receiver` (TOOL-016) | No | ✅ Compatible | Incoming webhook endpoints can enqueue heavy processing to arq and return 200 immediately to the remote sender |
| `add_cache_layer` (TOOL-021) | No | ✅ Compatible | Uses the same `settings.REDIS_URL`; separate logical Redis DB recommended for queue (`/1`) vs cache (`/0`) to avoid eviction collisions on queue data |
| `add_circuit_breaker` (TOOL-022) | No | ✅ Compatible | Tasks that call flaky third-party APIs should wrap calls in the breaker; failing tasks get retried by arq's built-in retry mechanism |
| `add_multi_tenancy` (TOOL-008) | Yes | ✅ Compatible — tenancy runs BEFORE | `has_tenants` detection keys on `app/models/tenant.py`; when tenancy is installed first, `Job` model + migration emit the FK automatically (INV-ARQ-13) |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC runs AFTER | RBAC adds `require("jobs:read")` to `get_job_status` / `list_active_jobs`; current version only enforces `CurrentUser` authentication |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | API keys are first-class `CurrentUser` identities; can submit jobs and poll status with the same key |
| `add_oauth2_provider` (TOOL-011) | No | ✅ Compatible | OAuth2 JWTs work via the same `CurrentUser` dependency; no changes required |
| `add_audit_log` (TOOL-005) | Yes | ⚠️ Caveat — audit runs AFTER | `update_job_*` CRUD wrappers should emit audit entries for lifecycle transitions; do NOT double-audit via an audit sqlalchemy event |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | `Job` audit rows should NOT use soft-delete — auditors need irrevocable history; exclude `Job` from soft-delete mixin |
| `add_data_export` (TOOL-006) | No | ⚠️ Caveat | Data exports MAY include `jobs` rows for compliance; DO NOT include the `payload` column unless PII scrubbing is in place |
| `add_search` (TOOL-004) | No | ⚠️ Caveat | Full-text search over `jobs.payload` (JSONB) is expensive; restrict to `task_name` and `status` columns |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | `list_user_jobs` and `GET /jobs/active` can be cursor-paginated by `enqueued_at DESC` |
| `add_mfa` (TOOL-013) | No | ✅ Compatible | MFA challenges do not affect background task execution once enqueued |
| `add_sse` (TOOL-014) | No | ✅ Compatible | SSE endpoint can push `task.completed` events to clients as an alternative to polling `GET /jobs/{id}/status` |
| `add_feature_flags` (TOOL-009) | No | ✅ Compatible | Worker can toggle task handlers via flags without a redeploy |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | The admin panel renders `Job` model views out of the box; add `ModelAdmin` for filtering by `status` / `task_name` |
| Rate-limit middleware (slowapi / generic ASGI) | No | ✅ Compatible | Rate-limit `POST /enqueue-triggering` handlers upstream of `enqueue()`; do not rate-limit `GET /jobs/*/status` (dashboards need frequent polls). SKILL-001 does not ship a dedicated rate-limit tool. |

**Conflicts:** None identified. `add_arq_worker` is the ARQ-based alternative to a hypothetical Celery-based worker tool; SKILL-001 ships neither Celery support nor a scheduled-task tool today.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py \
  app/main.py \
  requirements.txt

rm -rf \
  app/workers/ \
  app/models/job.py \
  app/schemas/job.py \
  app/crud/job.py \
  app/api/routes/jobs.py \
  alembic/versions/add_arq_worker.py \
  Dockerfile.worker
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # drops jobs table + its two indexes
```

The `downgrade()` function in `alembic/versions/add_arq_worker.py` runs:

```python
op.drop_index("ix_jobs_user_enqueued", table_name="jobs")
op.drop_index("ix_jobs_status_enqueued", table_name="jobs")
op.drop_table("jobs")
```

### 12.3 Data preservation rollback

**Critical for compliance.** If any row exists in `jobs` with compliance significance (payments, webhook receipts, etc.), archive before downgrade:

```sql
CREATE TABLE jobs_archive_<date> AS SELECT * FROM jobs;
-- or: COPY jobs TO '/backup/jobs_<date>.csv' WITH CSV HEADER;
```

Redis job state (`arq:*` keys) has TTL and will expire naturally within `keep_results_seconds`; no explicit Redis cleanup is required for rollback correctness.

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

Because `_assert_parses` runs **at the end** of the tool's success path, a mid-execution failure may leave partially-written files. The tool writes files one at a time; `git checkout HEAD --` on modified paths plus `rm` on newly-created paths restores the project.

### 12.5 Emergency: Redis outage

1. Stop all arq workers: `docker ps | grep worker | awk '{print $1}' | xargs docker stop` (or `pkill -f 'app.workers.arq_worker'` on bare metal).
2. Disable the jobs router if it's preventing API boot: `mv app/api/routes/jobs.py app/api/routes/jobs.py.disabled` and comment out `include_router(jobs_router)` in `app/routes/__init__.py`.
3. Disable the lifespan pool hook: comment out `app.state.arq_pool = await create_arq_pool()` and `await close_arq_pool(app.state.arq_pool)` in `app/main.py`.
4. Restart the FastAPI app; the API tier continues serving synchronous traffic while Redis is restored.
5. On Redis restore, revert the three disable steps and restart both tiers.

### 12.6 Uninstall validator

After rollback, verify:

```bash
test ! -d app/workers || (echo "app/workers still present" && exit 1)
test ! -f app/models/job.py || (echo "Job model still present" && exit 1)
test ! -f Dockerfile.worker || (echo "Dockerfile.worker still present" && exit 1)
grep -q "ARQ_MAX_JOBS" app/core/config.py && echo "config still patched" && exit 1
grep -q "arq_pool" app/main.py && echo "main.py still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing a prerequisite (`CONFIG_SETTINGS`, etc.) | `ensure_prerequisites` returns errors → tool returns `status="error"` with list of missing prereqs and hint to run `fastapi_generate_project` first |
| EC-03 | Tool runs on a project with `app/workers/arq_worker.py` already containing `WorkerSettings` | Early return `status="no_op"` with single note `"WorkerSettings already present — arq worker is already installed, skipped."` — zero file writes |
| EC-04 | Tool runs with `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-ARQ-02) |
| EC-05 | `app/models/tenant.py` exists → `has_tenants = True` | `Job` model emits `tenant_id` with `ForeignKey("tenants.id", ondelete="CASCADE")`; migration emits matching FK column |
| EC-06 | `app/models/tenant.py` absent → `has_tenants = False` | `Job` model emits plain nullable `tenant_id` Uuid column (no FK); migration omits FK |
| EC-07 | `alembic/versions/` missing | Migration file step is SKIPPED silently (condition `if versions_dir.exists():`); other file writes proceed normally |
| EC-08 | `app/core/config.py` already contains `ARQ_MAX_JOBS` | `_patch_config` early-returns (`"ARQ_MAX_JOBS" in src` check); no duplicate block appended |
| EC-09 | `app/core/config.py` lacks the `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | `_patch_config` falls back to inserting before `settings = Settings()`; if that also missing, appends at EOF (still valid Python, fields land at module scope with warning) |
| EC-10 | `app/main.py` already contains `arq_pool` | `_patch_main` returns `False`; `files_modified` does NOT include `main.py`; idempotency preserved |
| EC-11 | `app/main.py` has no `from app.` import line | `_patch_main` returns `False` (cannot safely locate insertion point); caller must wire the pool manually — note emitted in `next_steps` |
| EC-12 | `app/main.py` has no `yield` in lifespan | `_patch_main` only inserts the import; pool create/close insertion silently skipped; caller must wire the lifespan manually |
| EC-13 | `requirements.txt` already contains `arq` or `redis` | `_patch_requirements` only appends missing tokens; order preserved; trailing newline handled |
| EC-14 | `app/models/__init__.py` already imports `Job` | `_patch_models_init` early-returns after `marker in content` check — no duplicate import line |
| EC-15 | `app/routes/__init__.py` already contains the jobs router import | `_register_router_in_routes_init` early-returns; no duplicate `include_router` call |
| EC-16 | Generated `arq_worker.py` fails `ast.parse` | `_assert_parses` raises `SyntaxError`; caller sees traceback; partial files remain on disk (use rollback 12.4) |
| EC-17 | `find_migration_head` returns `None` | `_write_job_migration` falls back to `"0001_initial"` so migration still wires to a plausible parent |
| EC-18 | `app/api/routes/` directory missing | `_write_jobs_http_routes` creates the directory via `mkdir(parents=True, exist_ok=True)` |
| EC-19 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `job.py` |
| EC-20 | `app/crud/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `job.py` |
| EC-21 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-20 verifies) |
| EC-22 | Very small fixture project (no `app/routes/__init__.py`) | Tool still succeeds; `routes_init` patch step is conditional on file existence; router must be registered manually — note emitted |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 20 Completeness Criteria verified via `test_add_arq_worker.py` passing
2. ✅ `test_add_arq_worker.py` reports `20 passed, 0 failed` via both pytest and standalone runner
3. ✅ Tool execution time < 5 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-ARQ-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-ARQ-02)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-ARQ-03)
7. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
8. ✅ `ARQ_*` settings live inside `class Settings` body with 4-space indentation (INV-ARQ-08)
9. ✅ `WorkerSettings.redis_settings` derived from `settings.REDIS_URL` — no hard-coded host (INV-ARQ-04)
10. ✅ `app/main.py` lifespan creates and closes the pool via `create_arq_pool` / `close_arq_pool` (INV-ARQ-05)
11. ✅ Both HTTP companion routes declare `current_user: CurrentUser` (INV-ARQ-06)
12. ✅ `Dockerfile.worker` runs as non-root `USER 1000` with `CMD ["python", "-m", "app.workers.arq_worker"]` (INV-ARQ-09)
13. ✅ `TASK_REGISTRY` contains `send_email_task`, `cleanup_task`, `webhook_retry_task` (INV-ARQ-10)
14. ✅ `enqueue()` raises `RuntimeError` when `pool.enqueue_job` returns `None` (INV-ARQ-11)
15. ✅ `next_steps` includes `alembic upgrade head` and Redis guidance (INV-ARQ-15)
16. ✅ Developer successfully enqueues `send_email_task` from a handler, polls `GET /jobs/{id}/status`, sees `success`, and retrieves the result

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` passes
- [ ] `app/workers/arq_worker.py` does NOT contain `"WorkerSettings"` (otherwise → `no_op`)
- [ ] Detect `has_tenants = (app_dir / "models" / "tenant.py").exists()`
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Workers package

- [ ] `mkdir -p app/workers`
- [ ] Write `app/workers/__init__.py` with docstring if missing
- [ ] Write `app/workers/tasks.py` via `_write_tasks_module` (startup, shutdown, 3 example tasks, `TASK_REGISTRY`)
- [ ] Write `app/workers/arq_worker.py` via `_write_worker_module` (`WorkerSettings`, `main()`, `__main__` guard)
- [ ] Write `app/workers/enqueue.py` via `_write_enqueue_module` (`create_arq_pool`, `close_arq_pool`, `get_pool`, `enqueue`)

### 15.3 `Job` audit model

- [ ] Write `app/models/job.py` via `_write_job_model(has_tenants=has_tenants)`
- [ ] Use `JSONB` for `payload` and `result`
- [ ] Add `ix_jobs_status_enqueued` and `ix_jobs_user_enqueued` via `__table_args__`
- [ ] Conditional tenant FK branch (model + migration must agree)
- [ ] `_patch_models_init` appends `from app.models.job import Job  # noqa: F401`

### 15.4 Schemas

- [ ] Write `app/schemas/job.py` with `JobStatus` enum, `JobPublic`, `JobListResponse`
- [ ] `JobPublic` uses `ConfigDict(from_attributes=True)` for SQLAlchemy → Pydantic coercion
- [ ] All timestamp fields typed as `datetime | None`

### 15.5 CRUD

- [ ] Write `app/crud/job.py` with `record_job`, `update_job_started`, `update_job_completed`, `update_job_failed`, `list_user_jobs`, `_get`
- [ ] All helpers are `async def` accepting `AsyncSession`
- [ ] `update_job_failed` truncates error to 4000 chars
- [ ] `list_user_jobs` uses `ORDER BY enqueued_at DESC LIMIT n`

### 15.6 HTTP companion routes

- [ ] Write `app/api/routes/jobs.py` with `APIRouter(prefix="/jobs", tags=["jobs"])`
- [ ] `_require_pool(request)` returns 503 if `app.state.arq_pool` missing
- [ ] `_fetch_job(job_id, pool)` returns `(status, info)` or 404
- [ ] `_extract_outcome(info)` normalises `(result, error)`
- [ ] `GET /{job_id}/status` requires `CurrentUser`
- [ ] `GET /active` requires `CurrentUser`

### 15.7 Alembic migration

- [ ] `find_migration_head(versions_dir) or "0001_initial"` resolves down_revision
- [ ] Create `jobs` table with all columns
- [ ] Tenant column conditional on `has_tenants`
- [ ] Two `DESC` indexes on `(status, enqueued_at)` and `(user_id, enqueued_at)`
- [ ] `downgrade()` drops indexes first, then table

### 15.8 Dockerfile.worker

- [ ] `FROM python:3.12-slim`
- [ ] `PYTHONUNBUFFERED=1` + `PYTHONDONTWRITEBYTECODE=1`
- [ ] `COPY requirements.txt` then `pip install --no-cache-dir -r requirements.txt`
- [ ] `COPY app/ ./app/`
- [ ] `USER 1000`
- [ ] `CMD ["python", "-m", "app.workers.arq_worker"]`

### 15.9 Config patch

- [ ] Early-return if `"ARQ_MAX_JOBS" in src`
- [ ] Block emits `ARQ_MAX_JOBS`, `ARQ_JOB_TIMEOUT_SECONDS`, `ARQ_MAX_TRIES`, `ARQ_KEEP_RESULTS_SECONDS`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.10 Routes init patch

- [ ] Early-return if import line already present
- [ ] Insert `from app.api.routes.jobs import router as jobs_router` after last `from app.` import
- [ ] Insert `api_router.include_router(jobs_router)` after last `include_router` call
- [ ] Preserve trailing newline

### 15.11 Main patch (lifespan)

- [ ] Early-return if `"arq_pool" in src`
- [ ] Insert import: `from app.workers.enqueue import close_arq_pool, create_arq_pool`
- [ ] Before `yield`: `app.state.arq_pool = await create_arq_pool()`
- [ ] After `yield`: `await close_arq_pool(app.state.arq_pool)`
- [ ] Preserve indentation via `lines[yield_idx]` prefix extraction
- [ ] Return `True` on success, `False` on no-op

### 15.12 Requirements patch

- [ ] Add `arq>=0.25.0` if `"arq"` absent
- [ ] Add `redis[hiredis]>=5.0.0` if `"redis"` absent
- [ ] Preserve trailing newline

### 15.13 Validation

- [ ] Loop over `files_created`; for every `.py` call `_assert_parses(p)`
- [ ] `_assert_parses` raises `SyntaxError` with file path on failure

### 15.14 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain `max_jobs`, `job_timeout`, `max_tries`, `keep_result`, HTTP routes, pool lifespan, Dockerfile non-root
- [ ] `next_steps` contains `"alembic upgrade head"`, Redis guidance, worker start command, restart hint, verification hint

### 15.15 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists all emitted files and the "why arq" rationale
- [ ] `add_arq_worker` docstring documents all four keyword parameters

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/workers/__init__.py",
    "/tmp/fixture/app/workers/tasks.py",
    "/tmp/fixture/app/workers/arq_worker.py",
    "/tmp/fixture/app/workers/enqueue.py",
    "/tmp/fixture/app/models/job.py",
    "/tmp/fixture/app/schemas/job.py",
    "/tmp/fixture/app/crud/job.py",
    "/tmp/fixture/app/api/routes/jobs.py",
    "/tmp/fixture/alembic/versions/add_arq_worker.py",
    "/tmp/fixture/Dockerfile.worker"
  ],
  "files_modified": [
    "/tmp/fixture/app/models/__init__.py",
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/routes/__init__.py",
    "/tmp/fixture/app/main.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "arq worker added: WorkerSettings runtime, task registry, enqueue helpers,",
    "Job audit model + schemas + CRUD + Alembic migration (tenant-aware).",
    "max_jobs=10, job_timeout=300s, max_tries=3, keep_result=86400s.",
    "HTTP companion routes: GET /jobs/{job_id}/status, GET /jobs/active.",
    "arq pool is created in FastAPI lifespan on app.state.arq_pool — multi-worker safe.",
    "Dockerfile.worker generated for running the worker as a separate process (runs as non-root USER 1000)."
  ],
  "next_steps": [
    "alembic upgrade head",
    "Set REDIS_URL in .env — the worker and enqueue helpers require Redis.",
    "Start the worker: docker build -f Dockerfile.worker -t myapp-worker . && docker run --rm --env-file .env myapp-worker",
    "Or locally: python -m app.workers.arq_worker",
    "Restart the FastAPI app so the /jobs/* routes and pool lifespan are active.",
    "Verify: POST an enqueue-triggering endpoint, then GET /jobs/<job_id>/status."
  ],
  "execution_time_ms": 142
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "WorkerSettings already present — arq worker is already installed, skipped."
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
    "[dry_run] Would create app/workers/ package (arq_worker.py, tasks.py, enqueue.py),",
    "         GET /jobs/{job_id}/status + GET /jobs/active HTTP routes,",
    "         Job model + schemas + CRUD + Alembic migration (tenant-aware), Dockerfile.worker.",
    "         max_jobs=10, job_timeout_seconds=300, max_tries=3, keep_results_seconds=86400.",
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
  "error": "Prerequisites not met:\n  - CONFIG_SETTINGS: app/core/config.py missing\n  - REQUIREMENTS_TXT: requirements.txt missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 2
}
```

---
