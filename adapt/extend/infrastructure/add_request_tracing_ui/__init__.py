"""TOOL-122: add_request_tracing_ui — embedded request tracing dashboard.

Adds a self-contained request tracing system with a ring-buffer of the last
N requests, per-layer timing breakdown, and a vanilla-JS dashboard served at
``/tracing/dashboard``.

Idempotent: a second run detects ``TracingBuffer`` in
``app/tracing_ui/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_request_tracing_ui import add_request_tracing_ui

    result = add_request_tracing_ui(ToolInput(project_dir="/path/to/project"))
    print(result.status)          # "success"
    print(result.files_created)   # [.../app/tracing_ui/__init__.py, ...]
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base.render import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_deployment_add_request_tracing_ui",
    "description": (
        "Add an embedded request tracing dashboard: TracingBuffer ring buffer (last 1000 "
        "requests), TimingCollector per-middleware/DB/external timing, GET /tracing/requests, "
        "GET /tracing/requests/{id}, GET /tracing/slow (p99), and a self-contained vanilla-JS "
        "HTML dashboard at GET /tracing/dashboard."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_request_tracing_ui",
    "imports_primitives": [],
    "imports_adapters": [],

}

_NOTES_SUCCESS = [
    "Request tracing UI enabled: TracingBuffer ring buffer (last 1000 requests).",
    "TimingCollector records per-layer timing: middleware, DB, external calls.",
    "Three JSON endpoints: GET /tracing/requests, GET /tracing/requests/{id}, "
    "GET /tracing/slow (p99 requests).",
    "Self-contained HTML dashboard at GET /tracing/dashboard (no build step).",
    "All tracing is in-process — zero external dependencies.",
]
_NEXT_STEPS = [
    "Set TRACING_UI_ENABLED=true in .env (default: false).",
    "Set TRACING_UI_BUFFER_SIZE in .env (default: 1000).",
    "Set TRACING_UI_AUTH_REQUIRED=true in .env to password-protect the dashboard.",
    "Visit /tracing/dashboard in your browser after starting the server.",
    "Instrument DB queries: call collector.record_span('db', latency_ms) from your DAL.",
]


def add_request_tracing_ui(inp: ToolInput) -> ToolResult:
    """Add request tracing UI to a FastAPI project.

    Writes ``app/tracing_ui/`` package, a routes file, an HTML dashboard
    template, patches ``app/core/config.py`` with tracing knobs, and
    registers the router in ``app/main.py``.

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
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    tracing_init = app_dir / "tracing_ui" / "__init__.py"
    if tracing_init.exists() and "TracingBuffer" in tracing_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["TracingBuffer already present — request tracing UI already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/tracing_ui/ package with TracingBuffer and TimingCollector.",
                "[dry_run] Would create app/api/routes/tracing.py with 3 endpoints.",
                "[dry_run] Would create app/tracing_ui/templates/dashboard.html.",
                "[dry_run] Would patch app/core/config.py and app/main.py.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    tracing_dir = app_dir / "tracing_ui"
    tracing_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = tracing_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "tracing_init.py.tmpl", dest=tracing_init, substitutions={})
    files_created.append(str(tracing_init))

    render_to(
        _HERE, "timing_collector.py.tmpl", dest=tracing_dir / "collector.py", substitutions={}
    )
    files_created.append(str(tracing_dir / "collector.py"))

    render_to(
        _HERE, "tracing_middleware.py.tmpl", dest=tracing_dir / "middleware.py", substitutions={}
    )
    files_created.append(str(tracing_dir / "middleware.py"))

    render_to(_HERE, "dashboard.html.tmpl", dest=templates_dir / "dashboard.html", substitutions={})
    files_created.append(str(templates_dir / "dashboard.html"))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        render_to(_HERE, "tracing_routes.py.tmpl", dest=routes_dir / "tracing.py", substitutions={})
        files_created.append(str(routes_dir / "tracing.py"))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

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
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_request_tracing_ui_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_request_tracing_ui_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_request_tracing_ui_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    """Inject tracing UI settings into app/core/config.py.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("TRACING_UI_ENABLED", "TRACING_UI_ENABLED: bool = False"),
            ("TRACING_UI_BUFFER_SIZE", "TRACING_UI_BUFFER_SIZE: int = 1000"),
            ("TRACING_UI_AUTH_REQUIRED", "TRACING_UI_AUTH_REQUIRED: bool = False"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Register tracing router and middleware in app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "tracing_ui" in src:
        return

    tracing_import = (
        "\nfrom app.api.routes.tracing import router as tracing_router"
        "  # noqa: E402 — request tracing UI\n"
        "from app.tracing_ui.middleware import TracingMiddleware  # noqa: E402\n"
    )
    tracing_register = (
        "\n# Request tracing UI — added by add_request_tracing_ui tool\n"
        "app.add_middleware(TracingMiddleware)\n"
        "app.include_router(tracing_router)\n"
    )

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + tracing_import,
        )
    else:
        src = tracing_import + src

    src = src.rstrip("\n") + "\n" + tracing_register
    main_file.write_text(src)


