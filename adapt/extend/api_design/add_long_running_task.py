"""TOOL-020: add_long_running_task — durable async task endpoints for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitives
   ``core.venous.jobs.WorkflowRun`` (run identity + id-reuse policy) and
   ``core.venous.jobs.DurableTimer`` (workflow-scoped persistent sleep).
2. Copy the FastAPI adapter ``WorkflowAdapter`` (attaches
   InMemoryWorkflowClient + InMemoryTimerService to ``app.state``).
3. Emit ``app/tasks.py`` (≤ 20-line glue) + ``app/api/routes/tasks.py``
   (POST 202 / GET status / DELETE cancel) calling ``WorkflowAdapter.install(app)``.

Idempotent: a second run detects ``WorkflowAdapter`` in the glue file
and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_api_add_long_running_task",
    "description": (
        "Copy WorkflowRun + DurableTimer primitives + FastAPI WorkflowAdapter "
        "into the project and wire a ≤20-line app/tasks.py caller plus task routes."
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


_GLUE = '''\
"""Wire durable long-running-task primitives into the FastAPI app.

Delegates to the primitives + FastAPI adapter copied under `core/venous/`
by the `add_long_running_task` tool. Re-emitted idempotently on subsequent runs.
"""

from __future__ import annotations

from fastapi import FastAPI

from core.venous._adapters.fastapi.WorkflowAdapter import (
    install,
    timer_service_dep,
    workflow_client_dep,
)


def install_long_running_tasks(app: FastAPI) -> None:
    """Attach a WorkflowClient + TimerService to *app.state*."""
    install(app)


__all__ = ["install_long_running_tasks", "timer_service_dep", "workflow_client_dep"]
'''


_ROUTES = '''\
"""HTTP surface for long-running tasks.

- POST /tasks        → 202 Accepted + Location header (workflow started)
- GET  /tasks/{wid}  → status + run_id (polling)
- DELETE /tasks/{wid}→ cooperative cancellation

All state lives in the `WorkflowClient` shipped by the adapter; this module
is pure wiring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from app.tasks import workflow_client_dep

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=202)
async def start_task(
    payload: dict[str, Any],
    response: Response,
    client=Depends(workflow_client_dep),
) -> dict[str, Any]:
    """Start a new workflow run. Returns 202 + Location header."""
    workflow_id = str(payload.get("workflow_id") or payload.get("id") or "")
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflow_id required")
    workflow_type = str(payload.get("workflow_type", "default"))
    task_queue = str(payload.get("task_queue", "default"))
    args = tuple(payload.get("args", ()))
    run = await client.start(workflow_type, workflow_id, task_queue, args)
    response.headers["Location"] = f"/tasks/{run.workflow_id}"
    return {"workflow_id": run.workflow_id, "run_id": run.run_id, "status": "accepted"}


@router.get("/{workflow_id}")
async def get_task(workflow_id: str, client=Depends(workflow_client_dep)) -> dict[str, Any]:
    """Poll a task's current run identity."""
    try:
        run = await client.describe(workflow_id)
    except Exception as exc:  # noqa: BLE001 — primitive raises when unknown
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"workflow_id": run.workflow_id, "run_id": run.run_id, "task_queue": run.task_queue}


@router.delete("/{workflow_id}", status_code=204)
async def cancel_task(workflow_id: str, client=Depends(workflow_client_dep)) -> Response:
    """Cooperatively cancel a task by workflow_id."""
    try:
        await client.cancel(workflow_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
'''


def add_long_running_task(inp: ToolInput) -> ToolResult:
    """Add long-running-task endpoints by delegating to shipped primitives + adapter."""
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "tasks.py"

    if glue_file.exists() and "WorkflowAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Long-running-task infra already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy WorkflowRun + DurableTimer primitives + WorkflowAdapter "
                "and write app/tasks.py + app/api/routes/tasks.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
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
    glue_file.write_text(_GLUE)
    files_created.append(str(glue_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_init = routes_dir / "__init__.py"
    if not routes_init.exists():
        routes_init.write_text('"""API routes package."""\n')
        files_created.append(str(routes_init))
    tasks_route_file = routes_dir / "tasks.py"
    tasks_route_file.write_text(_ROUTES)
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

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitives: core.venous.jobs.WorkflowRun + core.venous.jobs.DurableTimer.",
            "Shipped adapter: core.venous._adapters.fastapi.WorkflowAdapter.",
            "Wrote app/tasks.py + app/api/routes/tasks.py (POST 202 / GET / DELETE).",
            "WorkflowRun enforces id-reuse policy (REJECT by default) and deterministic replay.",
        ],
        next_steps=[
            "Import install_long_running_tasks in app/main.py and invoke it after FastAPI().",
            "POST /tasks with {workflow_id, workflow_type, task_queue, args} returns 202 + Location.",
            "Swap the reference InMemoryWorkflowClient for a Temporal/Cadence client in production.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
