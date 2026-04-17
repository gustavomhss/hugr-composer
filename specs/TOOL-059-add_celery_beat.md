# TOOL-059: add_celery_beat

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_celery_beat` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, Redis, celery[redis]>=5.4.0, pydantic-settings |
| Signature | `add_celery_beat(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_celery_beat", "description": "Add Celery Beat scheduled tasks to a FastAPI project: celery app factory, task registry, beat schedule, status route, and separate Dockerfiles for worker and beat processes.", "tags": ["extend", "infrastructure"], "entry": "add_celery_beat"}` |
| Files created (typical) | 7 — `app/workers/__init__.py`, `app/workers/celery_app.py`, `app/workers/celery_tasks.py`, `app/workers/celery_beat_schedule.py`, `app/api/routes/celery_status.py`, `Dockerfile.celery-worker`, `Dockerfile.celery-beat` |
| Files modified (typical) | 2 — `app/core/config.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_celery_beat` tool installs a production-grade Celery scheduled task system into a FastAPI project — including the worker runtime, crontab-based beat scheduler, HTTP status inspection route, and separate Dockerfiles — without any in-process coupling to the FastAPI application. Teams that need periodic background jobs (cleanup sweeps, digest emails, external data sync) need more than `APScheduler` (single-process, dies with the API, no retry model) and more than `asyncio.create_task` (survives only for the current process lifespan, no durability, no operator visibility) but less than a full event sourcing pipeline. Celery Beat fills that gap: a crontab-style schedule evaluated by a single dedicated beat container, tasks queued to Redis, and one or more worker containers pulling and executing them independently of HTTP traffic.

This tool generates the entire scaffolding a real service requires so developers do not piece it together from the Celery docs: (a) `app/workers/celery_app.py` — a `create_celery_app()` factory that imports Celery **lazily** (inside the function body) so the FastAPI process boots cleanly on machines where the `celery` package is absent, reads broker and result-backend DSNs from `settings.CELERY_BROKER_URL` / `settings.CELERY_RESULT_BACKEND` (falling back to `settings.REDIS_URL`), and sets a module-level `celery_app` singleton for the Celery CLI to discover; (b) `app/workers/celery_tasks.py` — a task registry with three example tasks (`cleanup_expired`, `send_digest`, `sync_external`) that each return structured `dict` results and degrade gracefully when Celery is absent (no `ImportError` in test environments without a live broker); (c) `app/workers/celery_beat_schedule.py` — a `BEAT_SCHEDULE` dict using `crontab()` notation for three representative schedules (nightly cleanup at 02:00 UTC, weekly digest on Monday at 08:00 UTC, external sync every 30 minutes during business hours); (d) `app/api/routes/celery_status.py` — an authenticated `GET /celery/status` endpoint that inspects active workers via `celery.app.control.inspect` with a 2-second timeout so the endpoint stays responsive even with no workers; (e) `Dockerfile.celery-worker` and `Dockerfile.celery-beat` that both run as non-root `USER 1000` and invoke the respective Celery CLI commands.

Key design decisions: Celery runs as **separate processes** — `app/main.py` is never modified, enforcing clean separation between the HTTP tier and the task execution tier; the broker and result backend are always read from `settings.*` — no DSN is ever hard-coded; `CELERY_TASK_ALWAYS_EAGER=True` is the supported mechanism for synchronous test execution (tasks run inline, no broker required); `autodiscover_tasks` pointed at `app.workers.celery_tasks` means new task modules can be dropped in without editing the factory; the beat scheduler Dockerfile carries an explicit warning that only **one** instance should run at a time (duplicate beat instances fire duplicate tasks); the tool is idempotent — a second run detects the `celery_app` fingerprint in `app/workers/celery_app.py` and returns `status="no_op"` with zero file writes.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (T-17) |
| Files created | ≥ 6 | Workers pkg `__init__`, celery_app, tasks, beat_schedule, status route, two Dockerfiles — at minimum six distinct outputs (T-04) |
| Files modified | ≥ 2 | `app/core/config.py` (Celery settings) and `requirements.txt` (celery[redis]) — both must exist (T-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (T-07) |
| `GET /celery/status` response time | < 3 s | `inspect(timeout=2.0)` hard caps the broker round-trip; response assembles in < 100 ms after inspection returns |
| Worker pickup delay | < 1 s | Celery default polling interval is 500 ms |
| Task serialization format | JSON | Explicitly configured in `celery_app.py` via `task_serializer="json"`, `accept_content=["json"]` |
| Broker + backend DSN resolution | 0 hard-coded hosts | `create_celery_app()` always reads from `settings`; `localhost` must never appear in generated code |
| Beat container cold start | < 30 s | Slim Python 3.12 base + `pip install -r requirements.txt` |
| Worker container cold start | < 30 s | Identical base image and install step as beat |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no Celery integration
│   ├── core/
│   │   └── config.py        # Settings class, no CELERY_* fields
│   └── api/
│       └── routes/          # No celery_status.py
├── requirements.txt         # no celery
└── (no Dockerfile.celery-*)
```

All periodic work is either crammed into background tasks (which cannot survive a deploy), ad-hoc cron jobs on the host (not containerised, not retried), or simply absent. There is no operator endpoint to check whether scheduled work is running.

### 4.2 Celery application factory: AFTER

```python
# app/workers/celery_app.py
"""Celery application factory.

Celery is imported lazily so the FastAPI process can boot even if the
celery package is not installed.  The worker and beat processes import
this module directly, which triggers the real import.

Broker and result backend are read from ``app.core.config.settings``
so no DSN is ever hard-coded here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from celery import Celery  # pragma: no cover


def create_celery_app() -> "Celery":
    """Build and return a configured Celery application instance.

    Reads broker URL from ``settings.CELERY_BROKER_URL`` (falls back to
    ``settings.REDIS_URL``) and result backend from
    ``settings.CELERY_RESULT_BACKEND``.

    Task modules are discovered via ``autodiscover_tasks`` pointing at
    ``app.workers.celery_tasks`` so adding new task modules does not
    require editing this factory.

    Returns:
        A fully configured ``Celery`` application instance.
    """
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
```

### 4.3 Task registry module: AFTER

```python
# app/workers/celery_tasks.py
"""Celery task registry.

Tasks are discovered automatically by the Celery worker via
``autodiscover_tasks(["app.workers.celery_tasks"])``.

To add a new task:

1. Define a function decorated with ``@celery_app.task``.
2. The worker picks it up on the next restart.

Celery is imported lazily at the top of this module so that running
the FastAPI server without celery installed does not cause an
``ImportError``.
"""
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
    """Decorator that applies ``@celery_app.task`` when celery is available.

    Falls back to a no-op wrapper when celery is absent so the module
    can be imported in test environments without a running broker.

    Args:
        func: The task function to decorate.

    Returns:
        The decorated (or unchanged) function.
    """
    if _CELERY_AVAILABLE and celery_app is not None:
        return celery_app.task(bind=False)(func)
    return func


@_task
def cleanup_expired() -> dict[str, Any]:
    """Scheduled task: purge expired records and tokens.

    Designed to run periodically via the beat schedule (e.g. nightly).
    Replace the stub body with real cleanup logic.

    Returns:
        Dict with ``status`` and ``cleaned`` count.
    """
    logger.info("cleanup_expired: starting sweep")
    return {"status": "ok", "cleaned": 0}


@_task
def send_digest(user_id: str, digest_type: str = "weekly") -> dict[str, Any]:
    """Scheduled task: send a periodic digest email to a user.

    Args:
        user_id: UUID string of the target user.
        digest_type: Digest frequency label (e.g. ``weekly``, ``daily``).

    Returns:
        Dict with ``status``, ``user_id``, and ``digest_type``.
    """
    logger.info("send_digest: user=%s type=%s", user_id, digest_type)
    return {"status": "sent", "user_id": user_id, "digest_type": digest_type}


@_task
def sync_external(source: str = "default") -> dict[str, Any]:
    """Scheduled task: pull updates from an external data source.

    Args:
        source: Named data source to sync (e.g. ``"crm"``, ``"erp"``).

    Returns:
        Dict with ``status``, ``source``, and ``synced`` record count.
    """
    logger.info("sync_external: source=%s", source)
    return {"status": "ok", "source": source, "synced": 0}
```

### 4.4 Beat schedule configuration: AFTER

```python
# app/workers/celery_beat_schedule.py
"""Celery Beat schedule configuration.

``BEAT_SCHEDULE`` is consumed by ``create_celery_app()`` in
``app/workers/celery_app.py``.  Each entry maps a human-readable
schedule name to a dict with ``task``, ``schedule``, and optional
``args`` / ``kwargs``.

``crontab`` notation (minute, hour, day_of_week, day_of_month,
month_of_year) is used throughout for readability.
"""
from __future__ import annotations

try:
    from celery.schedules import crontab  # noqa: PLC0415
except ImportError:  # pragma: no cover — celery not installed
    crontab = None  # type: ignore[assignment, misc]


def _cron(**kwargs) -> object:  # type: ignore[return]
    """Return a crontab or a sentinel object when celery is absent.

    Args:
        **kwargs: Forwarded verbatim to ``crontab()``.

    Returns:
        A ``crontab`` instance, or ``None`` when celery is not installed.
    """
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
```

### 4.5 HTTP status route: AFTER

```python
# app/api/routes/celery_status.py
"""HTTP route for Celery worker health / active-task inspection.

Provides a single authenticated endpoint that operators and dashboards
can poll to verify that workers are alive and to see which tasks are
currently running.

Celery is imported lazily so this module loads cleanly without a
running broker.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/celery", tags=["celery"])


def _get_celery_app():
    """Return the module-level Celery app instance or raise 503.

    Returns:
        The ``Celery`` application instance.

    Raises:
        HTTPException(503): celery package not installed or app unavailable.
    """
    try:
        from app.workers.celery_app import celery_app  # noqa: PLC0415
        return celery_app
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery is not available",
        ) from exc


def _inspect_workers(app) -> dict:
    """Return active-task info from all reachable workers.

    Uses a short 2-second timeout so the endpoint stays responsive
    even when no workers are running.

    Args:
        app: The ``Celery`` application instance.

    Returns:
        Dict with ``active`` (per-worker active task lists) and
        ``workers`` (list of reachable worker names).
    """
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
    """Return active Celery worker and task information.

    Inspects all reachable workers and returns their active task lists.
    Requires authentication — task details must not be publicly visible.

    Raises:
        HTTPException(503): Celery package unavailable.
    """
    _ = current_user  # auth gate only
    app = _get_celery_app()
    info = _inspect_workers(app)
    return {
        "status": "ok" if info["workers"] else "no_workers",
        "workers": info["workers"],
        "active_tasks": info["active"],
    }
```

### 4.6 Dockerfile.celery-worker: AFTER

```dockerfile
# Dockerfile.celery-worker — Celery background task worker
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

CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info"]
```

### 4.7 Dockerfile.celery-beat: AFTER

```dockerfile
# Dockerfile.celery-beat — Celery Beat periodic task scheduler
# Run EXACTLY ONE instance of this container at a time.
# Running multiple beat instances causes duplicate task firing.
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

CMD ["celery", "-A", "app.workers.celery_app", "beat", "--loglevel=info"]
```

### 4.8 Config patch (settings injected inside `class Settings`): AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # --- Celery settings — added by add_celery_beat tool ---
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    CELERY_TASK_ALWAYS_EAGER: bool = False
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables. Appending at module level would create module-scope attributes the generated worker code cannot reach via `settings.*`.

### 4.9 Typical caller usage (after install)

```python
# Start worker (local, development):
# celery -A app.workers.celery_app worker --loglevel=info

# Start beat scheduler (local, development):
# celery -A app.workers.celery_app beat --loglevel=info

# Invoke a task directly (e.g., from a FastAPI route):
from app.workers.celery_tasks import send_digest

send_digest.delay(user_id="abc-123", digest_type="weekly")
# Returns AsyncResult; caller can poll .status or .get(timeout=5)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_celery_beat` pre-flight checks `"celery_app" in app/workers/celery_app.py` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero files** | Returns success + notes before any filesystem write when `inp.dry_run` is truthy; no `Path.write_text` call is reached |
| QS-3 | **Every generated `.py` file AST-parses** | `_assert_parses` runs `ast.parse` on each created `.py` file; raises `SyntaxError` on failure before returning success |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers in `celery_tasks.py`, `celery_app.py`, `celery_beat_schedule.py`, `celery_status.py` stay small by construction; asserted by AST walk in test harness |
| QS-5 | **Broker DSN is never hard-coded** | `create_celery_app()` reads `settings.CELERY_BROKER_URL or settings.REDIS_URL`; `localhost` must not appear in generated files |
| QS-6 | **Celery is imported lazily in the app factory** | `from celery import Celery` appears INSIDE `create_celery_app()` body, never at module level — FastAPI boots without celery installed |
| QS-7 | **`app/main.py` is never modified** | Celery runs as a separate process; the tool does not touch `app/main.py`; `main.py` must NOT appear in `files_modified` |
| QS-8 | **HTTP status route requires authentication** | `get_celery_status` declares `current_user: CurrentUser` from `app.api.deps` |
| QS-9 | **Both Dockerfiles run as non-root** | `Dockerfile.celery-worker` and `Dockerfile.celery-beat` both declare `USER 1000` before `CMD` |
| QS-10 | **`CELERY_*` fields live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent so pydantic-settings binds env vars |
| QS-11 | **Task module imports Celery lazily** | `celery_tasks.py` wraps the Celery import in `try/except` so the module loads in test environments without a broker |
| QS-12 | **Beat schedule uses only `crontab` from `celery.schedules`** | `celery_beat_schedule.py` wraps `crontab` in a guard and provides a sentinel when Celery is absent |
| QS-13 | **`celery[redis]>=5.4.0` is added to requirements** | `_patch_requirements` appends the pin only when absent; existing `celery` line is preserved |
| QS-14 | **Workers package has `__init__.py`** | `app/workers/__init__.py` is created if missing; package is importable without explicit `sys.path` manipulation |
| QS-15 | **Prerequisites validated before write** | `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` runs first; returns `status="error"` with actionable notes on failure |
| QS-16 | **Tool records execution time** | `ToolResult.execution_time_ms` is computed via `_elapsed_ms(start)` on every return path |
| QS-17 | **`next_steps` mention `celery worker` and `celery beat`** | `next_steps` list includes commands for starting both the worker and the beat scheduler |
| QS-18 | **Second run keeps project parseable** | Idempotent no-op path does not corrupt any file; all `.py` remain AST-valid after two invocations |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_celery_beat.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and `r2.files_created == []` and `r2.files_modified == []` | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree; `result.files_created == []` and `result.files_modified == []` | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 6 new files | `len(result.files_created) >= 6` and each path exists on disk | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists on disk | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER` exist inside `class Settings` body with 4-space indent | String scan + indent check on line containing `CELERY_BROKER_URL` | T-08 (`test_config_fields_patched`) |
| CC-09 | `celery[redis]>=` present in `requirements.txt` | `"celery" in content` of `requirements.txt` | T-09 (`test_requirements_patched`) |
| CC-10 | `app/workers/celery_app.py` exists and contains `celery_app` and `create_celery_app` | File exists + both substrings in content | T-10 (`test_celery_app_created`) |
| CC-11 | `app/workers/celery_tasks.py` exists with `cleanup_expired`, `send_digest`, `sync_external` | File exists + three task name substrings in content | T-11 (`test_tasks_module_created`) |
| CC-12 | `app/workers/celery_beat_schedule.py` exists with `BEAT_SCHEDULE` and `crontab` reference | File exists + both substrings in content | T-12 (`test_beat_schedule_created`) |
| CC-13 | `app/api/routes/celery_status.py` exists with `get_celery_status` and `/celery` prefix | File exists + `"get_celery_status"` and `"/celery"` in content | T-13 (`test_status_route_created`) |
| CC-14 | `Dockerfile.celery-worker` exists and runs as non-root (`USER` directive) with celery reference | File exists + `"USER"` and `"celery"` (case-insensitive) in content | T-14 (`test_dockerfile_worker_created`) |
| CC-15 | `Dockerfile.celery-beat` exists and runs as non-root with beat reference | File exists + `"USER"` and `"beat"` (case-insensitive) in content | T-15 (`test_dockerfile_beat_created`) |
| CC-16 | `celery_app.py` imports Celery lazily (inside function body, not module level) | `from celery import Celery` appears indented (starts with 4+ spaces), not at column 0 | T-16 (`test_lazy_celery_import`) |
| CC-17 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-17 (`test_execution_time_recorded`) |
| CC-18 | `next_steps` includes guidance for starting worker and beat (≥ 3 items, mentions `celery` and `worker` or `beat`) | `len(result.next_steps) >= 3`; lowercased join contains `"celery"` and (`"worker"` or `"beat"`) | T-18 (`test_next_steps_present`) |
| CC-19 | Running tool twice leaves project AST-parseable | `ast.parse` over all `.py` files after two invocations | T-19 (`test_idempotent_project_still_parses`) |
| CC-20 | `celery_app.py` reads broker from `settings` and does not hard-code `localhost` | `"settings" in content` and `"localhost" not in content` | T-20 (`test_celery_app_uses_settings_broker`) |
| CC-21 | `app/main.py` is NOT modified by the tool | `before == after` for `app/main.py`; `"main.py" not in files_modified names` | T-21 (`test_main_py_not_modified`) |
| CC-22 | `app/workers/__init__.py` exists after tool runs | File exists | T-22 (`test_workers_package_init_created`) |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_celery_beat.py`
- [ ] `add_celery_beat.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_celery_beat.py` detects `"celery_app"` fingerprint in `app/workers/celery_app.py` and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified` and no filesystem writes
- [ ] `create_celery_app()` reads broker from `settings.CELERY_BROKER_URL or settings.REDIS_URL` — never hard-coded
- [ ] `from celery import Celery` appears inside `create_celery_app()` body — lazy import pattern enforced
- [ ] `app/main.py` is never modified — Celery process is independent of the HTTP tier
- [ ] Both Dockerfiles declare `USER 1000` before `CMD`
- [ ] `BEAT_SCHEDULE` contains three entries using `crontab()` notation
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so fields land inside `Settings` class body
- [ ] `_patch_requirements` adds `celery[redis]>=5.4.0` when absent
- [ ] `get_celery_status` route declares `current_user: CurrentUser` auth gate
- [ ] `_inspect_workers` uses `inspect(timeout=2.0)` to prevent indefinite blocking
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-BEAT-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"celery_app" in celery_app_file.read_text()` short-circuits to `status="no_op"` | T-02, T-19 |
| INV-BEAT-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any `Path.write_text` call | T-03 |
| INV-BEAT-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: if .py: _assert_parses(p)` | T-06, T-19 |
| INV-BEAT-04 | Broker DSN MUST be read from `settings.*` — never invented or hard-coded | `create_celery_app()` emits `getattr(settings, "CELERY_BROKER_URL", None) or str(settings.REDIS_URL)` | T-20 |
| INV-BEAT-05 | `app/main.py` MUST NOT be modified — Celery runs as a separate process | Tool does not call any write helper against `main.py`; `files_modified` list never contains `main.py` | T-21 |
| INV-BEAT-06 | HTTP status route MUST require authentication | `get_celery_status` has `current_user: CurrentUser` as required parameter | T-13 |
| INV-BEAT-07 | `CELERY_*` settings MUST live inside `class Settings` body (pydantic-settings binding) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-08 |
| INV-BEAT-08 | Both worker and beat Dockerfiles MUST run as non-root (`USER 1000`) | Both `_write_dockerfile_worker` and `_write_dockerfile_beat` emit `USER 1000` before `CMD` | T-14, T-15 |
| INV-BEAT-09 | Celery MUST be imported LAZILY inside `create_celery_app()` — not at module level | `from celery import Celery` line appears with 4-space indent (inside function body) | T-16 |
| INV-BEAT-10 | Task module MUST contain `cleanup_expired`, `send_digest`, `sync_external` | `_write_celery_tasks` emits all three decorated task functions | T-11 |
| INV-BEAT-11 | `BEAT_SCHEDULE` MUST use `crontab()` entries from `celery.schedules` | `_write_beat_schedule` emits three schedule entries using `_cron()` wrapper | T-12 |
| INV-BEAT-12 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-17 |
| INV-BEAT-13 | `next_steps` MUST reference `celery worker` and `celery beat` so operators know how to start both processes | Hard-coded strings in the `success` branch of `add_celery_beat` | T-18 |
| INV-BEAT-14 | Beat container warning about singleton MUST appear in `Dockerfile.celery-beat` | Dockerfile comment `Run EXACTLY ONE instance` is emitted by `_write_dockerfile_beat` | T-15 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install Celery Beat into a clean FastAPI project**
- **As a** backend engineer who needs periodic background jobs
- **I want** to run one tool call and get the full Celery Beat scaffolding
- **So that** I stop assembling Celery boilerplate from documentation fragments
- **Given:** A FastAPI project with `app/core/config.py` and `requirements.txt`
- **When:** `add_celery_beat(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-BEAT-01)
  - `files_created` contains ≥ 6 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project or duplicate files
- **Given:** Project where `app/workers/celery_app.py` already contains `celery_app`
- **When:** `add_celery_beat(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-BEAT-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-BEAT-03)
  - Verified by T-02, T-19

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing to a shared codebase
- **Given:** Fresh FastAPI fixture project
- **When:** `add_celery_beat(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-BEAT-02)
  - Verified by T-03

**US-04: FastAPI process boots without celery installed**
- **As a** developer on a machine that does not have `celery` in the virtualenv
- **I want** `uvicorn app.main:app` to work even before `pip install celery`
- **So that** I can test the HTTP tier independently of the task tier
- **Given:** `create_celery_app()` uses a lazy import pattern
- **When:** FastAPI process boots
- **Then:**
  - `from celery import Celery` is inside the function body — not at module level (INV-BEAT-09)
  - `celery_tasks.py` wraps the Celery import in `try/except` — no `ImportError` at module scope
  - Verified by T-16

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it in a PR
- **Given:** Tool just emitted `celery_app.py`, `celery_tasks.py`, `celery_beat_schedule.py`, `celery_status.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

### 9.2 Worker and beat runtime (US-06 .. US-10)

**US-06: Start the worker from a Docker container**
- **As an** ops engineer
- **I want** a one-line container command
- **So that** I can scale workers with `kubectl scale deployment celery-worker`
- **Given:** `Dockerfile.celery-worker` generated
- **When:** `docker build -f Dockerfile.celery-worker -t worker . && docker run --env-file .env worker`
- **Then:**
  - Container runs `celery -A app.workers.celery_app worker --loglevel=info` as `USER 1000` (INV-BEAT-08)
  - Verified by T-14

**US-07: Start the beat scheduler from a Docker container**
- **As an** ops engineer
- **I want** a dedicated beat container that runs as a singleton
- **So that** scheduled tasks do not fire twice
- **Given:** `Dockerfile.celery-beat` generated
- **When:** I run exactly one beat container
- **Then:**
  - Container runs `celery -A app.workers.celery_app beat --loglevel=info` as `USER 1000` (INV-BEAT-08)
  - Dockerfile comment warns against multiple instances (INV-BEAT-14)
  - Verified by T-15

**US-08: Add a new periodic task**
- **As a** developer adding a new scheduled job
- **I want** to write a function and register it in the beat schedule
- **So that** no worker code file needs to change
- **Given:** `app/workers/celery_tasks.py` with `_task` decorator helper
- **When:** I add `@_task def my_task(): ...` and a `BEAT_SCHEDULE` entry in `celery_beat_schedule.py`
- **Then:**
  - `autodiscover_tasks(["app.workers.celery_tasks"])` picks it up
  - No factory file changes required
  - Verified by T-11, T-12

**US-09: Inspect running workers via HTTP**
- **As an** operations dashboard
- **I want** `GET /celery/status` to show live worker state
- **So that** I can confirm workers are connected before a deployment
- **Given:** Worker containers are running and `current_user` is authenticated
- **When:** Authenticated request hits `GET /celery/status`
- **Then:**
  - `_inspect_workers` calls `app.control.inspect(timeout=2.0)`
  - Response is `{"status": "ok" | "no_workers", "workers": [...], "active_tasks": {...}}`
  - Verified by T-13

**US-10: Broker outage does not crash the status endpoint**
- **As a** resilient ops team
- **I want** `GET /celery/status` to return `no_workers` instead of 500 when Redis is down
- **So that** my monitoring dashboard does not alert on an API error
- **Given:** `_inspect_workers` wraps `inspector.active()` in `try/except`
- **When:** Broker is unreachable
- **Then:**
  - Exception is caught; returns `{"active": {}, "workers": []}`
  - Route returns `{"status": "no_workers", ...}` with HTTP 200
  - Verified by T-13 (inspecting the generated file structure)

### 9.3 HTTP status route (US-11 .. US-15)

**US-11: Unauthenticated access is denied**
- **As a** security reviewer
- **I want** no anonymous inspection of running tasks
- **So that** internal task names and arguments are not leaked
- **Given:** Route declares `current_user: CurrentUser`
- **When:** Anonymous request hits `GET /celery/status`
- **Then:**
  - FastAPI DI resolves `CurrentUser`; missing auth → 401
  - Verified by route signature (INV-BEAT-06)

**US-12: 503 when Celery package is unavailable**
- **As a** developer deploying to a machine without `celery` installed
- **I want** a clear 503 rather than a `ModuleNotFoundError` traceback
- **So that** the error is actionable
- **Given:** `_get_celery_app()` wraps the import in `try/except`
- **When:** `from app.workers.celery_app import celery_app` fails
- **Then:**
  - `HTTPException(503, "Celery is not available")` is raised
  - Verified by `_get_celery_app` structure in generated file

**US-13: Response body is structured JSON**
- **As a** dashboard developer
- **I want** `status`, `workers`, `active_tasks` fields in every response
- **So that** I can render a worker-health widget without fragile parsing
- **Given:** `get_celery_status` returns `dict`
- **When:** Workers are running
- **Then:**
  - Response contains `"status": "ok"`, `"workers": [<names>]`, `"active_tasks": {}`
  - When no workers: `"status": "no_workers"`, `"workers": []`

**US-14: Inspect timeout prevents endpoint from hanging**
- **As an** SRE with a 5-second health-check timeout
- **I want** `GET /celery/status` to complete within 3 s regardless of broker state
- **So that** the health-check does not time out itself
- **Given:** `_inspect_workers` calls `inspect(timeout=2.0)`
- **When:** Broker is slow or unresponsive
- **Then:**
  - Inspection returns in ≤ 2.0 s by design
  - `GET /celery/status` total response time < 3 s (SLO)

**US-15: Route prefix is `/celery` with tag `celery`**
- **As an** API documentation reader
- **I want** all Celery endpoints grouped under `/celery` in the Swagger UI
- **So that** I can find them without searching
- **Given:** `router = APIRouter(prefix="/celery", tags=["celery"])`
- **When:** Router is included in the main API router
- **Then:**
  - `GET /api/v1/celery/status` is the full path
  - Swagger UI groups it under `celery`

### 9.4 Configuration and operator experience (US-16 .. US-20)

**US-16: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `CELERY_BROKER_URL=redis://redis:6379/0` in `.env` to take effect
- **So that** I do not rebuild images for DSN changes
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `CELERY_BROKER_URL` inside `class Settings` picks up env var (INV-BEAT-07)
  - Fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
  - Verified by T-08

**US-17: `requirements.txt` gets the new dependency**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `celery[redis]>=5.4.0` to appear
- **So that** the worker and beat processes can import Celery
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains `celery` (idempotent: only appended if absent)
  - Verified by T-09

**US-18: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include worker and beat start commands
- **So that** I do not have to remember the Celery CLI syntax
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `celery` worker and beat guidance (≥ 3 items, mentions `worker` or `beat`)
  - Verified by T-18 (INV-BEAT-13)

**US-19: CELERY_TASK_ALWAYS_EAGER enables synchronous test mode**
- **As a** test engineer
- **I want** to set `CELERY_TASK_ALWAYS_EAGER=True` in the test environment
- **So that** tasks execute inline without a running broker
- **Given:** `create_celery_app()` reads `CELERY_TASK_ALWAYS_EAGER` from settings
- **When:** `CELERY_TASK_ALWAYS_EAGER=True` is set
- **Then:**
  - `task_always_eager=True` is passed to `app.config_from_object`
  - Tasks run synchronously; no Redis connection required in tests

**US-20: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **So that** the build does not blow the step budget
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-BEAT-12)
  - Verified by T-17

---

## 10. Test Plan

All 22 tests live in `adapt/extend/infrastructure/test_add_celery_beat.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `celery_t01` | `add_celery_beat(ToolInput(project_dir))` | `result.status == "success"` (INV-BEAT-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `celery_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; `r2.files_created == []`; `r2.files_modified == []` (INV-BEAT-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `celery_t03`; snapshot all `.py` | `add_celery_beat(ToolInput(dry_run=True))` | `status == "success"`; empty create/modify lists; byte-identical filesystem (INV-BEAT-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `celery_t04` | Run tool | `len(files_created) >= 6`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `celery_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-09)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `celery_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-BEAT-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `celery_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `celery_t08`; run tool | Read `app/core/config.py` | Contains `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER`; `CELERY_BROKER_URL` line starts with 4-space indent (INV-BEAT-07, CC-08) |
| T-09 | `test_requirements_patched` | Fixture `celery_t09`; run tool | Read `requirements.txt` | Contains `"celery"` (CC-09) |

### 10.3 Category C — Domain-specific modules (T-10 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-10 | `test_celery_app_created` | Fixture `celery_t10`; run tool | Read `app/workers/celery_app.py` | File exists; contains `"celery_app"` and `"create_celery_app"` (INV-BEAT-09, CC-10) |
| T-11 | `test_tasks_module_created` | Fixture `celery_t11`; run tool | Read `app/workers/celery_tasks.py` | Contains `cleanup_expired`, `send_digest`, `sync_external` (INV-BEAT-10, CC-11) |
| T-12 | `test_beat_schedule_created` | Fixture `celery_t12`; run tool | Read `app/workers/celery_beat_schedule.py` | Contains `BEAT_SCHEDULE` and `crontab` (INV-BEAT-11, CC-12) |
| T-13 | `test_status_route_created` | Fixture `celery_t13`; run tool | Read `app/api/routes/celery_status.py` | Contains `get_celery_status` and `"/celery"` (INV-BEAT-06, CC-13) |
| T-14 | `test_dockerfile_worker_created` | Fixture `celery_t14`; run tool | Read `Dockerfile.celery-worker` | File exists; contains `"USER"` and `"celery"` (case-insensitive) (INV-BEAT-08, CC-14) |
| T-15 | `test_dockerfile_beat_created` | Fixture `celery_t15`; run tool | Read `Dockerfile.celery-beat` | File exists; contains `"USER"` and `"beat"` (case-insensitive) (INV-BEAT-08, INV-BEAT-14, CC-15) |
| T-16 | `test_lazy_celery_import` | Fixture `celery_t16`; run tool | Read `app/workers/celery_app.py` and check each line containing Celery import | `from celery import Celery` starts with `"    "` (4-space indent), never at column 0 (INV-BEAT-09, CC-16) |

### 10.4 Category D — Meta (T-17 .. T-22)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-17 | `test_execution_time_recorded` | Fixture `celery_t17`; run tool | Read `result.execution_time_ms` | `> 0` (INV-BEAT-12, CC-17) |
| T-18 | `test_next_steps_present` | Fixture `celery_t18`; run tool | Inspect `result.next_steps` | `len >= 3`; lowercased join contains `"celery"` and `"worker"` or `"beat"` (INV-BEAT-13, CC-18) |
| T-19 | `test_idempotent_project_still_parses` | Fixture `celery_t19`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-BEAT-01, INV-BEAT-03, CC-19) |
| T-20 | `test_celery_app_uses_settings_broker` | Fixture `celery_t20`; run tool | Read `app/workers/celery_app.py` | `"settings" in content`; `"localhost" not in content` (INV-BEAT-04, CC-20) |
| T-21 | `test_main_py_not_modified` | Fixture `celery_t21`; snapshot `main.py` | Run tool | `before == after` for `main.py`; `"main.py" not in files_modified names` (INV-BEAT-05, CC-21) |
| T-22 | `test_workers_package_init_created` | Fixture `celery_t22`; run tool | Check `app/workers/__init__.py` | File exists (CC-22) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_celery_beat.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_celery_beat.py
```

Target: 22/22 passed, 0 failed. The standalone runner prints `TOOL-059 add_celery_beat: 22 passed, 0 failed`.

---

## 11. Interaction Matrix

How `add_celery_beat` composes with other SKILL-001 tools. Tool IDs below match the `specs/` directory.

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_email_templates` (TOOL-055) | No | ✅ Compatible | `send_digest` task in `TASK_REGISTRY` is the natural invocation point for template-rendered digest emails; the task body calls `app/email/service.py` |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Stripe webhook handlers can return 200 immediately and enqueue reconciliation to `sync_external` or a custom task via `.delay()` |
| `add_outbox_pattern` (TOOL-023) | Yes | ✅ Compatible — outbox runs FIRST | Outbox relay can trigger tasks via `.delay()` after publishing events; beat can trigger the relay sweep on a schedule |
| `add_event_driven` (TOOL-046) | No | ✅ Compatible | Task completions can emit domain events via the event bus; `cleanup_expired` can fire a `data.cleaned` event after sweep |
| `add_webhook_sender` (TOOL-015) | Yes | ✅ Compatible — webhook sender runs AFTER | Failed deliveries can be re-queued as celery tasks; `sync_external` pattern applies to webhook retry loops |
| `add_webhook_receiver` (TOOL-016) | No | ✅ Compatible | Incoming webhook routes can call `.delay()` on heavy-processing tasks and return 202 to the remote sender |
| `add_cache_layer` (TOOL-021) | No | ✅ Compatible | Uses the same `settings.REDIS_URL`; using a separate Redis logical DB (e.g. `/1` for broker, `/0` for cache) prevents eviction of queued tasks |
| `add_circuit_breaker` (TOOL-022) | No | ✅ Compatible | `sync_external` tasks that call flaky third-party APIs should wrap calls in the circuit breaker; Celery's `max_retries` handles task-level retry |
| `add_multi_tenancy` (TOOL-008) | No | ⚠️ Caveat | Task arguments carrying `tenant_id` must be validated inside each task body; Celery does not natively scope task execution by tenant |
| `add_rbac` (TOOL-012) | No | ✅ Compatible | `GET /celery/status` can be upgraded to require a `celery:read` permission scope; current version only enforces `CurrentUser` authentication |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | API keys are first-class `CurrentUser` identities; can call the status endpoint with the same `CurrentUser` dependency |
| `add_oauth2_provider` (TOOL-011) | No | ✅ Compatible | OAuth2 JWTs work via the same `CurrentUser` dependency; no changes required |
| `add_audit_log` (TOOL-005) | No | ⚠️ Caveat — audit should wrap task lifecycle | `cleanup_expired` and `sync_external` task bodies should emit audit entries when they modify data; the audit module should not introspect Celery internals |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | `cleanup_expired` task specifically targets expired / soft-deleted rows; ensure the sweep uses the correct filter (`deleted_at IS NOT NULL AND deleted_at < NOW() - INTERVAL '30 days'`) |
| `add_long_running_task` (TOOL-020) | No | ⚠️ Caveat | Both tools generate `app/workers/` content; `add_celery_beat` must run FIRST; `add_long_running_task` must be adapted to use `celery_tasks.py` instead of creating a parallel worker module |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | Admin panel can expose a read-only view of beat schedule entries and worker status via the `/celery/status` API |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | If task results are persisted to a relational table, `list` endpoints can apply cursor pagination by `created_at DESC` |
| `add_sse` (TOOL-014) | No | ✅ Compatible | SSE endpoint can push `task.completed` events to clients based on worker signals, replacing polling `GET /celery/status` for real-time dashboards |
| `add_feature_flags` (TOOL-009) | No | ✅ Compatible | Task handlers can check feature flags before executing heavy work, enabling gradual rollout of new scheduled operations |
| `add_rate_limiting` (TOOL-057) | No | ✅ Compatible | Rate-limit task-triggering HTTP endpoints upstream; do not rate-limit `GET /celery/status` (ops tools need unrestricted polling) |

**Conflicts:** `add_celery_beat` (TOOL-059) and `add_scheduled_tasks` (TOOL-058) both install scheduled task infrastructure; installing both into the same project creates duplicate `app/workers/` content. Use one or the other per project. `add_celery_beat` is the choice when you need separate worker and beat containers with Redis broker/backend; `add_scheduled_tasks` is the choice for in-process APScheduler-based scheduling.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  requirements.txt

rm -rf \
  app/workers/ \
  app/api/routes/celery_status.py \
  Dockerfile.celery-worker \
  Dockerfile.celery-beat
```

### 12.2 No database rollback required

`add_celery_beat` does not create any database tables or Alembic migrations. There is no schema rollback step.

### 12.3 Redis cleanup (optional)

Celery uses Redis keys prefixed with `celery` (tasks) and `_kombu` (broker transport). After rollback these keys expire naturally according to the Celery result TTL. To purge immediately:

```bash
redis-cli --scan --pattern "celery*" | xargs redis-cli del
redis-cli --scan --pattern "_kombu*" | xargs redis-cli del
```

Only run this if you are certain all workers have been stopped and no tasks are in-flight.

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

Because `_assert_parses` runs at the end of the tool's success path, a mid-execution failure may leave partially-written files. The tool writes files one at a time; `git checkout HEAD --` on modified paths plus `rm` on newly-created paths restores the project.

### 12.5 Emergency: Redis outage (workers already deployed)

1. Stop all Celery workers: `docker ps | grep celery | awk '{print $1}' | xargs docker stop`
2. Stop the beat scheduler: `docker ps | grep celery-beat | awk '{print $1}' | xargs docker stop`
3. The FastAPI API tier is unaffected — `app/main.py` was never modified (INV-BEAT-05).
4. The `/celery/status` endpoint will return `{"status": "no_workers", ...}` with HTTP 200 — it will not crash.
5. On Redis restore, restart workers and beat containers in order: workers first, beat second.

### 12.6 Uninstall validator

After rollback, verify:

```bash
test ! -d app/workers || (echo "app/workers still present" && exit 1)
test ! -f app/api/routes/celery_status.py || (echo "celery_status.py still present" && exit 1)
test ! -f Dockerfile.celery-worker || (echo "Dockerfile.celery-worker still present" && exit 1)
test ! -f Dockerfile.celery-beat || (echo "Dockerfile.celery-beat still present" && exit 1)
grep -q "CELERY_BROKER_URL" app/core/config.py && echo "config still patched" && exit 1
grep -q "celery" requirements.txt && echo "requirements.txt still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing prerequisites (`CONFIG_SETTINGS` or `REQUIREMENTS_TXT`) | `ensure_prerequisites` returns errors → tool returns `status="error"` with list of missing prereqs and hint to run `fastapi_generate_project` first |
| EC-03 | Tool runs on a project with `app/workers/celery_app.py` already containing `celery_app` | Early return `status="no_op"` with note `"celery_app already present — Celery Beat is already installed, skipped."` — zero file writes |
| EC-04 | Tool runs with `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-BEAT-02) |
| EC-05 | `app/core/config.py` already contains `CELERY_BROKER_URL` | `_patch_config` early-returns (`"CELERY_BROKER_URL" in src` check); no duplicate block appended |
| EC-06 | `app/core/config.py` lacks the `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | `_patch_config` falls back to inserting before `settings = Settings()`; if also missing, appends at EOF (still valid Python, fields land at module scope) |
| EC-07 | `requirements.txt` already contains `celery` | `_patch_requirements` early-returns (`"celery" in src` check); no duplicate line appended; existing pin is preserved |
| EC-08 | `Dockerfile.celery-worker` already exists | `_write_dockerfile_worker` is guarded by `if not dockerfile_worker.exists():`; file is not overwritten |
| EC-09 | `Dockerfile.celery-beat` already exists | `_write_dockerfile_beat` is guarded by `if not dockerfile_beat.exists():`; file is not overwritten |
| EC-10 | `app/api/routes/` directory does not exist | `_write_status_route` calls `routes_dir.mkdir(parents=True, exist_ok=True)` before writing — directory is created |
| EC-11 | `app/workers/` directory does not exist | `_write_celery_app` calls `dest.parent.mkdir(parents=True, exist_ok=True)` — all intermediate directories are created |
| EC-12 | `app/workers/__init__.py` already exists | `if not workers_init.exists():` guard prevents overwriting; file is not recreated or reported in `files_created` again |
| EC-13 | `app/core/config.py` does not exist | `if config_file.exists():` guard skips the patch step silently; `files_modified` does not include `config.py` |
| EC-14 | `requirements.txt` does not exist | `if requirements_file.exists():` guard skips the patch step silently; dependency must be added manually |
| EC-15 | Generated `celery_app.py` fails `ast.parse` | `_assert_parses` raises `SyntaxError` with the file path; caller sees traceback; partial files remain on disk (use rollback 12.4) |
| EC-16 | `celery[redis]` pin already present but as `celery>=5.0.0` (without extras) | `_patch_requirements` checks `"celery" in src`; the existing `celery` pin satisfies the check and no duplicate is added — operator must manually add `[redis]` extra if missing |
| EC-17 | Beat schedule `crontab` import fails because celery is absent at import time | `celery_beat_schedule.py` wraps `from celery.schedules import crontab` in `try/except ImportError`; `BEAT_SCHEDULE` values are `None` sentinels; module loads without error |
| EC-18 | Very small fixture project with no `app/api/` tree | `routes_dir.mkdir(parents=True, exist_ok=True)` creates the full path; `celery_status.py` is written successfully |
| EC-19 | Worker container runs multiple beat instances (operator error) | Dockerfile comment warns `Run EXACTLY ONE instance of this container at a time`; the tool cannot enforce singleton execution — this is an operator responsibility |
| EC-20 | Redis broker URL contains credentials (e.g. `redis://:password@host:6379/0`) | `settings.CELERY_BROKER_URL` is read at factory call time; no DSN appears in generated files; credentials are never logged by the tool |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 22 Completeness Criteria verified via `test_add_celery_beat.py` passing
2. ✅ `test_add_celery_beat.py` reports `22 passed, 0 failed` via both pytest and standalone runner
3. ✅ Tool execution time < 5 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-BEAT-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-BEAT-02)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-BEAT-03)
7. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
8. ✅ `CELERY_*` settings live inside `class Settings` body with 4-space indentation (INV-BEAT-07)
9. ✅ `create_celery_app()` reads broker from `settings.*` — no hard-coded `localhost` or DSN (INV-BEAT-04)
10. ✅ `app/main.py` is never modified — Celery runs as a completely separate process (INV-BEAT-05)
11. ✅ `GET /celery/status` declares `current_user: CurrentUser` (INV-BEAT-06)
12. ✅ Both Dockerfiles run as non-root `USER 1000` (INV-BEAT-08)
13. ✅ `from celery import Celery` appears inside `create_celery_app()` body, not at module level (INV-BEAT-09)
14. ✅ `BEAT_SCHEDULE` contains three entries with `crontab()` scheduling (INV-BEAT-11)
15. ✅ `next_steps` includes worker and beat start commands (INV-BEAT-13)
16. ✅ Developer successfully builds both Dockerfiles, starts worker and beat, verifies `GET /celery/status` returns `"ok"` with at least one worker listed

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` passes; auto-scaffold if `not inp.dry_run`
- [ ] `app/workers/celery_app.py` does NOT contain `"celery_app"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Workers package

- [ ] `mkdir -p app/workers`
- [ ] Write `app/workers/__init__.py` with `"""Celery workers sub-package."""` if missing
- [ ] Write `app/workers/celery_app.py` via `_write_celery_app` (`create_celery_app`, `celery_app` singleton)
- [ ] Write `app/workers/celery_tasks.py` via `_write_celery_tasks` (`_task` decorator, 3 example tasks)
- [ ] Write `app/workers/celery_beat_schedule.py` via `_write_beat_schedule` (`_cron` wrapper, `BEAT_SCHEDULE` with 3 entries)

### 15.3 HTTP status route

- [ ] `mkdir -p app/api/routes`
- [ ] Write `app/api/routes/celery_status.py` via `_write_status_route`
- [ ] Route prefix is `/celery`, tag is `"celery"`
- [ ] `_get_celery_app()` wraps import in `try/except`, raises 503 on failure
- [ ] `_inspect_workers(app)` calls `inspect(timeout=2.0)`, catches all exceptions, returns empty dict on failure
- [ ] `get_celery_status` declares `current_user: CurrentUser` (auth gate)

### 15.4 Dockerfiles

- [ ] Write `Dockerfile.celery-worker` if not already present
  - [ ] `FROM python:3.12-slim`
  - [ ] `PYTHONUNBUFFERED=1` + `PYTHONDONTWRITEBYTECODE=1`
  - [ ] `COPY requirements.txt` then `pip install --no-cache-dir`
  - [ ] `COPY app/ ./app/`
  - [ ] `USER 1000`
  - [ ] `CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info"]`
- [ ] Write `Dockerfile.celery-beat` if not already present
  - [ ] Same base and install steps as worker
  - [ ] Comment: `Run EXACTLY ONE instance of this container at a time`
  - [ ] `USER 1000`
  - [ ] `CMD ["celery", "-A", "app.workers.celery_app", "beat", "--loglevel=info"]`

### 15.5 Config patch

- [ ] Early-return if `"CELERY_BROKER_URL" in src`
- [ ] Block emits `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.6 Requirements patch

- [ ] Early-return if `"celery" in src`
- [ ] Append `celery[redis]>=5.4.0\n` with trailing newline handling
- [ ] Preserve existing content and trailing newline

### 15.7 Validation

- [ ] Loop over `files_created`; for every `.py` call `_assert_parses(p)`
- [ ] `_assert_parses` raises `SyntaxError` with file path on failure
- [ ] No validation run on Dockerfiles (non-Python)

### 15.8 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain: separate process model, broker/backend from settings, `CELERY_TASK_ALWAYS_EAGER` for tests, non-root containers
- [ ] `next_steps` contain: env var setup, worker Docker build+run, beat Docker build+run, local CLI alternatives, `/celery/status` verification, beat schedule customisation path

### 15.9 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists all emitted files and key design decisions
- [ ] `add_celery_beat` docstring documents `inp` parameter and all return fields

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/workers/__init__.py",
    "/tmp/fixture/app/workers/celery_app.py",
    "/tmp/fixture/app/workers/celery_tasks.py",
    "/tmp/fixture/app/workers/celery_beat_schedule.py",
    "/tmp/fixture/app/api/routes/celery_status.py",
    "/tmp/fixture/Dockerfile.celery-worker",
    "/tmp/fixture/Dockerfile.celery-beat"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "Celery Beat added: celery_app factory, task registry (3 tasks),",
    "beat schedule (crontab-based), GET /celery/status HTTP route.",
    "Celery runs as a SEPARATE process — app/main.py is not modified.",
    "Broker and result backend read from settings.CELERY_BROKER_URL / CELERY_RESULT_BACKEND (default: REDIS_URL).",
    "CELERY_TASK_ALWAYS_EAGER=False by default; set to True in test env.",
    "Dockerfile.celery-worker and Dockerfile.celery-beat run as non-root USER 1000."
  ],
  "next_steps": [
    "Set CELERY_BROKER_URL and CELERY_RESULT_BACKEND in .env (or leave unset to inherit REDIS_URL).",
    "Start the worker: docker build -f Dockerfile.celery-worker -t myapp-celery-worker . && docker run --rm --env-file .env myapp-celery-worker",
    "Start the beat scheduler: docker build -f Dockerfile.celery-beat -t myapp-celery-beat . && docker run --rm --env-file .env myapp-celery-beat",
    "Or locally: celery -A app.workers.celery_app worker --loglevel=info",
    "           celery -A app.workers.celery_app beat --loglevel=info",
    "Verify: inspect active tasks via GET /celery/status (requires auth).",
    "Customize beat schedule in app/workers/celery_beat_schedule.py."
  ],
  "execution_time_ms": 98
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "celery_app already present — Celery Beat is already installed, skipped."
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
    "[dry_run] Would create app/workers/ package (celery_app.py, celery_tasks.py,",
    "         celery_beat_schedule.py), GET /celery/status HTTP route,",
    "         Dockerfile.celery-worker, Dockerfile.celery-beat.",
    "[dry_run] Would patch app/core/config.py with CELERY_BROKER_URL,",
    "         CELERY_RESULT_BACKEND, CELERY_TASK_ALWAYS_EAGER.",
    "[dry_run] Would add celery[redis]>=5.4.0 to requirements.txt.",
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
