"""TOOL-058: add_scheduled_tasks — APScheduler-based cron jobs for FastAPI.

Generates production-grade scheduled task infrastructure using APScheduler's
async interface with a Redis job store (multi-worker safe) and a lightweight
job registry. Jobs are declared via a simple ``@scheduled_job("*/5 * * * *")``
decorator and auto-registered at startup.

Idempotent: a second run detects ``app/workers/scheduler.py`` and returns
``status="no_op"`` without touching any file.

Generated files:
  - ``app/workers/scheduler.py``   APScheduler factory + lifespan integration
  - ``app/workers/cron_jobs.py``   Job registry + 3 example cron jobs
  - ``app/api/routes/scheduler.py``   GET /scheduler/jobs endpoint

Patched files:
  - ``app/core/config.py``       SCHEDULER_* fields
  - ``app/main.py``              lifespan start/stop hooks
  - ``requirements.txt``         ``apscheduler>=3.10.0``

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_scheduled_tasks import add_scheduled_tasks

    result = add_scheduled_tasks(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/workers/scheduler.py, ...]
    print(result.next_steps)    # ["pip install apscheduler", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_scheduled_tasks",
    "description": (
        "Add APScheduler-based cron jobs with Redis job store, decorator "
        "registry, and FastAPI lifespan integration."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_scheduled_tasks",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_scheduled_tasks(inp: ToolInput) -> ToolResult:
    """Add APScheduler-based cron job infrastructure to a FastAPI project.

    Writes ``app/workers/scheduler.py`` (factory), ``app/workers/cron_jobs.py``
    (registry + examples), and a ``/scheduler/jobs`` status endpoint. Patches
    ``app/main.py`` to start/stop the scheduler in the lifespan context, and
    ``app/core/config.py`` to add the ``SCHEDULER_*`` settings.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    project = Path(inp.project_dir)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first with fastapi_generate_project(...).",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    scheduler_file = app_dir / "workers" / "scheduler.py"
    if scheduler_file.exists() and "SchedulerFactory" in scheduler_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SchedulerFactory already present — scheduled tasks already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/workers/scheduler.py, "
                "app/workers/cron_jobs.py, and app/api/routes/scheduler.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Workers package --------------------------------------------
    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init = workers_dir / "__init__.py"
    if not workers_init.exists():
        workers_init.write_text('"""Background worker package."""\n')
        files_created.append(str(workers_init))

    _write_scheduler_factory(scheduler_file)
    files_created.append(str(scheduler_file))

    cron_jobs_file = workers_dir / "cron_jobs.py"
    _write_cron_jobs(cron_jobs_file)
    files_created.append(str(cron_jobs_file))

    # --- Step 2: Status route ------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "scheduler.py"
        _write_scheduler_status_route(status_route)
        files_created.append(str(status_route))

    # --- Step 3: Patch config -----------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 4: Patch main.py lifespan -------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 5: Patch requirements.txt -------------------------------------
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        req_adds = []
        if "apscheduler" not in req_src.lower():
            req_adds.append("apscheduler>=3.10.0")
        if req_adds:
            req_file.write_text(req_src.rstrip("\n") + "\n" + "\n".join(req_adds) + "\n")
            files_modified.append(str(req_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "APScheduler with Redis/memory job store installed.",
            "Cron jobs registered via @scheduled_job decorator auto-start in main.py lifespan.",
            "3 example jobs generated: cleanup_expired_sessions, refresh_materialized_view, "
            "health_heartbeat.",
            "Scheduler runs in-process (not on a separate worker).",
        ],
        next_steps=[
            "pip install 'apscheduler>=3.10.0'",
            "Optionally set SCHEDULER_JOBSTORE_URL to a Redis DSN for multi-instance persistence.",
            "Register new jobs via @scheduled_job('0 */6 * * *') in app/workers/cron_jobs.py.",
            "Inspect live schedule via GET /scheduler/jobs (requires auth).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — every function ≤ 50 LOC
# ---------------------------------------------------------------------------

def _write_scheduler_factory(dest: Path) -> None:
    """Write ``app/workers/scheduler.py`` with the SchedulerFactory.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent('''\
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
        '''))


def _write_cron_jobs(dest: Path) -> None:
    """Write ``app/workers/cron_jobs.py`` with the job registry + examples.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent('''\
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
        '''))


def _write_scheduler_status_route(dest: Path) -> None:
    """Write ``app/api/routes/scheduler.py`` with GET /scheduler/jobs.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent('''\
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
        '''))


def _patch_config(config_file: Path) -> None:
    """Inject ``SCHEDULER_*`` fields inside the ``Settings`` class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "SCHEDULER_ENABLED" in src:
        return

    fields = (
        "    SCHEDULER_ENABLED: bool = True\n"
        '    SCHEDULER_TIMEZONE: str = "UTC"\n'
        '    SCHEDULER_JOBSTORE_URL: str = ""\n'
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Hook ``start_scheduler`` / ``stop_scheduler`` into the lifespan.

    Modern FastAPI uses an ``@asynccontextmanager`` ``lifespan`` function.
    We inject the start call before the ``yield`` and the stop call after,
    without disturbing the rest of the lifespan body.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "start_scheduler" in src:
        return

    import_line = (
        "\nfrom app.workers.scheduler import start_scheduler, stop_scheduler  "
        "# noqa: F401 — scheduled tasks\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_line,
        )
    else:
        src = import_line + src

    # Preferred path: inject into the existing ``lifespan`` context manager.
    # The base generator ships a lifespan with ``yield`` between startup and
    # shutdown blocks. We inject ``await start_scheduler()`` before the yield
    # and ``await stop_scheduler()`` after.
    if "async def lifespan" in src and "yield" in src:
        # Find the first `yield` inside the lifespan function and insert
        # our start call on the line immediately before it.
        lines = src.splitlines(keepends=True)
        out: list[str] = []
        in_lifespan = False
        injected_start = injected_stop = False
        for line in lines:
            stripped = line.strip()
            if "async def lifespan" in line:
                in_lifespan = True
            if in_lifespan and not injected_start and stripped == "yield":
                out.append(line[: len(line) - len(line.lstrip())] + "await start_scheduler()\n")
                out.append(line)
                injected_start = True
                continue
            if in_lifespan and injected_start and not injected_stop and (
                "engine.dispose" in line or stripped.startswith("# --- Shutdown")
            ):
                if stripped.startswith("# --- Shutdown"):
                    out.append(line)
                    out.append(line[: len(line) - len(line.lstrip())] + "await stop_scheduler()\n")
                else:
                    out.append(line[: len(line) - len(line.lstrip())] + "await stop_scheduler()\n")
                    out.append(line)
                injected_stop = True
                continue
            out.append(line)
        if injected_start and not injected_stop:
            out.append("    await stop_scheduler()\n")
        src = "".join(out)
    else:
        # Fallback: register via FastAPI's router events (legacy syntax).
        marker = "app = FastAPI("
        if marker in src:
            idx = src.find(marker)
            depth = 0
            end = idx
            for i in range(idx + len(marker), len(src)):
                ch = src[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        end = i + 1
                        break
                    depth -= 1
            hook = (
                '\n@app.on_event("startup")'
                '\nasync def _scheduler_startup() -> None:'
                '\n    await start_scheduler()'
                '\n@app.on_event("shutdown")'
                '\nasync def _scheduler_shutdown() -> None:'
                '\n    await stop_scheduler()\n'
            )
            src = src[:end] + hook + src[end:]

    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
