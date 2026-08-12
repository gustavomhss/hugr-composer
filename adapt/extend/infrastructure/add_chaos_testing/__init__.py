"""TOOL-099: add_chaos_testing — fault injection for dev/staging environments.

Generates ``app/chaos/__init__.py`` (ChaosEngine), ``app/chaos/injectors.py``
(LatencyInjector, ErrorInjector, TimeoutInjector), ``app/chaos/middleware.py``
(ChaosMiddleware) and ``app/api/routes/chaos.py``
(POST /chaos/enable, POST /chaos/disable, GET /chaos/status).

The production guard is hardcoded inside ``ChaosEngine``: chaos **cannot** be
enabled when ``ENVIRONMENT == "production"``, regardless of ``CHAOS_ENABLED``.

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.

The tool is idempotent: a second run detects ``ChaosEngine`` in
``app/chaos/__init__.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.config_patcher import patch_settings_fields
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_testing_add_chaos_testing",
    "description": (
        "Add chaos engineering fault injection for dev/staging. "
        "Hardcoded guard: NEVER active in production (ENVIRONMENT=production)."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_chaos_testing",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_chaos_testing(inp: ToolInput) -> ToolResult:
    """Add chaos testing fault injection to a FastAPI project."""
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
    app_dir = project / "app"
    chaos_init = app_dir / "chaos" / "__init__.py"

    if chaos_init.exists() and "ChaosEngine" in chaos_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["ChaosEngine already present — chaos testing already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/chaos/__init__.py, injectors.py, "
                "middleware.py, and app/api/routes/chaos.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    chaos_dir = app_dir / "chaos"
    chaos_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "chaos_engine.py.tmpl", dest=chaos_init, substitutions={})
    files_created.append(str(chaos_init))

    injectors_file = chaos_dir / "injectors.py"
    render_to(_HERE, "chaos_injectors.py.tmpl", dest=injectors_file, substitutions={})
    files_created.append(str(injectors_file))

    middleware_file = chaos_dir / "middleware.py"
    render_to(_HERE, "chaos_middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        chaos_route = routes_dir / "chaos.py"
        render_to(_HERE, "chaos_routes.py.tmpl", dest=chaos_route, substitutions={})
        files_created.append(str(chaos_route))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        patch_settings_fields(
            config_file,
            fields=[
                ("CHAOS_ENABLED", "CHAOS_ENABLED: bool = False"),
                ("CHAOS_LATENCY_MS", "CHAOS_LATENCY_MS: int = 0"),
                ("CHAOS_ERROR_RATE", "CHAOS_ERROR_RATE: float = 0.0"),
                ("CHAOS_TIMEOUT_RATE", "CHAOS_TIMEOUT_RATE: float = 0.0"),
            ],
        )
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

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

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Chaos testing added: LatencyInjector, ErrorInjector, TimeoutInjector.",
            "PRODUCTION GUARD: chaos is physically blocked when ENVIRONMENT=production.",
            "ChaosMiddleware only activates when CHAOS_ENABLED=true AND not production.",
            "Endpoints: POST /chaos/enable, POST /chaos/disable, GET /chaos/status.",
            "Config: CHAOS_ENABLED (default false), CHAOS_LATENCY_MS, CHAOS_ERROR_RATE.",
        ],
        next_steps=[
            "Set CHAOS_ENABLED=true in .env for dev/staging ONLY.",
            "Set CHAOS_LATENCY_MS=200 to inject 200ms latency.",
            "Set CHAOS_ERROR_RATE=0.1 for 10% random 500 errors.",
            "Set CHAOS_TIMEOUT_RATE=0.05 for 5% request timeouts.",
            "POST /chaos/enable to activate (blocked in production).",
            "POST /chaos/disable to deactivate.",
            "Wire ChaosMiddleware into app.add_middleware() in main.py.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_main(main_file: Path) -> None:
    """Inject chaos middleware and router into main.py."""
    src = main_file.read_text()
    if "ChaosMiddleware" in src:
        return
    import_snippet = (
        "\nfrom app.chaos.middleware import ChaosMiddleware"
        "  # noqa: F401 — chaos fault injection\n"
        "from app.api.routes.chaos import router as _chaos_router"
        "  # noqa: F401 — chaos endpoints\n"
    )
    wire_snippet = (
        "\n# Chaos testing middleware + router — added by add_chaos_testing tool\n"
        "app.add_middleware(ChaosMiddleware)\n"
        "app.include_router(_chaos_router)\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_snippet,
        )
    else:
        src = import_snippet + src
    src = src.rstrip("\n") + "\n" + wire_snippet
    main_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_chaos_testing_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_chaos_testing_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


