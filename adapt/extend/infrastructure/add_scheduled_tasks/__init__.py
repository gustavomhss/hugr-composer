"""TOOL-058: add_scheduled_tasks — APScheduler-based cron jobs for FastAPI.

Generates production-grade scheduled task infrastructure using APScheduler's
async interface with a Redis job store (multi-worker safe) and a lightweight
job registry. Jobs are declared via a simple ``@scheduled_job("*/5 * * * *")``
decorator and auto-registered at startup.

WARNING (honesty, §4): The emitted scheduler runs IN-PROCESS. It is NOT
clustered. Multiple app instances will each run their own scheduler,
potentially executing jobs multiple times.

Idempotent: a second run detects ``app/workers/scheduler.py`` and returns
``status="no_op"`` without touching any file.

Generated files:
  - ``app/workers/scheduler.py``       APScheduler factory + lifespan integration
  - ``app/workers/cron_jobs.py``       Job registry + 3 example cron jobs
  - ``app/api/routes/scheduler.py``    GET /scheduler/jobs endpoint

Patched files:
  - ``app/core/config.py``    SCHEDULER_* fields
  - ``app/main.py``           lifespan start/stop hooks
  - ``requirements.txt``      ``apscheduler>=3.10.0``
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_scheduled_tasks",
    "description": (
        "Add APScheduler-based cron jobs with Redis job store, decorator "
        "registry, and FastAPI lifespan integration."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_scheduled_tasks",
}


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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    project = Path(inp.project_dir)

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

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

    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init = workers_dir / "__init__.py"
    if not workers_init.exists():
        workers_init.write_text('"""Background worker package."""\n')
        files_created.append(str(workers_init))

    render_to(_HERE, "scheduler.py.tmpl", dest=scheduler_file, substitutions={})
    files_created.append(str(scheduler_file))

    cron_jobs_file = workers_dir / "cron_jobs.py"
    render_to(_HERE, "cron_jobs.py.tmpl", dest=cron_jobs_file, substitutions={})
    files_created.append(str(cron_jobs_file))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "scheduler.py"
        render_to(_HERE, "scheduler_status_route.py.tmpl", dest=status_route, substitutions={})
        files_created.append(str(status_route))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        if "apscheduler" not in req_src.lower():
            req_file.write_text(req_src.rstrip("\n") + "\napscheduler>=3.10.0\n")
            files_modified.append(str(req_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "APScheduler with Redis/memory job store installed.",
            "WARNING: Scheduler runs IN-PROCESS (NOT clustered). Multiple instances "
            "will each run their own scheduler, potentially duplicating job execution.",
            "Cron jobs registered via @scheduled_job decorator auto-start in main.py lifespan.",
            "3 example jobs generated: cleanup_expired_sessions, refresh_materialized_view, "
            "health_heartbeat.",
        ],
        next_steps=[
            "pip install 'apscheduler>=3.10.0'",
            "Optionally set SCHEDULER_JOBSTORE_URL to a Redis DSN for multi-instance persistence.",
            "Register new jobs via @scheduled_job('0 */6 * * *') in app/workers/cron_jobs.py.",
            "Inspect live schedule via GET /scheduler/jobs (requires auth).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject ``SCHEDULER_*`` fields inside the ``Settings`` class body."""
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
    """Hook ``start_scheduler`` / ``stop_scheduler`` into the lifespan."""
    src = main_file.read_text()
    if "start_scheduler" in src:
        return
    import_line = (
        "\nfrom app.workers.scheduler import start_scheduler, stop_scheduler  "
        "# noqa: F401 — scheduled tasks\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI", "from fastapi import FastAPI" + import_line
        )
    else:
        src = import_line + src
    if "async def lifespan" in src and "yield" in src:
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
            if (
                in_lifespan
                and injected_start
                and not injected_stop
                and ("engine.dispose" in line or stripped.startswith("# --- Shutdown"))
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
    main_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_scheduled_tasks_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_scheduled_tasks_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_scheduled_tasks_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
