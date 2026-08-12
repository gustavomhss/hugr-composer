"""TOOL-100: add_graceful_shutdown — signal-driven graceful shutdown for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.resiliency.GracefulShutdown`` into the generated project.
2. Copy the FastAPI adapter
   ``core.venous._adapters.fastapi.GracefulShutdownAdapter`` alongside it.
3. Emit a thin ``app/shutdown.py`` (≤ 20 lines of glue) that calls
   ``GracefulShutdownAdapter.install(app, ...)``.

The tool is idempotent: a second run detects the import chain in
``app/shutdown.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_graceful_shutdown",
    "description": (
        "Copy GracefulShutdown primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/shutdown.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_graceful_shutdown",
    "imports_primitives": [
        "core.venous.resiliency.GracefulShutdown",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.GracefulShutdownAdapter",
    ],
}


def add_graceful_shutdown(inp: ToolInput) -> ToolResult:
    """Add graceful shutdown by delegating to the shipped primitive + adapter."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    shutdown_file = app_dir / "shutdown.py"

    if shutdown_file.exists() and "GracefulShutdownAdapter" in shutdown_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Graceful shutdown already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy GracefulShutdown primitive + FastAPI adapter "
                "and write app/shutdown.py calling GracefulShutdownAdapter.install(app)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.GracefulShutdown"],
        adapters=["core.venous._adapters.fastapi.GracefulShutdownAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "shutdown_glue.py.tmpl", dest=shutdown_file, substitutions={})
    files_created.append(str(shutdown_file))

    files_modified: list[str] = []
    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and "SHUTDOWN_DRAIN_SECONDS" not in config_file.read_text():
        from adapt.contracts.config_patcher import patch_settings_fields

        patch_settings_fields(
            config_file,
            fields=[
                ("SHUTDOWN_DRAIN_SECONDS", "SHUTDOWN_DRAIN_SECONDS: float = 5.0"),
                ("SHUTDOWN_TIMEOUT_SECONDS", "SHUTDOWN_TIMEOUT_SECONDS: float = 30.0"),
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
            "Shipped primitive: core.venous.resiliency.GracefulShutdown.",
            "Shipped adapter: core.venous._adapters.fastapi.GracefulShutdownAdapter.",
            "Wrote app/shutdown.py — call install_graceful_shutdown(app) from main.py.",
            "Drain returns 503 + Retry-After on non-pass-through paths.",
        ],
        next_steps=[
            "Import install_graceful_shutdown in app/main.py and invoke it after FastAPI() construction.",
            "Set SHUTDOWN_DRAIN_SECONDS / SHUTDOWN_TIMEOUT_SECONDS in .env to override defaults.",
            "Test with: kill -SIGTERM <pid> and verify 503 during drain phase.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_graceful_shutdown_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_graceful_shutdown_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


