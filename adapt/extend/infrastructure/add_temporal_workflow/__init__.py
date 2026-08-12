"""TOOL-067: add_temporal_workflow — add a Temporal.io durable workflow engine to a FastAPI project.

Writes an ``app/workflows/`` package containing a lazy-import ``TemporalClientFactory``
singleton, a ``WorkerFactory`` for the separate worker process, an
``OrderProcessingWorkflow`` with 3 activities and compensation-on-failure, activity
definitions with retry policies, REST companion routes for starting, querying,
signalling, and cancelling workflows, and a ``Dockerfile.temporal-worker`` for the
non-root container.

The tool is idempotent: a second run detects the ``TemporalClientFactory``
fingerprint in ``app/workflows/client.py`` and returns ``status="no_op"``
without touching any file.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_temporal_workflow",
    "description": (
        "Add a Temporal.io durable workflow engine with order-processing example, "
        "compensation pattern, signal support, and REST companion routes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_temporal_workflow",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_temporal_workflow(inp: ToolInput) -> ToolResult:
    """Add a Temporal.io durable workflow engine to a FastAPI project.

    Creates the workflows package (client singleton, worker factory, example
    workflow with compensation, activity definitions), REST companion routes,
    ``Dockerfile.temporal-worker``, and patches ``app/core/config.py`` and
    ``requirements.txt``.

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
        Prereq.ROUTES_INIT,
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

    client_file = app_dir / "workflows" / "client.py"
    if client_file.exists() and "TemporalClientFactory" in client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "TemporalClientFactory already present — "
                "Temporal workflow engine is already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/workflows/ package "
                "(client.py, worker.py, example_workflow.py, activities.py),",
                "         POST /workflows/start, GET /workflows/{id}/status, "
                "POST /workflows/{id}/signal, POST /workflows/{id}/cancel,",
                "         Dockerfile.temporal-worker.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    workflows_dir = app_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflows_init = workflows_dir / "__init__.py"
    if not workflows_init.exists():
        render_to(_HERE, "workflows_init.py.tmpl", dest=workflows_init, substitutions={})
        files_created.append(str(workflows_init))

    render_to(_HERE, "client.py.tmpl", dest=client_file, substitutions={})
    files_created.append(str(client_file))

    worker_file = workflows_dir / "worker.py"
    render_to(_HERE, "worker.py.tmpl", dest=worker_file, substitutions={})
    files_created.append(str(worker_file))

    activities_file = workflows_dir / "activities.py"
    render_to(_HERE, "activities.py.tmpl", dest=activities_file, substitutions={})
    files_created.append(str(activities_file))

    workflow_file = workflows_dir / "example_workflow.py"
    render_to(_HERE, "example_workflow.py.tmpl", dest=workflow_file, substitutions={})
    files_created.append(str(workflow_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    workflow_routes_file = routes_dir / "workflows.py"
    render_to(_HERE, "workflow_routes.py.tmpl", dest=workflow_routes_file, substitutions={})
    files_created.append(str(workflow_routes_file))

    dockerfile = project / "Dockerfile.temporal-worker"
    if not dockerfile.exists():
        render_to(_HERE, "Dockerfile.temporal-worker.tmpl", dest=dockerfile, substitutions={})
        files_created.append(str(dockerfile))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Temporal workflow engine added: TemporalClientFactory singleton, "
            "WorkerFactory, OrderProcessingWorkflow with compensation pattern.",
            "Activities: validate_order, charge_payment, fulfil_order "
            "(each with retry policy + compensation).",
            "REST routes: POST /workflows/start, GET /workflows/{id}/status, "
            "POST /workflows/{id}/signal, POST /workflows/{id}/cancel.",
            "Worker runs as a separate process — app/main.py is NOT modified.",
            "temporalio imported lazily so app boots without the SDK installed.",
            "Dockerfile.temporal-worker generated (non-root USER 1000).",
        ],
        next_steps=[
            "Start a Temporal server: docker run --rm -p 7233:7233 temporalio/auto-setup:latest",
            "Set TEMPORAL_HOST in .env (default: localhost:7233).",
            "Set TEMPORAL_NAMESPACE (default: default) and "
            "TEMPORAL_TASK_QUEUE (default: main-queue).",
            "Install the SDK: pip install 'temporalio>=1.7.0'",
            "Start the worker: "
            "docker build -f Dockerfile.temporal-worker -t myapp-temporal-worker . "
            "&& docker run --rm --env-file .env myapp-temporal-worker",
            "Or locally: python -m app.workflows.worker",
            "Restart the FastAPI app so the /workflows/* routes are active.",
            "Verify: POST /workflows/start with an order_id payload.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Patch ``app/core/config.py`` to add TEMPORAL_* settings."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("TEMPORAL_HOST", 'TEMPORAL_HOST: str = "localhost:7233"'),
            ("TEMPORAL_NAMESPACE", 'TEMPORAL_NAMESPACE: str = "default"'),
            ("TEMPORAL_TASK_QUEUE", 'TEMPORAL_TASK_QUEUE: str = "main-queue"'),
        ],
    )


def _patch_requirements(requirements_file: Path) -> None:
    """Append ``temporalio>=1.7.0`` to requirements.txt idempotently."""
    if not requirements_file.exists():
        return
    content = requirements_file.read_text()
    if "temporalio" in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "temporalio>=1.7.0\n"
    requirements_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register ``workflows`` router in ``app/routes/__init__.py`` idempotently."""
    if not routes_init.exists():
        return
    content = routes_init.read_text()
    import_line = "from app.api.routes.workflows import router as workflows_router"
    include_line = "api_router.include_router(workflows_router)"
    if "workflows_router" in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_temporal_workflow_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_temporal_workflow_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_temporal_workflow_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return milliseconds elapsed since *start* (monotonic clock)."""
    return max(1, int((time.monotonic() - start) * 1000))
