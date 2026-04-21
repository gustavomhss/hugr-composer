"""TOOL-012: add_rbac — ship RequestGuard + CurrentPrincipal primitives.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors `add_graceful_shutdown`):

1. Copy the framework-agnostic primitives
   `core.venous.auth.RequestGuard` and `core.venous.auth.CurrentPrincipal`
   into the generated project.
2. Copy the FastAPI adapter
   `core.venous._adapters.fastapi.RequestGuardAdapter` alongside them.
3. Emit a thin ``app/rbac.py`` (≤ 20 lines of glue) that calls
   ``RequestGuardAdapter.require(...)`` to build dependency-injected
   role guards.

The tool is idempotent: a second run detects the import chain in
``app/rbac.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_rbac import add_rbac

    result = add_rbac(ToolInput(project_dir="/path/to/project"))
    print(result.status)              # "success"
    print(result.imports_primitives)  # ["core.venous.auth.RequestGuard", ...]
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_auth_add_rbac",
    "description": (
        "Copy RequestGuard + CurrentPrincipal primitives + FastAPI adapter "
        "into the project and wire a ≤20-line app/rbac.py caller."
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


_GLUE = '''\
"""Wire RBAC into the FastAPI app.

Delegates to the `RequestGuard` + `CurrentPrincipal` primitives and the
FastAPI `RequestGuardAdapter` copied under `core/venous/` by
`add_rbac`. Hand-editing is safe but the file is re-emitted idempotently
on subsequent tool runs.
"""

from __future__ import annotations

from fastapi import Request

from core.venous._adapters.fastapi.RequestGuardAdapter import require
from core.venous.auth.CurrentPrincipal.CurrentPrincipal import anonymous
from core.venous.auth.RequestGuard.RequestGuard import RoleGuard


def resolve_principal(_request: Request):
    """Project-specific principal resolver. Default: anonymous."""
    return anonymous()


def require_roles(*roles: str):
    """Return a FastAPI dependency that admits only principals carrying `roles`."""
    return require(RoleGuard(*roles), principal=resolve_principal)
'''


def add_rbac(inp: ToolInput) -> ToolResult:
    """Add RBAC by delegating to the shipped primitives + adapter.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            notes=[
                "[dry_run] Would copy RequestGuard + CurrentPrincipal primitives + "
                "FastAPI adapter and write app/rbac.py calling require(RoleGuard(...))."
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
    rbac_file.write_text(_GLUE)
    files_created.append(str(rbac_file))

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
        files_modified=[],
        notes=[
            "Shipped primitives: RequestGuard (composable AND-guard), CurrentPrincipal (read-only identity).",
            "Shipped adapter: RequestGuardAdapter (maps GuardOutcome → 401/403/500).",
            "Wrote app/rbac.py — use require_roles('admin') in route dependencies.",
        ],
        next_steps=[
            "Replace resolve_principal in app/rbac.py with your real auth lookup.",
            "Use `dependencies=[Depends(require_roles('admin'))]` in routes.",
            "Compose additional guards (TenantGuard, AuthenticatedGuard) as needed.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
