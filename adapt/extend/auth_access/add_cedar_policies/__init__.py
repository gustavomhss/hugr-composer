"""TOOL-071: add_cedar_policies — add AWS Cedar policy-as-code authorization to a FastAPI project.

Installs a CedarEngine with file-based policy loading, AuthzRequest/AuthzResponse
Pydantic models, a CedarAuthzMiddleware that enforces every request against the
loaded policy set, three example .cedar policy files, and two API endpoints
(POST /authz/check, GET /authz/policies).

The tool is idempotent: a second run detects the ``CedarEngine`` fingerprint in
``app/authz/engine.py`` and returns ``status="no_op"`` without touching any file.

Cedar runs AFTER RBAC: if both are installed the RBAC check happens first and
Cedar provides additional ABAC enforcement.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import load_template
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_auth_add_cedar_policies",
    "description": (
        "Add AWS Cedar policy-as-code ABAC authorization to a FastAPI project. "
        "Generates CedarEngine, middleware, example .cedar policies, and /authz endpoints."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_cedar_policies",
    "imports_primitives": [],
    "imports_adapters": [],

}


def _elapsed_ms(start: float) -> int:
    return max(1, int((time.monotonic() - start) * 1000))


def _emit(template_name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(load_template(_HERE, template_name).template)


def add_cedar_policies(inp: ToolInput) -> ToolResult:
    """Add AWS Cedar policy-as-code authorization to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
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

    app_dir = project / "app"
    engine_file = app_dir / "authz" / "engine.py"
    if engine_file.exists() and "class CedarEngine" in engine_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Cedar authz engine already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would install Cedar authz: engine, models, middleware, "
                "example policies, /authz routes."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    # Step 1-4: app/authz/{__init__,engine,models,middleware}.py
    authz_init = app_dir / "authz" / "__init__.py"
    _emit("authz_init.py.tmpl", authz_init)
    files_created.append(str(authz_init))

    _emit("engine.py.tmpl", engine_file)
    files_created.append(str(engine_file))

    models_file = app_dir / "authz" / "models.py"
    _emit("models.py.tmpl", models_file)
    files_created.append(str(models_file))

    middleware_file = app_dir / "authz" / "middleware.py"
    _emit("middleware.py.tmpl", middleware_file)
    files_created.append(str(middleware_file))

    # Step 5: example .cedar policy files
    policies_dir = app_dir / "authz" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    for src_tmpl, name in (
        ("admin_full_access.cedar.tmpl", "admin_full_access.cedar"),
        ("owner_read_write.cedar.tmpl", "owner_read_write.cedar"),
        ("default_deny.cedar.tmpl", "default_deny.cedar"),
    ):
        out = policies_dir / name
        out.write_text(load_template(_HERE, src_tmpl).template)
        files_created.append(str(out))

    # Step 6: app/api/routes/authz.py
    authz_routes = app_dir / "api" / "routes" / "authz.py"
    _emit("authz_routes.py.tmpl", authz_routes)
    files_created.append(str(authz_routes))

    # Step 7: Patch app/core/config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8: Patch app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9: Patch requirements.txt
    req_file = project / "requirements.txt"
    if req_file.exists():
        _patch_requirements(req_file)
        files_modified.append(str(req_file))

    # Validate every generated .py file
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
            "Cedar authz installed: engine, models, middleware, example policies.",
            "Set CEDAR_ENABLED=true in your .env to activate the middleware.",
            "Add CEDAR_POLICY_DIR=app/authz/policies to point at your .cedar files.",
            "Use POST /authz/check to evaluate a policy decision programmatically.",
            "Cedar coexists with RBAC: RBAC check runs first, Cedar provides ABAC layer.",
            "cedarpy is imported lazily — app boots without it installed.",
        ],
        next_steps=[
            "pip install cedarpy>=0.4.0",
            "Set CEDAR_ENABLED=true in your .env / Settings.",
            "Set CEDAR_POLICY_DIR=app/authz/policies (or absolute path).",
            "Edit the example .cedar files in app/authz/policies/ for your domain.",
            "Restart the application to load the /authz router and middleware.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("CEDAR_ENABLED", "CEDAR_ENABLED: bool = False"),
            ("CEDAR_POLICY_DIR", 'CEDAR_POLICY_DIR: str = "app/authz/policies"'),
            ("CEDAR_DEFAULT_EFFECT", 'CEDAR_DEFAULT_EFFECT: str = "deny"'),
        ],
    )


def _patch_routes_init(routes_init: Path) -> None:
    content = routes_init.read_text()
    import_line = "from app.api.routes.authz import router as authz_router"
    include_line = "api_router.include_router(authz_router)"
    if import_line in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)


def _patch_requirements(req_file: Path) -> None:
    content = req_file.read_text()
    if "cedarpy" not in content:
        if not content.endswith("\n"):
            content += "\n"
        content += "cedarpy>=0.4.0\n"
        req_file.write_text(content)
