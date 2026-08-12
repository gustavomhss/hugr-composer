"""TOOL-072: add_opa_integration — add Open Policy Agent (OPA) integration to a FastAPI project.

Writes an OPAClient (httpx-based, lazy import, circuit breaker), OPA Pydantic
models, OPAMiddleware, example Rego policy files, and two management endpoints
(POST /authz/opa/check, GET /authz/opa/health).  Patches app/core/config.py
with OPA_URL / OPA_ENABLED / OPA_POLICY_PATH / OPA_TIMEOUT_MS and registers
the router in app/routes/__init__.py.

OPA runs as a sidecar; this tool generates the CLIENT side only.
The tool is idempotent: a second run detects the ``OPAClient`` fingerprint in
``app/authz/opa_client.py`` and returns ``status="no_op"`` without touching any file.
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
    "name": "fastapi_auth_add_opa_integration",
    "description": (
        "Add Open Policy Agent (OPA) integration with circuit breaker, "
        "middleware, example Rego policies, and management endpoints."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_opa_integration",
    "imports_primitives": [],
    "imports_adapters": [],

}


def _elapsed_ms(start: float) -> int:
    return max(1, int((time.monotonic() - start) * 1000))


def _emit(template_name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(load_template(_HERE, template_name).template)


def add_opa_integration(inp: ToolInput) -> ToolResult:
    """Add OPA integration to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
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
    opa_client_file = app_dir / "authz" / "opa_client.py"
    if opa_client_file.exists() and "class OPAClient" in opa_client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["OPA integration already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would install OPAClient, OPAMiddleware, Rego policies, "
                "management routes, config fields."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    # Step 1: app/authz/__init__.py (preserve "skip if exists" semantics)
    authz_init = app_dir / "authz" / "__init__.py"
    authz_init.parent.mkdir(parents=True, exist_ok=True)
    if not authz_init.exists():
        authz_init.write_text(load_template(_HERE, "authz_init.py.tmpl").template)
    files_created.append(str(authz_init))

    # Step 2: app/authz/opa_models.py
    opa_models_file = app_dir / "authz" / "opa_models.py"
    _emit("opa_models.py.tmpl", opa_models_file)
    files_created.append(str(opa_models_file))

    # Step 3: app/authz/opa_client.py
    _emit("opa_client.py.tmpl", opa_client_file)
    files_created.append(str(opa_client_file))

    # Step 4: app/authz/opa_middleware.py
    opa_middleware_file = app_dir / "authz" / "opa_middleware.py"
    _emit("opa_middleware.py.tmpl", opa_middleware_file)
    files_created.append(str(opa_middleware_file))

    # Step 5: example Rego files
    policies_dir = app_dir / "authz" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "authz.rego").write_text(load_template(_HERE, "authz.rego.tmpl").template)
    (policies_dir / "data.json").write_text(load_template(_HERE, "data.json.tmpl").template)
    (policies_dir / "authz_test.rego").write_text(
        load_template(_HERE, "authz_test.rego.tmpl").template
    )
    files_created.append(str(policies_dir / "authz.rego"))
    files_created.append(str(policies_dir / "data.json"))
    files_created.append(str(policies_dir / "authz_test.rego"))

    # Step 6: app/api/routes/opa.py
    opa_routes_file = app_dir / "api" / "routes" / "opa.py"
    _emit("opa_routes.py.tmpl", opa_routes_file)
    files_created.append(str(opa_routes_file))

    # Step 7: Patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8: Patch routes __init__
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9: Patch requirements
    req_file = project / "requirements.txt"
    if req_file.exists():
        _patch_requirements(req_file)
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
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "OPA integration installed: OPAClient, OPAMiddleware, Rego policies.",
            "Client uses httpx (lazy import) with circuit breaker on OPA unavailability.",
            "Configure OPA_FAIL_OPEN=true for fail-open (allow on OPA down) or false for fail-closed.",
            "Example Rego policies in app/authz/policies/. Load them into your OPA sidecar.",
            "Use OPAMiddleware for request-level enforcement or OPAClient directly in routes.",
        ],
        next_steps=[
            "Start OPA sidecar: docker run -p 8181:8181 openpolicyagent/opa run --server",
            "Load policies: opa build app/authz/policies/authz.rego",
            "Set OPA_URL=http://localhost:8181 in your .env",
            "Set OPA_ENABLED=true and OPA_POLICY_PATH=authz/allow",
            "Optionally add OPAMiddleware to app/main.py for request-level enforcement.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    content = config_file.read_text()
    new_lines: list[str] = []
    fields = {
        "OPA_URL": '    OPA_URL: str = "http://localhost:8181"',
        "OPA_ENABLED": "    OPA_ENABLED: bool = False",
        "OPA_POLICY_PATH": '    OPA_POLICY_PATH: str = "authz/allow"',
        "OPA_TIMEOUT_MS": "    OPA_TIMEOUT_MS: int = 500",
        "OPA_FAIL_OPEN": "    OPA_FAIL_OPEN: bool = False",
    }
    for key, line in fields.items():
        if key not in content:
            new_lines.append(line)
    if not new_lines:
        return
    marker = "settings = Settings()"
    if marker in content:
        content = content.replace(marker, "\n".join(new_lines) + "\n\n" + marker)
    else:
        content = content.rstrip() + "\n" + "\n".join(new_lines) + "\n"
    config_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    content = routes_init.read_text()
    import_line = "from app.api.routes.opa import router as opa_router"
    include_line = "api_router.include_router(opa_router)"
    if import_line in content and include_line in content:
        return
    additions: list[str] = []
    if import_line not in content:
        additions.append(import_line)
    if include_line not in content:
        additions.append(include_line)
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(additions) + "\n"
    routes_init.write_text(content)


def _patch_requirements(req_file: Path) -> None:
    content = req_file.read_text()
    if "httpx" in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "httpx>=0.28.0\n"
    req_file.write_text(content)
