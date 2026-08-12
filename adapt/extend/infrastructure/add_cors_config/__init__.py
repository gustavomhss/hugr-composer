"""TOOL-088: add_cors_config — env-var configurable CORS middleware.

Upgrades CORS in a FastAPI project: origins read from ``CORS_ALLOWED_ORIGINS``
(comma-separated), wildcard-warning logging in non-local environments,
configurable ``CORS_MAX_AGE`` / ``CORS_ALLOW_CREDENTIALS``, and a
``GET /cors/config`` debug endpoint.

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only (phase-1 ``discover``, phase-3 ``write``, phase-4 ``patch``).

The tool is idempotent: a second run detects ``CORSConfigMiddleware`` inside
``app/middleware/cors_config.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_cors_config",
    "description": (
        "Upgrade CORS middleware with env-var configurable origins, wildcard warnings, "
        "preflight cache, and a /cors/config debug endpoint."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_cors_config",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_cors_config(inp: ToolInput) -> ToolResult:
    """Upgrade CORS configuration in a FastAPI project."""
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
                "Generate a base project first with fastapi_generate_project(...).",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    cors_config_file = app_dir / "middleware" / "cors_config.py"

    if cors_config_file.exists() and "CORSConfigMiddleware" in cors_config_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["CORSConfigMiddleware already present — configurable CORS already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/middleware/cors_config.py, "
                "app/api/routes/cors_debug.py, and patch config + main."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    render_to(_HERE, "cors_config_middleware.py.tmpl", dest=cors_config_file, substitutions={})
    files_created.append(str(cors_config_file))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        cors_debug_route = routes_dir / "cors_debug.py"
        render_to(_HERE, "cors_debug_route.py.tmpl", dest=cors_debug_route, substitutions={})
        files_created.append(str(cors_debug_route))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
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
            "CORS upgraded: origins read from CORS_ALLOWED_ORIGINS env var (comma-separated).",
            "Wildcard '*' origin triggers a warning log in non-local environments.",
            "Preflight responses cached for CORS_MAX_AGE seconds (default: 600).",
            "GET /cors/config debug endpoint lists active CORS configuration.",
            "WARNING: default CORS_ALLOWED_ORIGINS='*' IS NOT a safe production default — "
            "the tool only logs a warning; it does NOT block startup or reject the request.",
        ],
        next_steps=[
            "Set CORS_ALLOWED_ORIGINS=https://app.example.com,https://www.example.com in .env.",
            "Set CORS_ALLOW_CREDENTIALS=true if your frontend sends cookies.",
            "Set CORS_MAX_AGE=3600 to increase preflight cache duration.",
            "Never use CORS_ALLOWED_ORIGINS=* in production — it defeats CORS protections.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject CORS_* fields inside the Settings class body."""
    src = config_file.read_text()
    if "CORS_ALLOWED_ORIGINS" in src:
        return
    new_fields = (
        "\n"
        "    # CORS configuration — added by add_cors_config tool\n"
        '    CORS_ALLOWED_ORIGINS: str = "*"\n'
        "    CORS_ALLOW_CREDENTIALS: bool = False\n"
        "    CORS_MAX_AGE: int = 600\n"
    )
    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    if anchor in src:
        src = src.replace(anchor, anchor + new_fields)
    else:
        for decorator in ("    @computed_field", "    @model_validator", "    @property"):
            if decorator in src:
                first_pos = src.index(decorator)
                src = src[:first_pos] + new_fields + "\n" + src[first_pos:]
                break
        else:
            marker = "settings = Settings()"
            if marker in src:
                src = src.replace(marker, new_fields + "\n" + marker)
            else:
                src = src.rstrip("\n") + new_fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject CORSConfigMiddleware and /cors/config router into app/main.py."""
    src = main_file.read_text()
    if "CORSConfigMiddleware" in src:
        return
    cors_import = (
        "\nfrom app.middleware.cors_config import CORSConfigMiddleware"
        "  # noqa: F401 — configurable CORS\n"
        "from app.api.routes.cors_debug import router as _cors_debug_router\n"
    )
    add_middleware_snippet = (
        "\n# Configurable CORS + debug endpoint — added by add_cors_config tool\n"
        "app.add_middleware(CORSConfigMiddleware)\n"
        "app.include_router(_cors_debug_router)\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + cors_import,
        )
    else:
        src = cors_import + src
    src = src.rstrip("\n") + "\n" + add_middleware_snippet
    main_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_cors_config_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_cors_config_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


