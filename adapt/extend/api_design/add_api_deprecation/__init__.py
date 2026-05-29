"""TOOL-106: add_api_deprecation — endpoint lifecycle management.

Generates a DeprecationRegistry, DeprecationMiddleware (RFC 8594 Sunset +
Deprecation headers + Link to replacement), DeprecationReporter (usage
tracking), GET /api/deprecations listing route, and a @deprecated decorator.

The tool is idempotent: a second run detects the ``DeprecationRegistry``
fingerprint and returns ``status="no_op"`` without touching any file.

Warnings:
    - This tool adds Sunset/Deprecation/Link response headers only.
      It does NOT return 410 Gone on expired endpoints; callers must
      implement their own enforcement if hard removal is required.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_api_deprecation import add_api_deprecation

    result = add_api_deprecation(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/deprecation/__init__.py", ...]

After applying::

    from app.deprecation import deprecated

    @router.get("/items")
    @deprecated(sunset="2026-06-01", replacement="/api/v2/items")
    async def list_items():
        ...
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.config_patcher import patch_settings_fields
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_api_add_api_deprecation",
    "description": (
        "Add endpoint lifecycle management with RFC 8594 Sunset headers, "
        "usage tracking, and @deprecated decorator."
    ),
    "tags": ["extend", "api_design"],
    "entry": "add_api_deprecation",
}

_NOTES_SUCCESS = [
    "API deprecation lifecycle management added.",
    "DeprecationRegistry: register endpoints with sunset dates.",
    "DeprecationMiddleware: adds Sunset (RFC 8594) + Deprecation headers on every response.",
    "DeprecationReporter: tracks usage count of deprecated endpoints.",
    "GET /api/deprecations: list all deprecated endpoints + sunset dates.",
    "@deprecated decorator: mark any route function as deprecated.",
    "WARNING: tool adds headers only — does NOT enforce 410 Gone on expired endpoints.",
]
_NEXT_STEPS = [
    "Decorate deprecated routes: @deprecated(sunset='2026-06-01', replacement='/v2/items')",
    "Register middleware: DeprecationMiddleware is auto-registered in app/main.py",
    "Set DEPRECATION_WARN_DAYS_BEFORE_SUNSET=30 in .env (default: 30)",
    "Monitor usage: GET /api/deprecations to see which deprecated endpoints are still called",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_api_deprecation(inp: ToolInput) -> ToolResult:
    """Add API deprecation lifecycle management to a FastAPI project.

    Creates DeprecationRegistry, DeprecationMiddleware (Sunset + Deprecation
    headers per RFC 8594), DeprecationReporter with usage tracking,
    GET /api/deprecations listing route, and @deprecated decorator.
    Patches ``app/core/config.py`` and ``app/main.py``.

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
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    # Idempotency guard
    registry_file = app_dir / "deprecation" / "__init__.py"
    if registry_file.exists() and "DeprecationRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "DeprecationRegistry already present — API deprecation is already installed, skipped."
            ],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/deprecation/ (DeprecationRegistry, middleware, reporter),",
                "         GET /api/deprecations listing route,",
                "         @deprecated decorator.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — deprecation package with registry + decorator
    render_to(_HERE, "registry.py.tmpl", dest=registry_file, substitutions={})
    files_created.append(str(registry_file))

    # Step 2 — middleware
    middleware_file = app_dir / "deprecation" / "middleware.py"
    render_to(_HERE, "middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    # Step 3 — reporter
    reporter_file = app_dir / "deprecation" / "reporter.py"
    render_to(_HERE, "reporter.py.tmpl", dest=reporter_file, substitutions={})
    files_created.append(str(reporter_file))

    # Step 4 — HTTP listing route
    deprecation_route = app_dir / "api" / "routes" / "deprecation.py"
    render_to(_HERE, "deprecation_route.py.tmpl", dest=deprecation_route, substitutions={})
    files_created.append(str(deprecation_route))

    # Step 5 — register route in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 6 — patch main.py to add DeprecationMiddleware
    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file):
        files_modified.append(str(main_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        patch_settings_fields(
            config_file,
            fields=[
                (
                    "DEPRECATION_WARN_DAYS_BEFORE_SUNSET",
                    "DEPRECATION_WARN_DAYS_BEFORE_SUNSET: int = 30",
                ),
            ],
        )
        files_modified.append(str(config_file))

    # Step 8 — emit test
    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_ms(start),
    )


def _patch_routes_init(routes_init: Path) -> None:
    """Register the deprecation router in app/routes/__init__.py idempotently."""
    content = routes_init.read_text()
    import_line = "from app.api.routes.deprecation import router as deprecation_router"
    include_line = "api_router.include_router(deprecation_router)"
    if import_line in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)


def _patch_main(main_file: Path) -> bool:
    """Inject DeprecationMiddleware into app/main.py idempotently."""
    content = main_file.read_text()
    if "DeprecationMiddleware" in content:
        return False
    import_line = "from app.deprecation.middleware import DeprecationMiddleware"
    add_middleware_line = "app.add_middleware(DeprecationMiddleware)"
    if import_line in content:
        return False
    lines = content.splitlines(keepends=True)
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("from ") or line.startswith("import "):
            insert_idx = i + 1
    lines.insert(insert_idx, f"{import_line}\n")
    new_content = "".join(lines)
    if "app = FastAPI" in new_content and add_middleware_line not in new_content:
        new_content = new_content + f"\n{add_middleware_line}\n"
    main_file.write_text(new_content)
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_api_deprecation_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_api_deprecation_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_api_deprecation_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
