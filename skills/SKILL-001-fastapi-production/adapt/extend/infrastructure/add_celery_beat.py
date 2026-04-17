"""TOOL-059: add_celery_beat — add Celery Beat scheduled task system to a FastAPI project.

Writes an ``app/workers/`` package containing:

* ``celery_app.py`` — Celery application factory with broker/backend from
  ``settings`` (lazy import so the app boots without celery installed).
* ``celery_tasks.py`` — Task registry with 3 example tasks
  (``cleanup_expired``, ``send_digest``, ``sync_external``).
* ``celery_beat_schedule.py`` — Beat schedule configuration using
  ``crontab`` entries.
* ``app/api/routes/celery_status.py`` — ``GET /celery/status`` endpoint
  (inspects active workers / active tasks via ``celery.app.control``).
* ``Dockerfile.celery-worker`` — Worker container (non-root USER).
* ``Dockerfile.celery-beat`` — Beat scheduler container.

Patches:

* ``app/core/config.py`` — adds ``CELERY_BROKER_URL``,
  ``CELERY_RESULT_BACKEND``, ``CELERY_TASK_ALWAYS_EAGER`` fields.
* ``requirements.txt`` — adds ``celery[redis]>=5.4.0``.

Key design decisions:

* Celery runs as a SEPARATE process (not in-process like APScheduler).
  ``app/main.py`` is therefore NOT modified.
* Broker = Redis (``settings.CELERY_BROKER_URL``, defaulting to
  ``settings.REDIS_URL``).
* Result backend = Redis (``settings.CELERY_RESULT_BACKEND``).
* Beat schedule uses ``crontab()`` from ``celery.schedules``.
* Task discovery via ``autodiscover_tasks`` pointing at
  ``app.workers.celery_tasks``.
* ``CELERY_TASK_ALWAYS_EAGER=True`` in test mode (tasks execute synchronously).

Idempotency: a second run detects the ``celery_app`` fingerprint in
``app/workers/celery_app.py`` and returns ``status="no_op"`` without
touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_celery_beat import add_celery_beat

    result = add_celery_beat(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/workers/celery_app.py", …]
    print(result.next_steps)    # ["celery -A app.workers.celery_app worker …", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_celery_beat",
    "description": (
        "Add Celery Beat scheduled tasks to a FastAPI project: "
        "celery app factory, task registry, beat schedule, status route, "
        "and separate Dockerfiles for worker and beat processes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_celery_beat",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_celery_beat(inp: ToolInput) -> ToolResult:
    """Add Celery Beat scheduled task system to a FastAPI project.

    Creates the Celery app factory, task registry, beat schedule, HTTP status
    route, and Dockerfiles for the worker and beat processes.  Patches
    ``app/core/config.py`` and ``requirements.txt``.

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

    # Step 1 — workers package
    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init = workers_dir / "__init__.py"
    if not workers_init.exists():
        workers_init.write_text('"""Celery workers sub-package."""\n')
        files_created.append(str(workers_init))

    # Step 2 — celery app factory
    _write_celery_app(celery_app_file)
    files_created.append(str(celery_app_file))

    # Step 3 — task registry
    tasks_file = workers_dir / "celery_tasks.py"
    _write_celery_tasks(tasks_file)
    files_created.append(str(tasks_file))

    # Step 4 — beat schedule
    beat_schedule_file = workers_dir / "celery_beat_schedule.py"
    _write_beat_schedule(beat_schedule_file)
    files_created.append(str(beat_schedule_file))

    # Step 5 — HTTP status route
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    status_route_file = routes_dir / "celery_status.py"
    _write_status_route(status_route_file)
    files_created.append(str(status_route_file))

    # Step 6 — Dockerfile.celery-worker
    dockerfile_worker = project / "Dockerfile.celery-worker"
    if not dockerfile_worker.exists():
        _write_dockerfile_worker(dockerfile_worker)
        files_created.append(str(dockerfile_worker))

    # Step 7 — Dockerfile.celery-beat
    dockerfile_beat = project / "Dockerfile.celery-beat"
    if not dockerfile_beat.exists():
        _write_dockerfile_beat(dockerfile_beat)
        files_created.append(str(dockerfile_beat))

    # Step 8 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 9 — patch requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate every generated .py file parses cleanly
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            _assert_parses(p)

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


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_celery_app(dest: Path) -> None:
    """Write ``app/workers/celery_app.py`` with the Celery factory.

    Uses a lazy import pattern so the FastAPI app boots without celery
    installed (celery is only imported when the factory is called).

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Celery application factory.

        Celery is imported lazily so the FastAPI process can boot even if the
        celery package is not installed.  The worker and beat processes import
        this module directly, which triggers the real import.

        Broker and result backend are read from ``app.core.config.settings``
        so no DSN is ever hard-coded here.
        \"\"\"
        from __future__ import annotations

        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from celery import Celery  # pragma: no cover


        def create_celery_app() -> "Celery":
            \"\"\"Build and return a configured Celery application instance.

            Reads broker URL from ``settings.CELERY_BROKER_URL`` (falls back to
            ``settings.REDIS_URL``) and result backend from
            ``settings.CELERY_RESULT_BACKEND``.

            Task modules are discovered via ``autodiscover_tasks`` pointing at
            ``app.workers.celery_tasks`` so adding new task modules does not
            require editing this factory.

            Returns:
                A fully configured ``Celery`` application instance.
            \"\"\"
            from celery import Celery  # noqa: PLC0415 — lazy import by design

            from app.core.config import settings
            from app.workers.celery_beat_schedule import BEAT_SCHEDULE

            broker = getattr(settings, "CELERY_BROKER_URL", None) or str(settings.REDIS_URL)
            backend = getattr(settings, "CELERY_RESULT_BACKEND", None) or str(settings.REDIS_URL)
            always_eager = bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))

            app = Celery(
                "app",
                broker=broker,
                backend=backend,
                include=["app.workers.celery_tasks"],
            )
            app.config_from_object(
                {
                    "task_always_eager": always_eager,
                    "task_eager_propagates": always_eager,
                    "beat_schedule": BEAT_SCHEDULE,
                    "timezone": "UTC",
                    "task_serializer": "json",
                    "result_serializer": "json",
                    "accept_content": ["json"],
                }
            )
            app.autodiscover_tasks(["app.workers.celery_tasks"])
            return app


        # Module-level singleton consumed by the celery CLI and Dockerfiles.
        celery_app = create_celery_app()
    """)
    dest.write_text(content)


def _write_celery_tasks(dest: Path) -> None:
    """Write ``app/workers/celery_tasks.py`` with 3 example tasks.

    Tasks: ``cleanup_expired``, ``send_digest``, ``sync_external``.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Celery task registry.

        Tasks are discovered automatically by the Celery worker via
        ``autodiscover_tasks(["app.workers.celery_tasks"])``.

        To add a new task:

        1. Define a function decorated with ``@celery_app.task``.
        2. The worker picks it up on the next restart.

        Celery is imported lazily at the top of this module so that running
        the FastAPI server without celery installed does not cause an
        ``ImportError``.
        \"\"\"
        from __future__ import annotations

        import logging
        from typing import Any

        logger = logging.getLogger(__name__)

        # ---------------------------------------------------------------------------
        # Lazy Celery import — app boots without celery installed
        # ---------------------------------------------------------------------------
        try:
            from app.workers.celery_app import celery_app  # noqa: PLC0415
            _CELERY_AVAILABLE = True
        except Exception:  # noqa: BLE001
            celery_app = None  # type: ignore[assignment]
            _CELERY_AVAILABLE = False


        def _task(func: Any) -> Any:
            \"\"\"Decorator that applies ``@celery_app.task`` when celery is available.

            Falls back to a no-op wrapper when celery is absent so the module
            can be imported in test environments without a running broker.

            Args:
                func: The task function to decorate.

            Returns:
                The decorated (or unchanged) function.
            \"\"\"
            if _CELERY_AVAILABLE and celery_app is not None:
                return celery_app.task(bind=False)(func)
            return func


        @_task
        def cleanup_expired() -> dict[str, Any]:
            \"\"\"Scheduled task: purge expired records and tokens.

            Designed to run periodically via the beat schedule (e.g. nightly).
            Replace the stub body with real cleanup logic (soft-deleted row
            purge, expired session sweep, stale file removal, etc.).

            Returns:
                Dict with ``status`` and ``cleaned`` count.
            \"\"\"
            logger.info("cleanup_expired: starting sweep")
            # Stub: replace with real cleanup logic in production.
            return {"status": "ok", "cleaned": 0}


        @_task
        def send_digest(user_id: str, digest_type: str = "weekly") -> dict[str, Any]:
            \"\"\"Scheduled task: send a periodic digest email to a user.

            Args:
                user_id: UUID string of the target user.
                digest_type: Digest frequency label (e.g. ``weekly``, ``daily``).

            Returns:
                Dict with ``status``, ``user_id``, and ``digest_type``.
            \"\"\"
            logger.info(
                "send_digest: user=%s type=%s",
                user_id,
                digest_type,
            )
            # Stub: call an email service (SES, Postmark, etc.) here.
            return {"status": "sent", "user_id": user_id, "digest_type": digest_type}


        @_task
        def sync_external(source: str = "default") -> dict[str, Any]:
            \"\"\"Scheduled task: pull updates from an external data source.

            Args:
                source: Named data source to sync (e.g. ``"crm"``, ``"erp"``).

            Returns:
                Dict with ``status``, ``source``, and ``synced`` record count.
            \"\"\"
            logger.info("sync_external: source=%s", source)
            # Stub: call external API or import pipeline here.
            return {"status": "ok", "source": source, "synced": 0}
    """)
    dest.write_text(content)


def _write_beat_schedule(dest: Path) -> None:
    """Write ``app/workers/celery_beat_schedule.py`` with crontab entries.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Celery Beat schedule configuration.

        ``BEAT_SCHEDULE`` is consumed by ``create_celery_app()`` in
        ``app/workers/celery_app.py``.  Each entry maps a human-readable
        schedule name to a dict with ``task``, ``schedule``, and optional
        ``args`` / ``kwargs``.

        ``crontab`` notation (minute, hour, day_of_week, day_of_month,
        month_of_year) is used throughout for readability.

        Celery is imported lazily so this module loads cleanly without a
        running broker (e.g. during unit tests).
        \"\"\"
        from __future__ import annotations

        try:
            from celery.schedules import crontab  # noqa: PLC0415
        except ImportError:  # pragma: no cover — celery not installed
            crontab = None  # type: ignore[assignment, misc]


        def _cron(**kwargs) -> object:  # type: ignore[return]
            \"\"\"Return a crontab or a sentinel object when celery is absent.

            Args:
                **kwargs: Forwarded verbatim to ``crontab()``.

            Returns:
                A ``crontab`` instance, or ``None`` when celery is not installed.
            \"\"\"
            if crontab is not None:
                return crontab(**kwargs)
            return None  # pragma: no cover


        #: Beat schedule mapping consumed by the Celery application factory.
        BEAT_SCHEDULE: dict = {
            # Run cleanup at 02:00 UTC every night.
            "cleanup-expired-nightly": {
                "task": "app.workers.celery_tasks.cleanup_expired",
                "schedule": _cron(hour=2, minute=0),
            },
            # Send weekly digest every Monday at 08:00 UTC.
            "send-digest-weekly": {
                "task": "app.workers.celery_tasks.send_digest",
                "schedule": _cron(hour=8, minute=0, day_of_week=1),
                "kwargs": {"digest_type": "weekly"},
            },
            # Sync external source every 30 minutes during business hours.
            "sync-external-business-hours": {
                "task": "app.workers.celery_tasks.sync_external",
                "schedule": _cron(minute="*/30", hour="8-18"),
                "kwargs": {"source": "default"},
            },
        }
    """)
    dest.write_text(content)


def _write_status_route(dest: Path) -> None:
    """Write ``app/api/routes/celery_status.py`` with GET /celery/status.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"HTTP route for Celery worker health / active-task inspection.

        Provides a single authenticated endpoint that operators and dashboards
        can poll to verify that workers are alive and to see which tasks are
        currently running.

        Celery is imported lazily so this module loads cleanly without a
        running broker.
        \"\"\"
        from __future__ import annotations

        import logging

        from fastapi import APIRouter, HTTPException, status

        from app.api.deps import CurrentUser

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/celery", tags=["celery"])


        def _get_celery_app():
            \"\"\"Return the module-level Celery app instance or raise 503.

            Returns:
                The ``Celery`` application instance.

            Raises:
                HTTPException(503): celery package not installed or app unavailable.
            \"\"\"
            try:
                from app.workers.celery_app import celery_app  # noqa: PLC0415
                return celery_app
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Celery is not available",
                ) from exc


        def _inspect_workers(app) -> dict:
            \"\"\"Return active-task info from all reachable workers.

            Uses a short 2-second timeout so the endpoint stays responsive
            even when no workers are running.

            Args:
                app: The ``Celery`` application instance.

            Returns:
                Dict with ``active`` (per-worker active task lists) and
                ``workers`` (list of reachable worker names).
            \"\"\"
            try:
                inspector = app.control.inspect(timeout=2.0)
                active = inspector.active() or {}
                return {
                    "active": active,
                    "workers": list(active.keys()),
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("celery inspect failed: %s", exc)
                return {"active": {}, "workers": []}


        @router.get("/status")
        async def get_celery_status(current_user: CurrentUser) -> dict:
            \"\"\"Return active Celery worker and task information.

            Inspects all reachable workers and returns their active task lists.
            Requires authentication — task details must not be publicly visible.

            Raises:
                HTTPException(503): Celery package unavailable.
            \"\"\"
            _ = current_user  # auth gate only
            app = _get_celery_app()
            info = _inspect_workers(app)
            return {
                "status": "ok" if info["workers"] else "no_workers",
                "workers": info["workers"],
                "active_tasks": info["active"],
            }
    """)
    dest.write_text(content)


def _write_dockerfile_worker(dest: Path) -> None:
    """Write ``Dockerfile.celery-worker`` for the Celery worker process.

    Args:
        dest: Absolute path for the new Dockerfile.
    """
    content = textwrap.dedent("""\
        # Dockerfile.celery-worker — Celery background task worker
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

        CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info"]
    """)
    dest.write_text(content)


def _write_dockerfile_beat(dest: Path) -> None:
    """Write ``Dockerfile.celery-beat`` for the Celery Beat scheduler.

    Args:
        dest: Absolute path for the new Dockerfile.
    """
    content = textwrap.dedent("""\
        # Dockerfile.celery-beat — Celery Beat periodic task scheduler
        # Run EXACTLY ONE instance of this container at a time.
        # Running multiple beat instances causes duplicate task firing.
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

        CMD ["celery", "-A", "app.workers.celery_app", "beat", "--loglevel=info"]
    """)
    dest.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject Celery settings fields into the ``Settings`` class body.

    The fields live INSIDE ``class Settings`` so pydantic-settings picks
    them up from env vars.  Idempotent — returns immediately when the
    marker ``CELERY_BROKER_URL`` is already present.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "CELERY_BROKER_URL" in src:
        return

    block = (
        "\n"
        "    # --- Celery settings — added by add_celery_beat tool ---\n"
        "    CELERY_BROKER_URL: str = \"\"\n"
        "    CELERY_RESULT_BACKEND: str = \"\"\n"
        "    CELERY_TASK_ALWAYS_EAGER: bool = False\n"
    )

    # Anchor: ACCESS_TOKEN_EXPIRE_MINUTES is stable across scaffold revisions.
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
    """Ensure ``celery[redis]>=5.4.0`` is in ``requirements.txt``.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    if "celery" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "celery[redis]>=5.4.0\n")


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
        raise SyntaxError(
            f"Generated file {path} has a syntax error: {exc}"
        ) from exc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
