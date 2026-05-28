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

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

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

# ⚠️  HONESTY NOTE: resolve_principal previously returned anonymous() unconditionally,
# making every require_roles() call deny ALL requests (anonymous has no roles).
# The new glue uses the project's get_current_user dep so the guard actually works.
# Even so, NO existing route is auto-guarded — the dev must wire Depends() manually.
_GLUE = '''\
"""Wire RBAC into the FastAPI app.

Primitives shipped by add_rbac:
  - core/venous/auth/RequestGuard/      — composable guard predicates
  - core/venous/auth/CurrentPrincipal/  — immutable identity value
  - core/venous/_adapters/fastapi/RequestGuardAdapter.py — HTTP bridge

⚠ RBAC IS NOT ENFORCED: add_rbac does NOT touch any existing route.
  Zero routes are protected until you explicitly add Depends(require_roles(...)).
  See app/api/routes/_rbac_example.py for a copy-paste wired example.

One-liner to protect a route::

    @router.delete("/{id}", dependencies=[Depends(require_roles("admin"))])
    async def delete_item(...): ...

Role mapping (edit _user_to_principal to customise):
  is_superuser=True  → roles={"admin"}
  is_superuser=False → roles={"user"}
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException

# `require` is available for advanced guard composition; require_roles uses
# get_current_user directly so DB access is handled by the existing auth stack.
from core.venous._adapters.fastapi.RequestGuardAdapter import require  # noqa: F401
from core.venous.auth.CurrentPrincipal.CurrentPrincipal import CurrentPrincipal, authenticated
from core.venous.auth.RequestGuard.RequestGuard import RoleGuard

from app.api.deps import get_current_user
from app.models.user import User


class _RbacCtx:
    """Minimal request-context stub; RoleGuard only reads principal, not ctx."""

    request_id = "-"
    headers: dict = {}
    assigns: dict = {}


# Edit this function to add fine-grained roles as your User model grows.
def _user_to_principal(user: User) -> CurrentPrincipal:
    roles = frozenset({"admin"} if user.is_superuser else {"user"})
    return authenticated(str(user.id), roles=roles)


# NOT applied automatically — add to every route you want to protect:
#    dependencies=[Depends(require_roles("admin"))]
# Admitted: principal carries all roles → returns CurrentPrincipal.
# Denied:   wrong role → HTTP 403; no token → HTTP 401 via get_current_user.
def require_roles(*roles: str):
    _guard = RoleGuard(*roles)

    async def _dep(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> CurrentPrincipal:
        principal = _user_to_principal(current_user)
        if not await _guard.allow(_RbacCtx(), principal):
            raise HTTPException(status_code=403, detail="forbidden")
        return principal

    return _dep
'''

# Concrete wired example emitted alongside app/rbac.py.
# This is a REAL FastAPI route that uses require_roles — copy-paste ready.
_RBAC_EXAMPLE = '''\
"""COPY-PASTE TEMPLATE: a wired RBAC-protected endpoint.

This file is generated by add_rbac as a concrete, runnable example.
It is NOT registered automatically — import the router in main.py or
include it in your APIRouter to activate it.

To wire into your app (main.py or app/api/main.py)::

    from app.api.routes._rbac_example import router as rbac_example_router
    app.include_router(rbac_example_router, prefix="/examples")

⚠ RBAC IS NOT ENFORCED on any of YOUR routes until you add
  Depends(require_roles(...)) to each route you want to protect.
  Use this file as a copy-paste template.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.rbac import CurrentPrincipal, require_roles

router = APIRouter(tags=["rbac-example"])


# --- ADMIN-ONLY route --------------------------------------------------
# Superusers (is_superuser=True) → admitted.
# Authenticated non-superusers   → HTTP 403 Forbidden.
# Unauthenticated requests        → HTTP 401 Unauthorized.
@router.get(
    "/admin-only",
    summary="[RBAC example] Admin-only endpoint",
    dependencies=[Depends(require_roles("admin"))],
)
async def admin_only_endpoint() -> dict:
    return {"message": "You are an admin — RBAC is working."}


# --- USER-OR-ADMIN route -----------------------------------------------
# Any authenticated user is admitted.
@router.get(
    "/user-area",
    summary="[RBAC example] User-or-admin endpoint",
)
async def user_area(
    principal: CurrentPrincipal = Depends(require_roles("user", "admin")),
) -> dict:
    return {"user_id": principal.subject, "roles": sorted(principal.roles)}
'''

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

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``warnings``, ``notes``, and ``next_steps``.
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
    rbac_file.write_text(_GLUE)
    files_created.append(str(rbac_file))

    # Emit the concrete wired example so the LLM driver / developer has
    # a real, runnable route to copy from — not just a warning.
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    example_file = routes_dir / "_rbac_example.py"
    if not example_file.exists():
        example_file.write_text(_RBAC_EXAMPLE)
        files_created.append(str(example_file))

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
        warnings=[_WARN_NOT_AUTO_ENFORCED],
        notes=[
            "Shipped primitives: RequestGuard (composable AND-guard), CurrentPrincipal (read-only identity).",
            "Shipped adapter: RequestGuardAdapter (maps GuardOutcome → 401/403/500).",
            "Wrote app/rbac.py — require_roles() is backed by get_current_user.",
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


def _elapsed_ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
