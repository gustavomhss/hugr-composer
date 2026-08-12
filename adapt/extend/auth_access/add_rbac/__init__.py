"""TOOL-012: add_rbac — ship RequestGuard + CurrentPrincipal primitives.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors `add_graceful_shutdown`):

1. Copy the framework-agnostic primitives
   `core.venous.auth.RequestGuard` and `core.venous.auth.CurrentPrincipal`
   into the generated project.
2. Copy the FastAPI adapter
   `core.venous._adapters.fastapi.RequestGuardAdapter` alongside them.
3. Emit a thin ``app/rbac.py`` (≤ 20 lines of glue) that wires
   ``require_roles()`` through the project's existing ``get_current_user``
   dependency so role enforcement is backed by real auth.

HONESTY CONTRACT: The tool reports ``status="success"`` only for file
emission. It always includes ``warnings`` that RBAC is NOT auto-enforced
on any existing route — the developer must add
``dependencies=[Depends(require_roles("admin"))]`` explicitly.

The tool is idempotent: a second run detects the import chain in
``app/rbac.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_rbac import add_rbac

    result = add_rbac(ToolInput(project_dir="/path/to/project"))
    print(result.status)    # "success"
    print(result.warnings)  # ["RBAC is NOT auto-enforced on any existing route..."]
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import load_template
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_auth_add_rbac",
    "description": (
        "Copy RequestGuard + CurrentPrincipal primitives + FastAPI adapter "
        "into the project and wire a ≤20-line app/rbac.py caller backed by "
        "the project's existing get_current_user dependency."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_rbac",
    "imports_primitives": [
        "core.venous.auth.RequestGuard",
        "core.venous.auth.CurrentPrincipal",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.RequestGuardAdapter",
    ],
}


def _glue_body() -> str:
    # Externalized to templates/glue.py.tmpl; no substitutions required.
    return load_template(_HERE, "glue.py.tmpl").template


def _rbac_example_body() -> str:
    # Externalized to templates/rbac_example.py.tmpl; no substitutions required.
    return load_template(_HERE, "rbac_example.py.tmpl").template


def _rbac_router_body() -> str:
    # Externalized to templates/rbac_router.py.tmpl; no substitutions required.
    return load_template(_HERE, "rbac_router.py.tmpl").template


def _patch_routes_init(routes_init: Path) -> bool:
    """Register the rbac router in ``app/routes/__init__.py`` idempotently.

    Returns ``True`` when the registry is modified, ``False`` when the
    import line is already present.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.rbac import router as rbac_router"
    include_line = "api_router.include_router(rbac_router)"
    if import_line in src:
        return False
    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)
    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


# Warning text emitted in every successful ToolResult so callers cannot miss it.
# All-caps prefix guarantees LLM drivers and log scanners cannot mistake this
# for a success: the tool ships the MECHANISM, not the POLICY.
_WARN_NOT_AUTO_ENFORCED = (
    "⚠ RBAC IS NOT ENFORCED: no route is protected until you add "
    "Depends(require_roles(...)) to each route you want to guard. "
    "This tool ships the mechanism, not the policy. "
    "See app/api/routes/_rbac_example.py for a fully wired copy-paste example."
)


def add_rbac(inp: ToolInput) -> ToolResult:
    """Add RBAC by delegating to the shipped primitives + adapter.

    Ships the RequestGuard + CurrentPrincipal primitives and emits
    ``app/rbac.py`` with a ``require_roles()`` dependency that is backed by
    the project's existing ``get_current_user``.

    HONESTY: always emits a warning that RBAC is not auto-enforced and that
    the developer must wire ``Depends(require_roles(...))`` manually.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        Prereq.ROUTES_INIT,
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

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    rbac_file = app_dir / "rbac.py"

    if rbac_file.exists() and "RequestGuardAdapter" in rbac_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RBAC already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            warnings=[_WARN_NOT_AUTO_ENFORCED],
            notes=[
                "[dry_run] Would copy RequestGuard + CurrentPrincipal primitives + "
                "FastAPI adapter and write app/rbac.py with require_roles() backed "
                "by get_current_user."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=[
            "core.venous.auth.RequestGuard",
            "core.venous.auth.CurrentPrincipal",
        ],
        adapters=["core.venous._adapters.fastapi.RequestGuardAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    rbac_file.write_text(_glue_body())
    files_created.append(str(rbac_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    example_file = routes_dir / "_rbac_example.py"
    if not example_file.exists():
        example_file.write_text(_rbac_example_body())
        files_created.append(str(example_file))

    # Emit a real, mounted RBAC router (prefix /rbac) so role enforcement is
    # exercised end-to-end out of the box, and register it in the project's
    # route registry.
    files_modified: list[str] = []
    rbac_router_file = routes_dir / "rbac.py"
    if not rbac_router_file.exists():
        rbac_router_file.write_text(_rbac_router_body())
        files_created.append(str(rbac_router_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists() and _patch_routes_init(routes_init):
        files_modified.append(str(routes_init))

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
        warnings=[_WARN_NOT_AUTO_ENFORCED],
        notes=[
            "Shipped primitives: RequestGuard (composable AND-guard), CurrentPrincipal (read-only identity).",
            "Shipped adapter: RequestGuardAdapter (maps GuardOutcome → 401/403/500).",
            "Wrote app/rbac.py — require_roles() is backed by get_current_user.",
            "Wrote app/api/routes/rbac.py — a mounted /rbac router (admin-only + me) "
            "registered in app/routes/__init__.py.",
            "Wrote app/api/routes/_rbac_example.py — a REAL wired endpoint you can copy-paste.",
            "Role mapping: is_superuser=True → {'admin'}, else → {'user'}.",
            "Edit _user_to_principal in app/rbac.py to customise the role mapping.",
        ],
        next_steps=[
            "STEP 1 — copy the pattern from app/api/routes/_rbac_example.py into your own routes.",
            "STEP 2 — add `dependencies=[Depends(require_roles('admin'))]` to every route that needs protection.",
            "STEP 3 — verify: superuser token → 200, non-superuser token → 403, no token → 401.",
            "STEP 4 — edit _user_to_principal in app/rbac.py to add fine-grained roles as your User model grows.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


