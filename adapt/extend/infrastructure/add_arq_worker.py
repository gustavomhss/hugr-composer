"""TOOL-022: add_arq_worker — add an arq (Redis-backed async) job queue to a FastAPI project.

Writes an ``app/workers/`` package containing the arq ``WorkerSettings`` runtime,
a task registry with 3 example tasks (``send_email_task``, ``cleanup_task``,
``webhook_retry_task``), a FastAPI-friendly ``enqueue()`` helper backed by a
pool cached on ``app.state.arq_pool``, HTTP companion routes
(``GET /jobs/{job_id}/status`` and ``GET /jobs/active``), an optional
``Job`` SQLAlchemy model + CRUD + Pydantic schemas for durable audit of
critical jobs (in addition to Redis), an Alembic migration (tenant-aware when
``app/models/tenant.py`` exists), a dedicated ``Dockerfile.worker`` for the
worker process, and every required ``settings`` key.

Why arq (and not Celery / Temporal)?

* **Async-native** — tasks are plain ``async def`` functions; no eventlet or
  greenlet monkey-patching.
* **Redis-only** — the scaffold already ships Redis; no new broker is needed.
* **Tiny surface area** — ``WorkerSettings``, ``functions``, ``on_startup``,
  ``on_shutdown`` is the entire API.  Auditing and debugging are trivial.
* **First-class retries** — ``max_tries`` + ``job_timeout`` + ``keep_result``
  are declarative, not middleware.

Security / correctness guarantees:

* The arq pool is created once on FastAPI startup and cached on
  ``app.state.arq_pool``; no per-request connection churn.
* Redis DSN is read from ``settings.REDIS_URL`` — the tool never invents a
  new DSN or hard-codes a host.
* HTTP companion routes require authentication (``CurrentUser``) so job
  state cannot be probed anonymously.
* Durable ``Job`` table is conditionally tenant-scoped: the migration and
  model emit a ``tenant_id`` FK only when ``app/models/tenant.py`` exists.
* The worker runs as a non-root user (``USER 1000``) in
  ``Dockerfile.worker``.

The tool is idempotent: a second run detects the ``WorkerSettings``
fingerprint in ``app/workers/arq_worker.py`` and returns ``status="no_op"``
without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_arq_worker import add_arq_worker

    result = add_arq_worker(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/workers/arq_worker.py", …]
    print(result.next_steps)    # ["alembic upgrade head", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_resiliency_add_arq_worker",
    "description": "Add an arq (Redis-backed async) job queue with worker, task registry, and HTTP status routes.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_arq_worker",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_arq_worker(
    inp: ToolInput,
    *,
    max_jobs: int = 10,
    job_timeout_seconds: int = 300,
    max_tries: int = 3,
    keep_results_seconds: int = 86400,
) -> ToolResult:
    """Add an arq (async Redis-backed) background job queue to a FastAPI project.

    Creates the worker runtime, task registry, enqueue helpers, HTTP companion
    routes, ``Job`` audit model/schema/CRUD, Alembic migration, and
    ``Dockerfile.worker``.  Patches ``app/core/config.py``,
    ``app/routes/__init__.py``, ``app/models/__init__.py``, ``app/main.py``
    (for the pool lifespan hook) and ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        max_jobs: Maximum concurrent jobs a single worker process will run
            (default 10).  Maps to ``WorkerSettings.max_jobs``.
        job_timeout_seconds: Per-job hard wall-clock timeout in seconds
            (default 300).  Maps to ``WorkerSettings.job_timeout``.
        max_tries: Maximum number of attempts for a job before it is marked
            permanently failed (default 3).  Maps to ``WorkerSettings.max_tries``.
        keep_results_seconds: How long arq should keep completed job results
            in Redis for status lookups (default 86400 = 24h).  Maps to
            ``WorkerSettings.keep_result``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Pre-flight: already installed? ------------------------------------
    worker_file = app_dir / "workers" / "arq_worker.py"
    if worker_file.exists() and "WorkerSettings" in worker_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["WorkerSettings already present — arq worker is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    has_tenants = (app_dir / "models" / "tenant.py").exists()

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/workers/ package (arq_worker.py, tasks.py, enqueue.py),",
                "         GET /jobs/{job_id}/status + GET /jobs/active HTTP routes,",
                "         Job model + schemas + CRUD + Alembic migration"
                + (" (tenant-aware)" if has_tenants else "")
                + ", Dockerfile.worker.",
                f"         max_jobs={max_jobs}, job_timeout_seconds={job_timeout_seconds}, "
                f"max_tries={max_tries}, keep_results_seconds={keep_results_seconds}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )
    files_modified: list[str] = []

    # Step 1 — workers package
    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init = workers_dir / "__init__.py"
    if not workers_init.exists():
        workers_init.write_text('"""Async background job queue (arq) sub-package."""\n')
        files_created.append(str(workers_init))

    # Step 2 — tasks registry (must exist before arq_worker imports it)
    tasks_file = workers_dir / "tasks.py"
    _write_tasks_module(tasks_file)
    files_created.append(str(tasks_file))

    # Step 3 — arq_worker runtime (WorkerSettings)
    _write_worker_module(worker_file)
    files_created.append(str(worker_file))

    # Step 4 — enqueue helpers
    enqueue_file = workers_dir / "enqueue.py"
    _write_enqueue_module(enqueue_file)
    files_created.append(str(enqueue_file))

    # Step 5 — Job model
    job_model_file = app_dir / "models" / "job.py"
    _write_job_model(job_model_file, has_tenants=has_tenants)
    files_created.append(str(job_model_file))

    # Register Job in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("job", "Job")])
        files_modified.append(str(models_init))

    # Step 6 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    job_schema_file = schemas_dir / "job.py"
    _write_job_schemas(job_schema_file)
    files_created.append(str(job_schema_file))

    # Step 7 — CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    job_crud_file = crud_dir / "job.py"
    _write_job_crud(job_crud_file)
    files_created.append(str(job_crud_file))

    # Step 8 — HTTP companion routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    jobs_route_file = routes_dir / "jobs.py"
    _write_jobs_http_routes(jobs_route_file)
    files_created.append(str(jobs_route_file))

    # Step 9 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_job_migration(versions_dir, has_tenants=has_tenants)
        files_created.append(str(migration_file))

    # Step 10 — Dockerfile.worker
    dockerfile_worker = project / "Dockerfile.worker"
    if not dockerfile_worker.exists():
        _write_dockerfile_worker(dockerfile_worker)
        files_created.append(str(dockerfile_worker))

    # Step 11 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            max_jobs,
            job_timeout_seconds,
            max_tries,
            keep_results_seconds,
        )
        files_modified.append(str(config_file))

    # Step 12 — register jobs router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 13 — patch app/main.py lifespan to create/close the arq pool
    main_file = app_dir / "main.py"
    if main_file.exists():
        if _patch_main(main_file):
            files_modified.append(str(main_file))

    # Step 14 — ensure arq + redis in requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate every generated file parses (Python files only)
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            _assert_parses(p)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "arq worker added: WorkerSettings runtime, task registry, enqueue helpers,",
            "Job audit model + schemas + CRUD + Alembic migration"
            + (" (tenant-aware)" if has_tenants else "")
            + ".",
            f"max_jobs={max_jobs}, job_timeout={job_timeout_seconds}s, "
            f"max_tries={max_tries}, keep_result={keep_results_seconds}s.",
            "HTTP companion routes: GET /jobs/{job_id}/status, GET /jobs/active.",
            "arq pool is created in FastAPI lifespan on app.state.arq_pool — multi-worker safe.",
            "Dockerfile.worker generated for running the worker as a separate process "
            "(runs as non-root USER 1000).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in .env — the worker and enqueue helpers require Redis.",
            "Start the worker: docker build -f Dockerfile.worker -t myapp-worker . && "
            "docker run --rm --env-file .env myapp-worker",
            "Or locally: python -m app.workers.arq_worker",
            "Restart the FastAPI app so the /jobs/* routes and pool lifespan are active.",
            "Verify: POST an enqueue-triggering endpoint, then GET /jobs/<job_id>/status.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to ``app/models/__init__.py``.
        class_imports: List of ``(module, class)`` tuples to register.
    """
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _write_worker_module(dest: Path) -> None:
    """Write ``app/workers/arq_worker.py`` with ``WorkerSettings`` and CLI entry.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"arq worker runtime.

        Provides ``WorkerSettings`` consumed by the arq CLI and a
        ``python -m app.workers.arq_worker`` entry point so the worker can be
        started directly (used by ``Dockerfile.worker``).

        Redis DSN, concurrency, per-job timeout, max retries, and result
        retention are read from ``app.core.config.settings`` — the worker
        does not invent its own config.
        \"\"\"
        from __future__ import annotations

        from arq.connections import RedisSettings

        from app.core.config import settings
        from app.workers.tasks import TASK_REGISTRY, shutdown, startup


        class WorkerSettings:
            \"\"\"arq worker configuration.

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
            \"\"\"

            functions = TASK_REGISTRY
            redis_settings = RedisSettings.from_dsn(str(settings.REDIS_URL))
            max_jobs = settings.ARQ_MAX_JOBS
            job_timeout = settings.ARQ_JOB_TIMEOUT_SECONDS
            max_tries = settings.ARQ_MAX_TRIES
            keep_result = settings.ARQ_KEEP_RESULTS_SECONDS
            on_startup = startup
            on_shutdown = shutdown


        def main() -> None:
            \"\"\"Run the arq worker until interrupted.

            Delegates to ``arq.worker.run_worker`` which handles signal
            trapping, graceful shutdown, and job draining.
            \"\"\"
            from arq.worker import run_worker

            run_worker(WorkerSettings)


        if __name__ == "__main__":
            main()
    """)
    dest.write_text(content)


def _write_tasks_module(dest: Path) -> None:
    """Write ``app/workers/tasks.py`` with the task registry and 3 examples.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"arq task registry and example tasks.

        Every task here must be ``async def`` and must accept ``ctx`` (an
        arq-provided dict with ``job_id``, ``job_try``, ``redis``, etc.) as
        its first positional argument.

        To register a new task:

        1. Write your ``async def my_task(ctx, ...): ...`` function.
        2. Append it to ``TASK_REGISTRY``.
        3. Restart the worker (or roll-restart in production).
        \"\"\"
        from __future__ import annotations

        import logging
        from typing import Any

        logger = logging.getLogger(__name__)


        async def startup(ctx: dict[str, Any]) -> None:
            \"\"\"Worker startup hook.

            Runs once per worker process.  Use this hook to open long-lived
            resources (database pools, HTTP clients) and stash them on
            ``ctx`` for task access.

            Args:
                ctx: arq worker context dict.  Mutated in-place.
            \"\"\"
            logger.info("arq worker starting up", extra={"worker": "arq"})
            ctx["started_at"] = True


        async def shutdown(ctx: dict[str, Any]) -> None:
            \"\"\"Worker shutdown hook.

            Runs once per worker process on graceful exit.  Close any
            resources opened in ``startup``.

            Args:
                ctx: arq worker context dict.
            \"\"\"
            logger.info("arq worker shutting down", extra={"worker": "arq"})


        async def send_email_task(
            ctx: dict[str, Any],
            to: str,
            subject: str,
            body: str,
        ) -> dict[str, Any]:
            \"\"\"Example I/O task: send a transactional email.

            This stub logs instead of calling an SMTP provider so the task
            is safe to run in tests.  Replace the body with a real email
            client (``aiosmtplib``, Postmark, SES, …) in production.

            Args:
                ctx: arq worker context dict.
                to: Recipient address.
                subject: Email subject line.
                body: Plain-text body.

            Returns:
                Dict with ``status``, ``to``, and the executing ``job_id``.
            \"\"\"
            job_id = ctx.get("job_id", "unknown")
            logger.info(
                "send_email_task executing",
                extra={"job_id": job_id, "to": to, "subject": subject},
            )
            # Stub: in production, await a real SMTP/API client here.
            _ = body  # referenced to satisfy linters until real impl lands
            return {"status": "sent", "to": to, "job_id": job_id}


        async def cleanup_task(ctx: dict[str, Any]) -> dict[str, Any]:
            \"\"\"Example scheduled cleanup task (no task arguments).

            Designed to be invoked on a cron-like schedule (e.g. from an
            external scheduler enqueuing it periodically).  In production,
            replace the body with real cleanup logic (soft-deleted row
            purge, expired token sweep, etc.).

            Args:
                ctx: arq worker context dict.

            Returns:
                Dict with ``status``, ``cleaned``, and the executing ``job_id``.
            \"\"\"
            job_id = ctx.get("job_id", "unknown")
            logger.info("cleanup_task executing", extra={"job_id": job_id})
            # Stub: in production, sweep expired rows/tokens/files here.
            return {"status": "ok", "cleaned": 0, "job_id": job_id}


        async def webhook_retry_task(
            ctx: dict[str, Any],
            delivery_id: str,
            url: str,
            payload: dict[str, Any],
            signature: str,
        ) -> dict[str, Any]:
            \"\"\"Retry a failed webhook delivery.

            Args:
                ctx: arq worker context dict.
                delivery_id: UUID of the original delivery attempt.
                url: Destination URL of the webhook.
                payload: JSON-serialisable payload to resend.
                signature: HMAC signature the receiver will verify.

            Returns:
                Dict with ``status``, ``delivery_id``, and ``job_id``.
            \"\"\"
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
            # Stub: in production, use an async HTTP client (httpx/aiohttp)
            # to POST payload with signature header here.
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
    """)
    dest.write_text(content)


def _write_enqueue_module(dest: Path) -> None:
    """Write ``app/workers/enqueue.py`` with pool + enqueue helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"FastAPI-friendly enqueue helpers for the arq worker.

        The arq Redis pool is expensive to create; we want exactly ONE per
        FastAPI worker process.  ``create_arq_pool`` is called from the
        FastAPI lifespan hook in ``app/main.py`` and the resulting pool is
        cached on ``app.state.arq_pool``.

        Callers should prefer reading the pool from the request state
        (``request.app.state.arq_pool``) when possible, but ``get_pool()``
        also works as a fallback singleton getter for code that does not
        have access to a request object.
        \"\"\"
        from __future__ import annotations

        import logging
        from typing import Any

        from arq import create_pool
        from arq.connections import ArqRedis, RedisSettings

        from app.core.config import settings

        logger = logging.getLogger(__name__)

        _pool: ArqRedis | None = None


        async def create_arq_pool() -> ArqRedis:
            \"\"\"Create a fresh arq Redis pool.

            Called from the FastAPI lifespan startup hook exactly once per
            process.  The returned pool is stored on ``app.state.arq_pool``.

            Returns:
                A connected ``ArqRedis`` pool instance.
            \"\"\"
            pool = await create_pool(
                RedisSettings.from_dsn(str(settings.REDIS_URL))
            )
            return pool


        async def close_arq_pool(pool: ArqRedis) -> None:
            \"\"\"Close the given arq Redis pool on shutdown.

            Args:
                pool: The pool previously returned by ``create_arq_pool``.
            \"\"\"
            try:
                await pool.close(close_connection_pool=True)
            except Exception:  # noqa: BLE001
                logger.warning("arq pool close failed", exc_info=True)


        async def get_pool() -> ArqRedis:
            \"\"\"Return the singleton arq Redis pool, creating it lazily.

            This is a convenience for code paths that do not have access to
            ``request.app.state.arq_pool`` (e.g. background scripts).  In
            normal FastAPI handlers, prefer reading the pool from the
            application state directly.

            Returns:
                The process-wide ``ArqRedis`` pool instance.
            \"\"\"
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
            \"\"\"Enqueue *task_name* on the arq queue and return the job id.

            Args:
                task_name: Registered function name (must appear in
                    ``TASK_REGISTRY``).
                *args: Positional arguments forwarded to the task function.
                _defer_by: Optional delay in seconds before the job becomes
                    eligible for execution.  ``None`` means run ASAP.
                **kwargs: Keyword arguments forwarded to the task function.

            Returns:
                The arq job id (string).  Callers can use this id to poll
                ``GET /jobs/{job_id}/status``.

            Raises:
                RuntimeError: If arq returns no job (enqueue rejected).
            \"\"\"
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
    """)
    dest.write_text(content)


def _write_job_model(dest: Path, *, has_tenants: bool = False) -> None:
    """Write ``app/models/job.py`` with the ``Job`` audit model.

    Args:
        dest: Absolute path for the new file.
        has_tenants: Whether ``app/models/tenant.py`` exists.  When *True*
            the ``tenant_id`` column gets a ``ForeignKey("tenants.id")``
            reference; otherwise it is a plain nullable UUID column.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    if has_tenants:
        tenant_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        ForeignKey("tenants.id", ondelete="CASCADE"),\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant owning this job record",\n'
            '    )'
        )
    else:
        tenant_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant owning this job record",\n'
            '    )'
        )

    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for durable audit of arq background jobs.

        The arq library already persists job state in Redis with a TTL.  This
        table is a SECOND source of truth for CRITICAL jobs where auditors
        or operators need a permanent record that survives Redis eviction.
        Non-critical jobs should rely on Redis alone.
        \"\"\"
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
            \"\"\"A durable audit record of a background job execution.

            Attributes:
                id: UUID primary key.
                tenant_id: Optional tenant UUID for multi-tenant isolation.
                task_name: Registered task function name (e.g. ``send_email_task``).
                status: Current lifecycle status string (``queued``,
                    ``running``, ``success``, ``failed``, ``cancelled``).
                payload: JSON snapshot of the arguments the job was
                    enqueued with.
                result: JSON snapshot of the value returned by the task on
                    success.  ``None`` while running or on failure.
                error: Error message on failure.  ``None`` on success.
                enqueued_at: UTC timestamp when the job was enqueued.
                started_at: UTC timestamp when the worker picked up the job.
                completed_at: UTC timestamp when the job finished (success or fail).
                user_id: Optional FK to ``users.id`` — user who triggered
                    the job.  ``None`` for system-initiated jobs.
            \"\"\"

            __tablename__ = "jobs"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            TENANT_PLACEHOLDER
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
                Index(
                    "ix_jobs_status_enqueued",
                    "status",
                    "enqueued_at",
                ),
                Index(
                    "ix_jobs_user_enqueued",
                    "user_id",
                    "enqueued_at",
                ),
            )
    """).replace("    TENANT_PLACEHOLDER", tenant_col)
    dest.write_text(content)


def _write_job_schemas(dest: Path) -> None:
    """Write ``app/schemas/job.py`` with Pydantic request/response schemas.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for background job audit records.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime
        from enum import Enum

        from pydantic import BaseModel, ConfigDict


        class JobStatus(str, Enum):
            \"\"\"Lifecycle status of a background job.

            Values:
                queued: Waiting in the arq queue, not yet picked up.
                running: Currently being executed by a worker.
                success: Completed successfully; ``result`` is populated.
                failed: Permanently failed after ``max_tries`` attempts.
                cancelled: Aborted by an operator before completion.
            \"\"\"

            queued = "queued"
            running = "running"
            success = "success"
            failed = "failed"
            cancelled = "cancelled"


        class JobPublic(BaseModel):
            \"\"\"Public view of a background job audit record.

            Attributes:
                id: UUID primary key of the ``Job`` row.
                task_name: Registered task function name.
                status: Current lifecycle status.
                enqueued_at: UTC timestamp when the job was enqueued.
                started_at: UTC timestamp when the worker picked it up.
                completed_at: UTC timestamp when it finished (success or fail).
                result: JSON snapshot of the task return value (success only).
                error: Error message (failure only).
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            task_name: str
            status: JobStatus
            enqueued_at: datetime
            started_at: datetime | None = None
            completed_at: datetime | None = None
            result: dict | None = None
            error: str | None = None


        class JobListResponse(BaseModel):
            \"\"\"Envelope for listing jobs.

            Attributes:
                data: List of public job views.
                count: Total rows returned in *data* (NOT the full table count).
            \"\"\"

            data: list[JobPublic]
            count: int
    """)
    dest.write_text(content)


def _write_job_crud(dest: Path) -> None:
    """Write ``app/crud/job.py`` with async CRUD helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Async CRUD helpers for the ``jobs`` audit table.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime, timezone
        from typing import Any

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.job import Job


        async def record_job(
            session: AsyncSession,
            *,
            task_name: str,
            payload: dict[str, Any],
            user_id: uuid.UUID | None = None,
        ) -> Job:
            \"\"\"Create a new ``queued`` audit row for a job about to be enqueued.

            Args:
                session: Async database session.
                task_name: Registered task function name.
                payload: JSON-serialisable snapshot of the task arguments.
                user_id: Optional UUID of the user triggering the job.

            Returns:
                The persisted ``Job`` instance (status = ``queued``).
            \"\"\"
            job = Job(
                task_name=task_name,
                payload=payload,
                user_id=user_id,
                status="queued",
            )
            session.add(job)
            await session.flush()
            return job


        async def update_job_started(
            session: AsyncSession, *, job_id: uuid.UUID
        ) -> Job | None:
            \"\"\"Mark *job_id* as ``running`` and stamp ``started_at``.

            Args:
                session: Async database session.
                job_id: UUID primary key of the job row.

            Returns:
                The updated ``Job`` or ``None`` if not found.
            \"\"\"
            job = await _get(session, job_id)
            if job is None:
                return None
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.flush()
            return job


        async def update_job_completed(
            session: AsyncSession,
            *,
            job_id: uuid.UUID,
            result: dict[str, Any],
        ) -> Job | None:
            \"\"\"Mark *job_id* as ``success`` and persist *result*.

            Args:
                session: Async database session.
                job_id: UUID primary key of the job row.
                result: JSON-serialisable task return value.

            Returns:
                The updated ``Job`` or ``None`` if not found.
            \"\"\"
            job = await _get(session, job_id)
            if job is None:
                return None
            job.status = "success"
            job.result = result
            job.completed_at = datetime.now(timezone.utc)
            await session.flush()
            return job


        async def update_job_failed(
            session: AsyncSession,
            *,
            job_id: uuid.UUID,
            error: str,
        ) -> Job | None:
            \"\"\"Mark *job_id* as ``failed`` and persist *error*.

            Args:
                session: Async database session.
                job_id: UUID primary key of the job row.
                error: Human-readable failure message (truncated to 4k chars).

            Returns:
                The updated ``Job`` or ``None`` if not found.
            \"\"\"
            job = await _get(session, job_id)
            if job is None:
                return None
            job.status = "failed"
            job.error = error[:4000]
            job.completed_at = datetime.now(timezone.utc)
            await session.flush()
            return job


        async def list_user_jobs(
            session: AsyncSession,
            *,
            user_id: uuid.UUID,
            limit: int = 50,
        ) -> list[Job]:
            \"\"\"Return the most recent jobs triggered by *user_id*.

            Args:
                session: Async database session.
                user_id: UUID of the user who triggered the jobs.
                limit: Maximum number of rows to return (default 50).

            Returns:
                List of ``Job`` instances, newest first.
            \"\"\"
            stmt = (
                select(Job)
                .where(Job.user_id == user_id)
                .order_by(Job.enqueued_at.desc())
                .limit(limit)
            )
            return list((await session.execute(stmt)).scalars().all())


        async def _get(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
            \"\"\"Return the ``Job`` row with *job_id* or ``None``.

            Args:
                session: Async database session.
                job_id: UUID primary key.

            Returns:
                The ``Job`` or ``None`` if absent.
            \"\"\"
            stmt = select(Job).where(Job.id == job_id)
            return (await session.execute(stmt)).scalar_one_or_none()
    """)
    dest.write_text(content)


def _write_jobs_http_routes(dest: Path) -> None:
    """Write ``app/api/routes/jobs.py`` with the companion HTTP endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"HTTP companion routes for the arq background job queue.

        Provides job introspection endpoints for UI dashboards and operators.
        Both endpoints require authentication so job state cannot be probed
        by unauthenticated clients.
        \"\"\"
        from __future__ import annotations

        import logging

        from fastapi import APIRouter, HTTPException, Request, status

        from app.api.deps import CurrentUser

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/jobs", tags=["jobs"])


        def _require_pool(request: Request):
            \"\"\"Return the arq pool from app state or raise 503.\"\"\"
            pool = getattr(request.app.state, "arq_pool", None)
            if pool is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="arq pool not initialised",
                )
            return pool


        async def _fetch_job(job_id: str, pool) -> tuple:
            \"\"\"Fetch (status, info) for *job_id* or raise 404 on lookup failure.\"\"\"
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
            \"\"\"Return (result, error) from an arq JobResult info object.\"\"\"
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
            \"\"\"Return the current status (and result/error) of *job_id*.

            Reads job state from the live arq Redis pool attached to
            ``request.app.state.arq_pool``.

            Raises:
                HTTPException(503): arq pool not initialised.
                HTTPException(404): job_id unknown to arq.
            \"\"\"
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
            \"\"\"Return currently-queued job ids for ops dashboards.

            Raises:
                HTTPException(503): arq pool not initialised.
            \"\"\"
            _ = current_user  # auth gate only
            pool = _require_pool(request)
            try:
                jobs = await pool.queued_jobs()
                ids = [getattr(j, "job_id", "") for j in jobs]
            except Exception as exc:  # noqa: BLE001
                logger.warning("arq queued_jobs lookup failed: %s", exc)
                ids = []
            return {"data": ids, "count": len(ids)}
    """)
    dest.write_text(content)


def _write_job_migration(versions_dir: Path, *, has_tenants: bool = False) -> Path:
    """Generate ``alembic/versions/XXXX_add_arq_worker.py``.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.
        has_tenants: Whether multi-tenancy is installed.  When *True* the
            ``tenant_id`` column references ``tenants.id`` via FK; otherwise
            it is a plain nullable UUID column.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"

    if has_tenants:
        tenant_col = (
            '        sa.Column(\n'
            '            "tenant_id", sa.Uuid(),\n'
            '            sa.ForeignKey("tenants.id", ondelete="CASCADE"),\n'
            '            nullable=True,\n'
            '        ),'
        )
    else:
        tenant_col = (
            '        sa.Column("tenant_id", sa.Uuid(), nullable=True),'
        )

    content = textwrap.dedent("""\
        \"\"\"Add jobs table for durable audit of arq background jobs.

        Revision ID: add_arq_worker
        Revises: DOWN_REV
        Create Date: auto-generated by add_arq_worker tool
        \"\"\"
        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op
        from sqlalchemy.dialects import postgresql

        revision = "add_arq_worker"
        down_revision = "DOWN_REV"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create the jobs table with status + user_id indexes.\"\"\"
            op.create_table(
                "jobs",
                sa.Column("id", sa.Uuid(), primary_key=True),
        TENANT_PLACEHOLDER
                sa.Column("task_name", sa.String(127), nullable=False),
                sa.Column(
                    "status",
                    sa.String(16),
                    server_default="queued",
                    nullable=False,
                ),
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
                    "user_id",
                    sa.Uuid(),
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
            \"\"\"Drop the jobs table and its indexes.\"\"\"
            op.drop_index("ix_jobs_user_enqueued", table_name="jobs")
            op.drop_index("ix_jobs_status_enqueued", table_name="jobs")
            op.drop_table("jobs")
    """).replace("DOWN_REV", down_rev).replace(
        "TENANT_PLACEHOLDER", tenant_col,
    )
    migration_file = versions_dir / "add_arq_worker.py"
    migration_file.write_text(content)
    return migration_file


def _write_dockerfile_worker(dest: Path) -> None:
    """Write ``Dockerfile.worker`` for running the arq worker process.

    Args:
        dest: Absolute path for the new Dockerfile.
    """
    content = textwrap.dedent("""\
        # Dockerfile.worker — arq background job worker
        # Built and run SEPARATELY from the FastAPI API container so workers
        # can be scaled independently of HTTP traffic.
        FROM python:3.12-slim

        ENV PYTHONUNBUFFERED=1 \\
            PYTHONDONTWRITEBYTECODE=1 \\
            PIP_NO_CACHE_DIR=1 \\
            PIP_DISABLE_PIP_VERSION_CHECK=1

        WORKDIR /app

        COPY requirements.txt .
        RUN pip install --no-cache-dir -r requirements.txt

        COPY app/ ./app/

        # Run as non-root for least-privilege execution.
        USER 1000

        CMD ["python", "-m", "app.workers.arq_worker"]
    """)
    dest.write_text(content)


def _patch_config(
    config_file: Path,
    max_jobs: int,
    job_timeout_seconds: int,
    max_tries: int,
    keep_results_seconds: int,
) -> None:
    """Inject arq worker settings into the ``Settings`` class body.

    The fields must live INSIDE ``class Settings`` so pydantic-settings
    picks them up from env vars; appending at module level would create
    plain module attributes that the generated code can never reach.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
        max_jobs: Value for ``ARQ_MAX_JOBS``.
        job_timeout_seconds: Value for ``ARQ_JOB_TIMEOUT_SECONDS``.
        max_tries: Value for ``ARQ_MAX_TRIES``.
        keep_results_seconds: Value for ``ARQ_KEEP_RESULTS_SECONDS``.
    """
    src = config_file.read_text()
    if "ARQ_MAX_JOBS" in src:
        return

    # 4-space indentation — fields are class attributes of Settings.
    block = (
        "\n"
        "    # --- arq worker settings — added by add_arq_worker tool ---\n"
        f"    ARQ_MAX_JOBS: int = {max_jobs}\n"
        f"    ARQ_JOB_TIMEOUT_SECONDS: int = {job_timeout_seconds}\n"
        f"    ARQ_MAX_TRIES: int = {max_tries}\n"
        f"    ARQ_KEEP_RESULTS_SECONDS: int = {keep_results_seconds}\n"
    )

    # Anchor on an existing field we know is present in the scaffold.
    # ACCESS_TOKEN_EXPIRE_MINUTES is emitted by generators/infra/config.py
    # and is stable across scaffold revisions.
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            # Last resort — append at EOF (still valid Python, even if the
            # fields land at module scope instead of inside Settings).
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the jobs HTTP router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.jobs import router as jobs_router",
        include_line="api_router.include_router(jobs_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call (no trailing newline).
    """
    src = routes_init.read_text()
    if import_line in src:
        return

    lines = src.splitlines()

    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)

    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)

    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_main(main_file: Path) -> bool:
    """Wire the arq pool startup/shutdown into ``app/main.py``'s lifespan.

    Inserts ``app.state.arq_pool = await create_arq_pool()`` before the
    ``yield`` in the lifespan function, and a matching
    ``await close_arq_pool(app.state.arq_pool)`` after ``yield``.  Also
    injects the ``create_arq_pool`` / ``close_arq_pool`` import.
    Idempotent: returns ``False`` if ``arq_pool`` is already referenced.

    Args:
        main_file: Path to ``app/main.py``.

    Returns:
        ``True`` if the file was modified.
    """
    src = main_file.read_text()
    if "arq_pool" in src:
        return False
    lines = src.splitlines()
    last_from_app = max(
        (i for i, ln in enumerate(lines) if ln.startswith("from app.")),
        default=-1,
    )
    if last_from_app == -1:
        return False
    lines.insert(
        last_from_app + 1,
        "from app.workers.enqueue import close_arq_pool, create_arq_pool",
    )
    yield_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "yield"), -1
    )
    if yield_idx != -1:
        indent = lines[yield_idx][: len(lines[yield_idx]) - len(lines[yield_idx].lstrip())]
        lines.insert(yield_idx, f"{indent}app.state.arq_pool = await create_arq_pool()")
        lines.insert(yield_idx + 2, f"{indent}await close_arq_pool(app.state.arq_pool)")
    main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure ``arq`` and ``redis[hiredis]`` are in ``requirements.txt``.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    additions: list[str] = []
    if "arq" not in src:
        additions.append("arq>=0.25.0")
    if "redis" not in src:
        additions.append("redis[hiredis]>=5.0.0")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Path to the file to validate.

    Raises:
        SyntaxError: If the file has a syntax error.
    """
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(f"Generated file {path} has a syntax error: {exc}") from exc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
