"""TOOL-089: add_csrf_protection — CSRF tokens + SameSite cookies.

Generates ``app/security/__init__.py``, ``app/security/csrf.py``
(``CSRFProtection``: generate_token, validate_token, get_csrf_cookie),
``app/security/csrf_middleware.py`` (``CSRFMiddleware`` with double-submit
cookie + exempt path support), and ``app/api/routes/csrf.py``
(``GET /csrf/token``).

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.  No external dependencies — stdlib only (hmac, hashlib, secrets).

The tool is idempotent: a second run detects ``CSRFProtection`` in
``app/security/csrf.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.config_patcher import patch_settings_fields
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_csrf_protection",
    "description": "Add CSRF token protection with double-submit cookie pattern to FastAPI.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_csrf_protection",
}


def add_csrf_protection(inp: ToolInput) -> ToolResult:
    """Add CSRF protection to a FastAPI project."""
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
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    csrf_file = app_dir / "security" / "csrf.py"

    if csrf_file.exists() and "CSRFProtection" in csrf_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["CSRFProtection already present — CSRF protection already enabled, skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create csrf.py, csrf_middleware.py, routes/csrf.py, "
                "patch config.py and main.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    security_dir = app_dir / "security"
    security_dir.mkdir(parents=True, exist_ok=True)
    security_init = security_dir / "__init__.py"
    if not security_init.exists():
        render_to(_HERE, "security_init.py.tmpl", dest=security_init, substitutions={})
        files_created.append(str(security_init))

    render_to(_HERE, "csrf_core.py.tmpl", dest=csrf_file, substitutions={})
    files_created.append(str(csrf_file))

    middleware_file = security_dir / "csrf_middleware.py"
    render_to(_HERE, "csrf_middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        csrf_route = routes_dir / "csrf.py"
        render_to(_HERE, "csrf_route.py.tmpl", dest=csrf_route, substitutions={})
        files_created.append(str(csrf_route))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        patch_settings_fields(
            config_file,
            fields=[
                ("CSRF_ENABLED", "CSRF_ENABLED: bool = True"),
                (
                    "CSRF_SECRET_KEY",
                    'CSRF_SECRET_KEY: str = "change-this-csrf-secret-key-min-32-chars!"',
                ),
                ("CSRF_COOKIE_NAME", 'CSRF_COOKIE_NAME: str = "csrftoken"'),
                ("CSRF_HEADER_NAME", 'CSRF_HEADER_NAME: str = "X-CSRF-Token"'),
                ("CSRF_EXEMPT_PATHS", "CSRF_EXEMPT_PATHS: list[str] = []"),
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
                    execution_time_ms=_ms(start),
                )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "CSRF protection added: double-submit cookie pattern (no session required).",
            "CSRFMiddleware checks all unsafe methods (POST/PUT/PATCH/DELETE).",
            "Exempt paths configurable via CSRF_EXEMPT_PATHS (e.g. webhooks, health).",
            "GET /csrf/token endpoint issues a signed token for JS clients.",
            "No external dependencies — stdlib only (hmac, hashlib, secrets).",
            "⚠ CSRFMiddleware IS NOT auto-wired into app/main.py — the tool only "
            "writes a commented hint. You must uncomment app.add_middleware(CSRFMiddleware) "
            "to enable protection.",
        ],
        next_steps=[
            "Set CSRF_SECRET_KEY in .env (min 32 chars, random).",
            "Add CSRFMiddleware to app in main.py: app.add_middleware(CSRFMiddleware).",
            "Frontend: fetch /csrf/token, store in cookie, send X-CSRF-Token header.",
            "Exempt webhook paths: CSRF_EXEMPT_PATHS=['/webhooks/stripe', '/webhooks/github'].",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_main(main_file: Path) -> None:
    """Inject CSRF router registration comment into ``app/main.py``."""
    src = main_file.read_text()
    if "csrf_router" in src or "csrf.router" in src:
        return
    note = (
        "\n# CSRF protection router — added by add_csrf_protection tool\n"
        "# from app.api.routes.csrf import router as csrf_router\n"
        "# app.include_router(csrf_router)\n"
        "# app.add_middleware(CSRFMiddleware)  # from app.security.csrf_middleware\n"
    )
    src = src.rstrip("\n") + "\n" + note
    main_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_csrf_protection_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_csrf_protection_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
