"""TOOL-020: add_long_running_task — durable async task endpoints for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitives
   ``core.venous.jobs.WorkflowRun`` (run identity + id-reuse policy) and
   ``core.venous.jobs.DurableTimer`` (workflow-scoped persistent sleep).
2. Copy the FastAPI adapter ``WorkflowAdapter`` (attaches
   InMemoryWorkflowClient + InMemoryTimerService to ``app.state``).
3. Emit ``app/workflow.py`` (≤ 20-line glue) + ``app/api/routes/tasks.py``
   (POST 202 / GET status / DELETE cancel) calling ``WorkflowAdapter.install(app)``.

Idempotent: a second run detects ``WorkflowAdapter`` in the glue file
and returns ``status="no_op"``.

Warnings:
    Task state is held in-process (InMemoryWorkflowClient) and does NOT
    persist across process restarts. Swap the reference client for a
    Temporal/Cadence client in production for durable state.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_api_add_long_running_task",
    "description": (
        "Copy WorkflowRun + DurableTimer primitives + FastAPI WorkflowAdapter "
        "into the project and wire a ≤20-line app/workflow.py caller plus task routes."
    ),
    "tags": ["extend", "api_design"],
    "entry": "add_long_running_task",
    "imports_primitives": [
        "core.venous.jobs.WorkflowRun",
        "core.venous.jobs.DurableTimer",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.WorkflowAdapter",
    ],
}


def add_long_running_task(inp: ToolInput) -> ToolResult:
    """Add long-running-task endpoints by delegating to shipped primitives + adapter."""
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    # Glue writes to `app/workflow.py` (not `app/tasks.py`) because
    # `add_file_upload` owns the `app/tasks/` package for task handler
    # modules — a file of the same name would be shadowed by Python's
    # package import precedence. See e2e regression fixed 2026-04-22.
    glue_file = app_dir / "workflow.py"

    # Idempotency guard
    if glue_file.exists() and "WorkflowAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Long-running-task infra already wired via the FastAPI adapter."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy WorkflowRun + DurableTimer primitives + WorkflowAdapter "
                "and write app/workflow.py + app/api/routes/tasks.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=[
            "core.venous.jobs.WorkflowRun",
            "core.venous.jobs.DurableTimer",
        ],
        adapters=["core.venous._adapters.fastapi.WorkflowAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "workflow.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_init = routes_dir / "__init__.py"
    if not routes_init.exists():
        routes_init.write_text('"""API routes package."""\n')
        files_created.append(str(routes_init))
    tasks_route_file = routes_dir / "tasks.py"
    render_to(_HERE, "tasks_route.py.tmpl", dest=tasks_route_file, substitutions={})
    files_created.append(str(tasks_route_file))

    files_modified: list[str] = []
    routes_init_parent = app_dir / "routes" / "__init__.py"
    if routes_init_parent.exists():
        content = routes_init_parent.read_text()
        if "tasks_router" not in content:
            content = content.rstrip("\n") + (
                "\nfrom app.api.routes.tasks import router as tasks_router\n"
                "api_router.include_router(tasks_router)\n"
            )
            routes_init_parent.write_text(content)
            files_modified.append(str(routes_init_parent))

    # Emit test
    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitives: core.venous.jobs.WorkflowRun + core.venous.jobs.DurableTimer.",
            "Shipped adapter: core.venous._adapters.fastapi.WorkflowAdapter.",
            "Wrote app/workflow.py + app/api/routes/tasks.py (POST 202 / GET / DELETE).",
            "WorkflowRun enforces id-reuse policy (REJECT by default) and deterministic replay.",
            "WARNING: task state is in-process (InMemoryWorkflowClient) — does NOT persist "
            "across restarts. Use Temporal/Cadence in production.",
        ],
        next_steps=[
            "Import install_long_running_tasks in app/main.py and invoke it after FastAPI().",
            "POST /tasks with {workflow_id, workflow_type, task_queue, args} returns 202 + Location.",
            "Swap the reference InMemoryWorkflowClient for a Temporal/Cadence client in production.",
        ],
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_long_running_task_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_long_running_task_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_long_running_task_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
