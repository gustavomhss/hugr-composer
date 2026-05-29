"""TOOL-059: add_celery_beat — add Celery Beat scheduled task system to a FastAPI project.

Writes an ``app/workers/`` package containing:

* ``celery_app.py`` — Celery application factory with broker/backend from
  ``settings`` (lazy import so the app boots without celery installed).
* ``celery_tasks.py`` — Task registry with 3 example tasks.
* ``celery_beat_schedule.py`` — Beat schedule configuration using crontab entries.
* ``app/api/routes/celery_status.py`` — ``GET /celery/status`` endpoint.
* ``Dockerfile.celery-worker`` — Worker container (non-root USER).
* ``Dockerfile.celery-beat`` — Beat scheduler container.

Idempotency: a second run detects the ``celery_app`` fingerprint in
``app/workers/celery_app.py`` and returns ``status="no_op"`` without
touching any file.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_celery_beat",
    "description": (
        "Add Celery Beat scheduled tasks to a FastAPI project: "
        "celery app factory, task registry, beat schedule, status route, "
        "and separate Dockerfiles for worker and beat processes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_celery_beat",
}


def add_celery_beat(inp: ToolInput) -> ToolResult:
    """Add Celery Beat scheduled task system to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    celery_app_file = app_dir / "workers" / "celery_app.py"
    if celery_app_file.exists() and "celery_app" in celery_app_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["celery_app already present — Celery Beat is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/workers/ package (celery_app.py, celery_tasks.py,",
                "         celery_beat_schedule.py), GET /celery/status HTTP route,",
                "         Dockerfile.celery-worker, Dockerfile.celery-beat.",
                "[dry_run] Would patch app/core/config.py with CELERY_BROKER_URL,",
                "         CELERY_RESULT_BACKEND, CELERY_TASK_ALWAYS_EAGER.",
                "[dry_run] Would add celery[redis]>=5.4.0 to requirements.txt.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init = workers_dir / "__init__.py"
    if not workers_init.exists():
        workers_init.write_text('"""Celery workers sub-package."""\n')
        files_created.append(str(workers_init))

    render_to(_HERE, "celery_app.py.tmpl", dest=celery_app_file, substitutions={})
    files_created.append(str(celery_app_file))

    tasks_file = workers_dir / "celery_tasks.py"
    render_to(_HERE, "celery_tasks.py.tmpl", dest=tasks_file, substitutions={})
    files_created.append(str(tasks_file))

    beat_schedule_file = workers_dir / "celery_beat_schedule.py"
    render_to(_HERE, "celery_beat_schedule.py.tmpl", dest=beat_schedule_file, substitutions={})
    files_created.append(str(beat_schedule_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    status_route_file = routes_dir / "celery_status.py"
    render_to(_HERE, "celery_status_route.py.tmpl", dest=status_route_file, substitutions={})
    files_created.append(str(status_route_file))

    dockerfile_worker = project / "Dockerfile.celery-worker"
    if not dockerfile_worker.exists():
        render_to(
            _HERE,
            "Dockerfile.celery-worker.tmpl",
            dest=dockerfile_worker,
            substitutions={},
        )
        files_created.append(str(dockerfile_worker))

    dockerfile_beat = project / "Dockerfile.celery-beat"
    if not dockerfile_beat.exists():
        render_to(
            _HERE,
            "Dockerfile.celery-beat.tmpl",
            dest=dockerfile_beat,
            substitutions={},
        )
        files_created.append(str(dockerfile_beat))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Celery Beat added: celery_app factory, task registry (3 tasks),",
            "beat schedule (crontab-based), GET /celery/status HTTP route.",
            "Celery runs as a SEPARATE process — app/main.py is not modified.",
            "Broker and result backend read from settings.CELERY_BROKER_URL / "
            "CELERY_RESULT_BACKEND (default: REDIS_URL).",
            "CELERY_TASK_ALWAYS_EAGER=False by default; set to True in test env.",
            "Dockerfile.celery-worker and Dockerfile.celery-beat run as non-root USER 1000.",
        ],
        next_steps=[
            "Set CELERY_BROKER_URL and CELERY_RESULT_BACKEND in .env "
            "(or leave unset to inherit REDIS_URL).",
            "Start the worker: docker build -f Dockerfile.celery-worker -t myapp-celery-worker . "
            "&& docker run --rm --env-file .env myapp-celery-worker",
            "Start the beat scheduler: docker build -f Dockerfile.celery-beat -t myapp-celery-beat . "
            "&& docker run --rm --env-file .env myapp-celery-beat",
            "Or locally: celery -A app.workers.celery_app worker --loglevel=info",
            "           celery -A app.workers.celery_app beat --loglevel=info",
            "Verify: inspect active tasks via GET /celery/status (requires auth).",
            "Customize beat schedule in app/workers/celery_beat_schedule.py.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_celery_beat_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_celery_beat_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_celery_beat_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    """Inject Celery settings fields into the ``Settings`` class body idempotently."""
    src = config_file.read_text()
    if "CELERY_BROKER_URL" in src:
        return

    block = (
        "\n"
        "    # --- Celery settings — added by add_celery_beat tool ---\n"
        '    CELERY_BROKER_URL: str = ""\n'
        '    CELERY_RESULT_BACKEND: str = ""\n'
        "    CELERY_TASK_ALWAYS_EAGER: bool = False\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block

    config_file.write_text(src)


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure ``celery[redis]>=5.4.0`` is in ``requirements.txt``."""
    src = requirements_file.read_text()
    if "celery" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "celery[redis]>=5.4.0\n")


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
