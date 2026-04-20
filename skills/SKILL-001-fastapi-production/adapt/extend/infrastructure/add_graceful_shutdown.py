"""TOOL-100: add_graceful_shutdown — signal-driven graceful shutdown for FastAPI.

Reference implementation of the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.resiliency.GracefulShutdown`` into the generated project.
2. Copy the FastAPI adapter
   ``core.venous._adapters.fastapi.GracefulShutdownAdapter`` alongside it.
3. Emit a thin ``app/shutdown.py`` (≤ 20 lines of glue) that calls
   ``GracefulShutdownAdapter.install(app, ...)``.

The tool is idempotent: a second run detects the import chain in
``app/shutdown.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_graceful_shutdown import add_graceful_shutdown

    result = add_graceful_shutdown(ToolInput(project_dir="/path/to/project"))
    print(result.status)              # "success"
    print(result.imports_primitives)  # ["core.venous.resiliency.GracefulShutdown"]
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_add_graceful_shutdown",
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


_GLUE = '''\
"""Wire graceful shutdown into the FastAPI app.

Delegates to the primitive + FastAPI adapter copied under `core/venous/`
by the `add_graceful_shutdown` tool. Hand-editing is safe but the file is
re-emitted idempotently on subsequent tool runs.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from core.venous._adapters.fastapi.GracefulShutdownAdapter import install


def install_graceful_shutdown(app: FastAPI) -> None:
    """Attach drain middleware + shutdown coordinator to *app*."""
    install(
        app,
        drain_seconds=float(os.getenv("SHUTDOWN_DRAIN_SECONDS", "5")),
        timeout_seconds=float(os.getenv("SHUTDOWN_TIMEOUT_SECONDS", "30")),
    )
'''


def add_graceful_shutdown(inp: ToolInput) -> ToolResult:
    """Add graceful shutdown by delegating to the shipped primitive + adapter.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    shutdown_file = app_dir / "shutdown.py"

    # --- Idempotency guard ---------------------------------------------------
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

    # --- Step 1: copy primitive + adapter (idempotent) ---------------------
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.GracefulShutdown"],
        adapters=["core.venous._adapters.fastapi.GracefulShutdownAdapter"],
    )
    files_created.append(manifest.path)

    # --- Step 2: thin glue -------------------------------------------------
    app_dir.mkdir(parents=True, exist_ok=True)
    shutdown_file.write_text(_GLUE)
    files_created.append(str(shutdown_file))

    # --- Step 3: patch config.py ------------------------------------------
    files_modified: list[str] = []
    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and "SHUTDOWN_DRAIN_SECONDS" not in config_file.read_text():
        src = config_file.read_text()
        fields = (
            "\n    # Graceful shutdown (TOOL-100)\n"
            "    SHUTDOWN_DRAIN_SECONDS: float = 5.0\n"
            "    SHUTDOWN_TIMEOUT_SECONDS: float = 30.0\n"
        )
        if "settings = Settings()" in src:
            src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
        else:
            src = src.rstrip("\n") + "\n" + fields
        config_file.write_text(src)
        files_modified.append(str(config_file))

    # --- Step 4: validate every .py we created parses ---------------------
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


def _elapsed_ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
