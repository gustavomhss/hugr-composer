"""TOOL-118: add_response_armor — five-layer response hardening.

Generates production-grade response security with:
1. ErrorSanitizer: generic messages to clients, full detail to structured logs
2. Constant-time auth comparisons via hmac.compare_digest wrappers
3. BREACH mitigation: random-length padding injected into compressed responses
4. Cache-Control enforcement: no-store/no-cache on sensitive responses
5. CRLF injection protection: strip CR/LF from all header values

Idempotent: a second run detects ``app/middleware/response_armor.py`` and
returns ``status="no_op"`` without touching any file.

Generated files:
  - ``app/middleware/response_armor.py``   main hardening middleware
  - ``app/core/response_armor.py``         error sanitizer + BREACH + CRLF utils
  - ``app/core/timing_safe.py``            constant-time comparison helpers

Patched files:
  - ``app/core/config.py``      RESPONSE_ARMOR_* fields inside Settings
  - ``app/main.py``             armor middleware registration
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, _elapsed_ms, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_response_armor",
    "description": (
        "Add five-layer response hardening: error sanitization (generic to client, "
        "full to logs), constant-time auth comparisons (hmac.compare_digest), "
        "BREACH mitigation (random padding), Cache-Control enforcement on sensitive "
        "responses, and CRLF injection protection in headers."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_response_armor",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_response_armor(inp: ToolInput) -> ToolResult:
    """Add five-layer response hardening to a FastAPI project."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    project = Path(inp.project_dir)

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

    files_created: list[str] = list(scaffolded)
    app_dir = project / "app"
    mw_file = app_dir / "middleware" / "response_armor.py"

    if mw_file.exists() and "ResponseArmorMiddleware" in mw_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["ResponseArmorMiddleware already present — response armor already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/middleware/response_armor.py, "
                "app/core/response_armor.py, and app/core/timing_safe.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    armor_core = app_dir / "core" / "response_armor.py"
    render_to(_HERE, "armor_core.py.tmpl", dest=armor_core, substitutions={})
    files_created.append(str(armor_core))

    timing_safe = app_dir / "core" / "timing_safe.py"
    render_to(_HERE, "timing_safe.py.tmpl", dest=timing_safe, substitutions={})
    files_created.append(str(timing_safe))

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    render_to(_HERE, "armor_middleware.py.tmpl", dest=mw_file, substitutions={})
    files_created.append(str(mw_file))

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
        notes=[
            "Response armor installed: 5-layer hardening active.",
            "ErrorSanitizer: 500 errors send generic message to client, full detail to logs.",
            "BREACH mitigation: random 0-32 byte padding injected into compressed responses.",
            "Cache-Control: no-store applied to all 4xx/5xx responses automatically.",
            "CRLF injection: CR/LF characters stripped from all response header values.",
        ],
        next_steps=[
            "Set RESPONSE_ARMOR_ENABLED=true in .env to activate.",
            "Set RESPONSE_ARMOR_SANITIZE_ERRORS=true to enable error sanitization.",
            "Set RESPONSE_ARMOR_TIMING_SAFE=true to enable timing-safe comparison logging.",
            "Import compare_tokens from app.core.timing_safe for all auth comparisons.",
            "Review logs for armor.error_sanitized events to monitor sanitization activity.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject ``RESPONSE_ARMOR_*`` fields inside the ``Settings`` class body."""
    src = config_file.read_text()
    if "RESPONSE_ARMOR_ENABLED" in src:
        return

    fields = (
        "    RESPONSE_ARMOR_ENABLED: bool = True\n"
        "    RESPONSE_ARMOR_SANITIZE_ERRORS: bool = True\n"
        "    RESPONSE_ARMOR_TIMING_SAFE: bool = True\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Register response armor middleware in ``app/main.py``."""
    src = main_file.read_text()
    if "register_response_armor" in src:
        return

    import_line = (
        "\nfrom app.middleware.response_armor import register_response_armor"
        "  # noqa: F401 — response armor\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_line,
        )
    else:
        src = import_line + src

    marker = "app = FastAPI("
    if marker in src:
        idx = src.find(marker)
        depth = 0
        end = idx
        for i in range(idx + len(marker), len(src)):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    end = i + 1
                    break
                depth -= 1
        src = src[:end] + "\nregister_response_armor(app)\n" + src[end:]
    else:
        src = src.rstrip("\n") + "\nregister_response_armor(app)\n"

    main_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_response_armor_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_response_armor_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


