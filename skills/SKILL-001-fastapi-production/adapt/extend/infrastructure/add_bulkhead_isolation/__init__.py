"""TOOL-097: add_bulkhead_isolation — per-endpoint-group concurrency partitioning.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.resiliency.Bulkhead`` into the generated project.
2. Emit a thin ``app/resilience/bulkhead.py`` glue file (≤ 20 logic lines)
   that instantiates a ``PartitionRegistry`` and exposes a factory used by
   the ASGI middleware.
3. Emit a ``BulkheadMiddleware`` (thin glue over the primitive) and a
   status route — both are pure wiring over the primitive's public API.

The tool is idempotent: a second run detects the primitive's
``InMemoryBulkhead`` import in ``app/resilience/bulkhead.py`` and returns
``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_bulkhead_isolation",
    "description": (
        "Copy Bulkhead primitive into the project and wire a thin "
        "app/resilience/bulkhead.py + ASGI middleware that partitions "
        "semaphore permits per endpoint group."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_bulkhead_isolation",
    "imports_primitives": [
        "core.venous.resiliency.Bulkhead",
    ],
    "imports_adapters": ("core.venous._adapters.fastapi.BulkheadAdapter",),
}


def add_bulkhead_isolation(inp: ToolInput) -> ToolResult:
    """Add bulkhead isolation by delegating to the shipped primitive."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    resilience_dir = app_dir / "resilience"
    glue_file = resilience_dir / "bulkhead.py"

    if glue_file.exists() and "BulkheadAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Bulkhead adapter already wired via app/resilience/bulkhead.py."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy Bulkhead primitive and write "
                "app/resilience/bulkhead.py + pool_config.py + "
                "middleware/bulkhead.py + bulkhead_status.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.Bulkhead"],
        adapters=["core.venous._adapters.fastapi.BulkheadAdapter"],
    )
    files_created.append(manifest.path)

    files_modified: list[str] = []

    resilience_dir.mkdir(parents=True, exist_ok=True)
    resilience_init = resilience_dir / "__init__.py"
    if not resilience_init.exists():
        resilience_init.write_text('"""Resilience patterns package."""\n')
        files_created.append(str(resilience_init))

    render_to(_HERE, "bulkhead_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    pool_config_file = resilience_dir / "pool_config.py"
    render_to(_HERE, "pool_config_glue.py.tmpl", dest=pool_config_file, substitutions={})
    files_created.append(str(pool_config_file))

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_init = middleware_dir / "__init__.py"
    if not middleware_init.exists():
        middleware_init.write_text('"""Middleware package."""\n')
        files_created.append(str(middleware_init))

    mw_file = middleware_dir / "bulkhead.py"
    render_to(_HERE, "middleware_glue.py.tmpl", dest=mw_file, substitutions={})
    files_created.append(str(mw_file))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "bulkhead_status.py"
        render_to(_HERE, "status_route_glue.py.tmpl", dest=status_route, substitutions={})
        files_created.append(str(status_route))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    glue_loc = _count_logic_lines(glue_file.read_text())
    if glue_loc > 20:
        return ToolResult(
            status="error",
            error=f"Primary glue {glue_file} has {glue_loc} logic lines (> 20).",
            execution_time_ms=_ms(start),
        )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitive: core.venous.resiliency.Bulkhead.",
            "Shipped adapter: core.venous._adapters.fastapi.BulkheadAdapter "
            "(Bulkhead facade + BulkheadMiddleware).",
            "Glue: app/resilience/bulkhead.py re-exports adapter + get_bulkhead() factory.",
            "app/middleware/bulkhead.py: install_if_enabled(app) — one-line wire-in.",
            "Status endpoint: GET /resilience/bulkheads (delegates to Bulkhead.status()).",
            "Config: BULKHEAD_ENABLED, BULKHEAD_PAYMENTS_MAX, BULKHEAD_CRUD_MAX, "
            "BULKHEAD_ANALYTICS_MAX, BULKHEAD_WAIT_MS.",
        ],
        next_steps=[
            "Set BULKHEAD_ENABLED=true in .env to activate.",
            "Call `install_if_enabled(app)` from main.py (idempotent no-op when disabled).",
            "Include bulkhead_status router in app for /resilience/bulkheads.",
            "Tune BULKHEAD_*_MAX values to match your workload profiles.",
            "Monitor /resilience/bulkheads to identify bottleneck groups.",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Add BULKHEAD_* fields to ``app/core/config.py`` Settings class."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("BULKHEAD_ENABLED", "BULKHEAD_ENABLED: bool = False"),
            ("BULKHEAD_PAYMENTS_MAX", "BULKHEAD_PAYMENTS_MAX: int = 10"),
            ("BULKHEAD_CRUD_MAX", "BULKHEAD_CRUD_MAX: int = 50"),
            ("BULKHEAD_ANALYTICS_MAX", "BULKHEAD_ANALYTICS_MAX: int = 20"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Leave a hint in main.py for installing the BulkheadMiddleware."""
    src = main_file.read_text()
    if "bulkhead" in src:
        return
    note = (
        "\n# Bulkhead isolation — added by add_bulkhead_isolation tool\n"
        "# from app.middleware.bulkhead import install_if_enabled\n"
        "# from app.api.routes.bulkhead_status import router as bulkhead_router\n"
        "# install_if_enabled(app)\n"
        "# app.include_router(bulkhead_router)\n"
    )
    main_file.write_text(src.rstrip("\n") + "\n" + note)


def _count_logic_lines(source: str) -> int:
    """Count executable logic lines in a rendered glue file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    loc = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            start = node.body[0].lineno
            end = node.end_lineno or start
            loc += end - start + 1
    return loc


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_bulkhead_isolation_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_bulkhead_isolation_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
