"""TOOL-090: add_input_sanitization — HTML sanitization + XSS prevention.

Generates ``app/security/sanitizer.py`` (``InputSanitizer`` with lazy bleach
import, html.escape fallback, sql-char stripper), ``app/security/
sanitize_middleware.py`` (``SanitizeMiddleware`` that sanitizes JSON request
bodies up to a configurable depth) and ``app/security/validators.py``
(``SafeString`` Pydantic type and ``NoSQLInjection`` validator).

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.  Bleach is lazy-imported inside the emitted code so the app boots
even when bleach is not installed (falls back to ``html.escape``).

The tool is idempotent: a second run detects ``InputSanitizer`` in
``app/security/sanitizer.py`` and returns ``status="no_op"``.
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
    "name": "fastapi_resiliency_add_input_sanitization",
    "description": "Add HTML sanitization and XSS prevention middleware to FastAPI.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_input_sanitization",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_input_sanitization(inp: ToolInput) -> ToolResult:
    """Add input sanitization to a FastAPI project."""
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
    sanitizer_file = app_dir / "security" / "sanitizer.py"

    if sanitizer_file.exists() and "InputSanitizer" in sanitizer_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["InputSanitizer already present — input sanitization already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create sanitizer.py, sanitize_middleware.py, "
                "validators.py, patch config.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    security_dir = app_dir / "security"
    security_dir.mkdir(parents=True, exist_ok=True)
    security_init = security_dir / "__init__.py"
    if not security_init.exists():
        render_to(_HERE, "security_init.py.tmpl", dest=security_init, substitutions={})
        files_created.append(str(security_init))
    elif "InputSanitizer" not in security_init.read_text():
        _patch_security_init(security_init)
        files_modified.append(str(security_init))

    render_to(_HERE, "sanitizer_core.py.tmpl", dest=sanitizer_file, substitutions={})
    files_created.append(str(sanitizer_file))

    middleware_file = security_dir / "sanitize_middleware.py"
    render_to(_HERE, "sanitize_middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    validators_file = security_dir / "validators.py"
    render_to(_HERE, "sanitize_validators.py.tmpl", dest=validators_file, substitutions={})
    files_created.append(str(validators_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        patch_settings_fields(
            config_file,
            fields=[
                ("SANITIZE_ENABLED", "SANITIZE_ENABLED: bool = True"),
                ("SANITIZE_ALLOWED_TAGS", "SANITIZE_ALLOWED_TAGS: list[str] = []"),
                ("SANITIZE_MAX_DEPTH", "SANITIZE_MAX_DEPTH: int = 5"),
            ],
        )
        files_modified.append(str(config_file))

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
            "Input sanitization added: HTML sanitize + XSS prevention.",
            "bleach imported lazily — app boots without bleach (fallback: html.escape).",
            "SanitizeMiddleware sanitizes all JSON string fields in request bodies.",
            "SafeString Pydantic type auto-sanitizes on model validation.",
            "NoSQLInjection validator rejects common NoSQL injection patterns.",
            "⚠ SanitizeMiddleware IS NOT auto-wired into app/main.py — you must call "
            "app.add_middleware(SanitizeMiddleware) yourself for request bodies to be sanitized.",
            "⚠ escape_sql_chars IS NOT a SQL-injection defence — parameterised queries are. "
            "It is a defence-in-depth char-stripper only.",
        ],
        next_steps=[
            "pip install 'bleach>=6.0.0' (optional but recommended for allowlist support).",
            "Add SanitizeMiddleware: app.add_middleware(SanitizeMiddleware).",
            "Use SafeString type in Pydantic models for user-facing string fields.",
            "Configure SANITIZE_ALLOWED_TAGS in .env to control allowed HTML tags.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_security_init(dest: Path) -> None:
    """Add InputSanitizer export to an existing security __init__.py."""
    src = dest.read_text()
    if "InputSanitizer" in src:
        return
    addition = "\nfrom app.security.sanitizer import InputSanitizer  # noqa: F401\n"
    dest.write_text(src.rstrip("\n") + addition)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_input_sanitization_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_input_sanitization_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


