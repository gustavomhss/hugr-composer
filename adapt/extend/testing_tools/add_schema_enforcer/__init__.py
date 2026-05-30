"""TOOL-117: add_schema_enforcer — OpenAPI schema enforcement middleware.

Generates production-grade schema enforcement:
- Request/response validation against the live OpenAPI spec
- Rejection of extra fields (prevents mass assignment, OWASP API1)
- Drift detection: routes vs docs → shadow API alert
- Fuzz test generation from schema (property tests)
- Shadow API blocker for undocumented endpoints

Idempotent: a second run detects ``SchemaEnforcerMiddleware`` in
``app/middleware/schema_enforcer.py`` and returns ``status="no_op"``.

Generated files:
  - ``app/core/schema_enforcer.py``        spec loader + validator engine
  - ``app/middleware/schema_enforcer.py``  ASGI middleware + shadow blocker
  - ``tests/test_schema_fuzz.py``          generated fuzz tests

Patched files:
  - ``app/core/config.py``   SCHEMA_ENFORCER_* settings
  - ``app/main.py``          middleware registration
  - ``requirements.txt``     jsonschema>=4.23.0
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
    "name": "fastapi_testing_add_schema_enforcer",
    "description": (
        "Add OpenAPI schema enforcement middleware: validates every req/resp "
        "against the spec (rejects extra fields), detects shadow/zombie APIs "
        "(drift detection), generates Schemathesis-style fuzz tests, and blocks "
        "undocumented endpoints. Modes: enforce/detect/fuzz."
    ),
    "tags": ["extend", "testing_tools", "security"],
    "entry": "add_schema_enforcer",
}


def add_schema_enforcer(inp: ToolInput) -> ToolResult:
    """Add OpenAPI schema enforcement to a FastAPI project.

    Creates the schema enforcer engine, ASGI middleware, and a fuzz test
    file. Patches ``app/core/config.py`` with ``SCHEMA_ENFORCER_*`` settings
    and ``app/main.py`` to register the middleware.

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
                "Generate a base project first with fastapi_generate_project(...).",
            ],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    mw_file = app_dir / "middleware" / "schema_enforcer.py"
    if mw_file.exists() and "SchemaEnforcerMiddleware" in mw_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SchemaEnforcerMiddleware already present — schema enforcer already installed."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/core/schema_enforcer.py",
                "[dry_run] Would create app/middleware/schema_enforcer.py",
                "[dry_run] Would create tests/test_schema_fuzz.py",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    core_file = app_dir / "core" / "schema_enforcer.py"
    render_to(_HERE, "enforcer_core.py.tmpl", dest=core_file, substitutions={})
    files_created.append(str(core_file))

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    render_to(_HERE, "enforcer_middleware.py.tmpl", dest=mw_file, substitutions={})
    files_created.append(str(mw_file))

    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    fuzz_file = tests_dir / "test_schema_fuzz.py"
    render_to(_HERE, "schema_fuzz_tests.py.tmpl", dest=fuzz_file, substitutions={})
    files_created.append(str(fuzz_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        if "jsonschema" not in req_src:
            req_file.write_text(req_src.rstrip("\n") + "\njsonschema>=4.23.0\n")
            files_modified.append(str(req_file))

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

    emitted = tests_dir / "test_add_schema_enforcer_emitted.py"
    if not emitted.exists():
        render_to(_HERE, "test_add_schema_enforcer_emitted.py.tmpl", dest=emitted, substitutions={})
        files_created.append(str(emitted))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Schema enforcer installed. Default mode: DETECT (logs violations, does not block).",
            "Set SCHEMA_ENFORCER_MODE=enforce to activate hard rejection of extra fields.",
            "Shadow API detector alerts when a route exists but is not in the spec.",
            "Fuzz tests generated at tests/test_schema_fuzz.py — run with pytest.",
            "Set SCHEMA_ENFORCER_BLOCK_SHADOW=true to return 403 on undocumented routes.",
        ],
        next_steps=[
            "pip install 'jsonschema>=4.23.0'",
            "Set SCHEMA_ENFORCER_MODE=enforce in .env (options: enforce/detect/fuzz).",
            "Set SCHEMA_ENFORCER_SPEC_PATH=openapi.json to load schema from disk.",
            "Set SCHEMA_ENFORCER_BLOCK_SHADOW=true to block undocumented endpoints.",
            "Run pytest tests/test_schema_fuzz.py to execute generated fuzz tests.",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("SCHEMA_ENFORCER_MODE", 'SCHEMA_ENFORCER_MODE: str = "detect"'),
            ("SCHEMA_ENFORCER_SPEC_PATH", 'SCHEMA_ENFORCER_SPEC_PATH: str = ""'),
            ("SCHEMA_ENFORCER_BLOCK_SHADOW", "SCHEMA_ENFORCER_BLOCK_SHADOW: bool = False"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    src = main_file.read_text()
    if "register_schema_enforcer" in src:
        return

    import_line = (
        "\nfrom app.middleware.schema_enforcer import register_schema_enforcer"
        "  # noqa: F401 — schema enforcer\n"
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
        src = src[:end] + "\nregister_schema_enforcer(app)\n" + src[end:]
    else:
        src = src.rstrip("\n") + "\nregister_schema_enforcer(app)\n"

    main_file.write_text(src)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
