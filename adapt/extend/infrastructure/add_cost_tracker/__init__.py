"""TOOL-120: add_cost_tracker — per-request cost estimation for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy ``core.venous.resiliency.CostTracker`` (primitive ships CostTracker,
   RequestContext, CostEstimate, and the DB/S3/API estimators).
2. Copy the FastAPI adapter ``CostTrackerAdapter`` (middleware emitting
   ``X-Request-Cost-Estimate``).
3. Emit ``app/cost_tracker.py`` (≤ 20-line glue) calling
   ``CostTrackerAdapter.install(app, ...)``.

Idempotent: a second run detects ``CostTrackerAdapter`` in the glue
and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_cost_tracker",
    "description": (
        "Copy CostTracker primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/cost_tracker.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_cost_tracker",
    "imports_primitives": [
        "core.venous.resiliency.CostTracker",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.CostTrackerAdapter",
    ],
}


def add_cost_tracker(inp: ToolInput) -> ToolResult:
    """Add per-request cost estimation by delegating to the shipped primitive + adapter."""
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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "cost_tracker.py"

    if glue_file.exists() and "CostTrackerAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Cost tracker already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy CostTracker primitive + FastAPI adapter "
                "and write app/cost_tracker.py calling CostTrackerAdapter.install(app, ...)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.CostTracker"],
        adapters=["core.venous._adapters.fastapi.CostTrackerAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "cost_tracker_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    files_modified: list[str] = []
    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and "COST_DB_QUERY_RATE" not in config_file.read_text():
        from adapt.contracts.config_patcher import patch_settings_fields

        patch_settings_fields(
            config_file,
            fields=[
                ("COST_TRACKING_ENABLED", "COST_TRACKING_ENABLED: bool = False"),
                ("COST_DB_QUERY_RATE", "COST_DB_QUERY_RATE: float = 0.00001"),
                ("COST_S3_PER_GB", "COST_S3_PER_GB: float = 0.023"),
                ("COST_API_CALL_RATE", "COST_API_CALL_RATE: float = 0.0001"),
            ],
        )
        files_modified.append(str(config_file))

    _emit_project_test(project, files_created)

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
            "Shipped primitive: core.venous.resiliency.CostTracker (with DB/S3/API estimators).",
            "Shipped adapter: core.venous._adapters.fastapi.CostTrackerAdapter.",
            "Wrote app/cost_tracker.py — call install_cost_tracker(app) from main.py.",
            "Middleware annotates each response with X-Request-Cost-Estimate (fail-open).",
        ],
        next_steps=[
            "Import install_cost_tracker in app/main.py and invoke it after FastAPI().",
            "Set COST_DB_QUERY_RATE / COST_S3_PER_GB / COST_API_CALL_RATE in .env to match cloud pricing.",
            "Populate request.state.cost_context counters (db_query_count, s3_bytes_transferred, external_api_calls) during request processing.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_cost_tracker_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_cost_tracker_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_cost_tracker_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


