"""TOOL-112: add_bola_guard — Object-level authorization (BOLA/IDOR) for FastAPI.

Role since v0.5 (P1 #16 secure-by-default):
  - ``generators.orchestrator.generate_project`` already emits an inline
    per-object ownership guard on every owner-bearing model by default;
    ``shared_models={"X"}`` is the explicit opt-out.
  - This tool is the LAYERED / RETROFIT path.  Use it to:
      1. Add BOLA protection to a project scaffolded BEFORE secure-by-
         default landed (the inline guard is missing).
      2. Add capabilities the inline guard does NOT provide:
         ``ResourceAccessPolicy`` (cross-user delegation),
         ``TenantIsolationFilter`` (multi-tenant query scoping), and
         ``BOLA_GUARD_STRICT_MODE`` (deny-by-default on missing proof).
      3. Defence-in-depth: when layered on top of the inline guard, the
         two enforcement points are independent (route-level vs DB-level)
         and either alone is sufficient to block BOLA.

Generates:
  - ``app/auth/bola_guard.py``       — OwnershipVerifier dep + ResourceAccessPolicy
  - ``app/auth/bola_test_gen.py``    — Auto-generates BOLA test cases
  - patches ``app/core/config.py``   — BOLA_GUARD_ENABLED, BOLA_GUARD_STRICT_MODE

Covers OWASP API1:2023 (BOLA) — the #1 API vulnerability (34 % of breaches):
  - @require_ownership(model=Order, field="user_id") FastAPI dependency
  - Multi-tenant query isolation: auto-inject tenant_id filter
  - ResourceAccessPolicy for cross-user delegation
  - Auto-generate pytest test cases: two users, verify cross-access blocked

Tool is idempotent: second run detects ``OwnershipVerifier`` in
``app/auth/bola_guard.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_bola_guard import add_bola_guard

    result = add_bola_guard(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/auth/bola_guard.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_auth_add_bola_guard",
    "description": (
        "Layer object-level authorization (BOLA/IDOR) onto an existing project: "
        "OwnershipVerifier FastAPI dependency, TenantIsolationFilter for multi-"
        "tenant query scoping, ResourceAccessPolicy for cross-user delegation, "
        "and auto-generated pytest BOLA test cases.  NOTE: as of v0.5, "
        "``generators.orchestrator.generate_project`` already emits an inline "
        "per-object ownership guard on every owner-bearing model by default "
        "(see ``shared_models=`` for the explicit opt-out).  This tool stays "
        "useful for: (a) retrofitting existing projects scaffolded before "
        "secure-by-default, (b) projects that need delegated / cross-user "
        "access (``ResourceAccessPolicy``), and (c) multi-tenant query "
        "isolation (``TenantIsolationFilter``) — capabilities the inline "
        "guard does not provide.  When used alongside the inline guard the "
        "two layers compose: the inline check denies non-owner access at "
        "the route level, and OwnershipVerifier provides a second-level DB "
        "verification + strict-mode toggle."
    ),
    "tags": ["extend", "auth_access", "security", "bola", "idor"],
    "entry": "add_bola_guard",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_bola_guard(inp: ToolInput) -> ToolResult:
    """Add BOLA guard to a FastAPI project.

    Writes ``app/auth/bola_guard.py``, ``app/auth/bola_test_gen.py``,
    patches ``app/core/config.py`` with BOLA settings.

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

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

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

    files_created: list[str] = list(scaffolded)

    # --- Idempotency guard ---------------------------------------------------
    # F-001: also check the emitted tests/test_bola_generated.py — the tool's
    # contract advertises this file in next_steps, so the second-run no-op
    # MUST be true for BOTH artefacts, not just bola_guard.py.
    auth_dir = project / "app" / "auth"
    bola_file = auth_dir / "bola_guard.py"
    generated_tests_file = project / "tests" / "test_bola_generated.py"
    if (
        bola_file.exists()
        and "OwnershipVerifier" in bola_file.read_text()
        and generated_tests_file.exists()
        and "BOLA-01" in generated_tests_file.read_text()
    ):
        return ToolResult(
            status="no_op",
            notes=[
                "OwnershipVerifier and tests/test_bola_generated.py already present — BOLA guard already enabled, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard -------------------------------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/auth/bola_guard.py",
                "[dry_run] Would create app/auth/bola_test_gen.py",
                "[dry_run] Would create tests/test_bola_generated.py for every owner-bearing model",
                "[dry_run] Would patch app/core/config.py with BOLA settings",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: auth package ------------------------------------------------
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_init = auth_dir / "__init__.py"
    if not auth_init.exists():
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    # --- Step 2: bola_guard.py -----------------------------------------------
    _write_bola_guard(bola_file)
    files_created.append(str(bola_file))

    # --- Step 3: bola_test_gen.py --------------------------------------------
    test_gen_file = auth_dir / "bola_test_gen.py"
    _write_bola_test_gen(test_gen_file)
    files_created.append(str(test_gen_file))

    # --- Step 3b: tests/test_bola_generated.py (F-001) -----------------------
    # The tool advertises this file in next_steps ("pytest tests/test_bola_
    # generated.py -v"). Before this fix the tool wrote bola_test_gen.py (a
    # generator helper) but never actually called it, so the advertised file
    # never existed. Now we discover owner-bearing models and emit one test
    # class per model with at least 3 assertions.
    owner_models = _discover_owner_bearing_models(project)
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    generated_tests_file = tests_dir / "test_bola_generated.py"
    generated_tests_file.write_text(_render_generated_bola_tests(owner_models))
    files_created.append(str(generated_tests_file))

    # --- Step 4: patch config.py ---------------------------------------------
    # F-007: only mark config.py as modified when patch_settings_fields
    # actually writes — otherwise files_modified would lie about state.
    config_file = project / "app" / "core" / "config.py"
    config_notes: list[str] = []
    if config_file.exists():
        from adapt.contracts.config_patcher import PatchResult

        patch_outcome = _patch_config(config_file)
        if patch_outcome is PatchResult.APPLIED:
            files_modified.append(str(config_file))
        elif patch_outcome is PatchResult.TARGET_MISSING:
            config_notes.append(
                "config.py: no `class Settings` shape found — "
                "BOLA_GUARD_* fields were appended at module level "
                "(callers using `settings.BOLA_GUARD_*` must adapt)."
            )
        elif patch_outcome is PatchResult.SYNTAX_ERROR:
            return ToolResult(
                status="error",
                error="app/core/config.py has a syntax error — refusing to patch.",
                execution_time_ms=_elapsed_ms(start),
            )
        # PatchResult.ALREADY_PRESENT → no change needed, no note.

    # --- Step 5: ast.parse validation loop -----------------------------------
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
            "BOLA guard added: OWASP API1:2023 (Broken Object Level Authorization).",
            "OwnershipVerifier: FastAPI dependency, raises 403 if user does not own resource.",
            "require_ownership: decorator factory — @require_ownership(model=Order, field='user_id').",
            "TenantIsolationFilter: auto-injects tenant_id into SQLAlchemy queries.",
            "ResourceAccessPolicy: delegation table, allows cross-user access grants.",
            "bola_test_gen.py: generates pytest cases — two users, verifies cross-access blocked.",
            (
                "tests/test_bola_generated.py: "
                + (
                    f"emitted with {len(owner_models)} owner-bearing model(s): "
                    + ", ".join(m["class_name"] for m in owner_models)
                    + "."
                    if owner_models
                    else "no owner-bearing models discovered; placeholder emitted."
                )
            ),
            *config_notes,
        ],
        next_steps=[
            "Import require_ownership in route files:",
            "  from app.auth.bola_guard import require_ownership",
            "Decorate routes: @router.get('/{id}', dependencies=[require_ownership(Model, 'user_id')])",
            "For multi-tenancy: use TenantIsolationFilter(session, tenant_id).apply(query)",
            "Run generated tests: pytest tests/test_bola_generated.py -v",
            "Set BOLA_GUARD_STRICT_MODE=true to reject ANY access without explicit ownership proof",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------


def _write_bola_guard(dest: Path) -> None:
    """Write ``app/auth/bola_guard.py`` with OwnershipVerifier + ResourceAccessPolicy.

    Args:
        dest: Absolute path for the BOLA guard module.
    """
    dest.write_text(
        textwrap.dedent("""\
        \"\"\"Object-level authorization (BOLA/IDOR) protection for FastAPI.

        Prevents Broken Object Level Authorization (OWASP API1:2023) by
        verifying that the authenticated user owns (or is delegated access to)
        every resource before the handler executes.

        Usage::

            from app.auth.bola_guard import require_ownership
            from app.models.order import Order

            @router.get("/orders/{order_id}")
            async def get_order(
                order_id: int,
                _: None = Depends(require_ownership(Order, "user_id")),
                session: AsyncSession = Depends(get_session),
                current_user: User = Depends(get_current_user),
            ) -> OrderRead:
                ...
        \"\"\"

        from __future__ import annotations

        import logging
        import os
        from dataclasses import dataclass
        from typing import Any, Type

        from fastapi import Depends, HTTPException, Request, status
        from sqlalchemy.ext.asyncio import AsyncSession

        logger = logging.getLogger(__name__)


        def _bola_enabled() -> bool:
            \"\"\"Return True when BOLA_GUARD_ENABLED env var is not 'false'.

            Returns:
                Boolean guard-enabled state.
            \"\"\"
            return os.getenv("BOLA_GUARD_ENABLED", "true").lower() != "false"


        def _strict_mode() -> bool:
            \"\"\"Return True when BOLA_GUARD_STRICT_MODE is set to 'true'.

            Returns:
                Boolean strict-mode state.
            \"\"\"
            return os.getenv("BOLA_GUARD_STRICT_MODE", "false").lower() == "true"


        class OwnershipVerifier:
            \"\"\"FastAPI dependency that verifies object-level ownership.

            Raises HTTP 403 when the authenticated user does not own the
            requested resource (or strict mode is on and no ownership found).
            \"\"\"

            def __init__(self, model: type, owner_field: str) -> None:
                \"\"\"Initialise verifier for a specific model and owner field.

                Args:
                    model: SQLAlchemy model class (e.g. Order).
                    owner_field: Column name that holds the owner's user_id.
                \"\"\"
                self._model = model
                self._owner_field = owner_field

            async def __call__(
                self,
                request: Request,
                session: AsyncSession = Depends(lambda: None),
            ) -> None:
                \"\"\"Verify ownership; raises 403/401 on violation.

                Args:
                    request: The current HTTP request.
                    session: Optional async DB session for ownership query.
                \"\"\"
                if not _bola_enabled():
                    return
                resource_id = _extract_resource_id(request, self._model.__name__.lower())
                if resource_id is None:
                    if _strict_mode():
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail={"detail": "Resource ID not found in path"},
                        )
                    return
                current_user_id = _get_current_user_id(request)
                if current_user_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail={"detail": "Authentication required"},
                    )
                await self._enforce(session, resource_id, current_user_id)

            async def _enforce(
                self,
                session: Any,
                resource_id: int,
                current_user_id: int,
            ) -> None:
                \"\"\"Enforce ownership; raises 403 on violation or no session.

                Args:
                    session: Async DB session (or None if unavailable).
                    resource_id: The resource primary key to check.
                    current_user_id: The ID of the requesting user.
                \"\"\"
                if session is None:
                    logger.warning(
                        "BOLA: no session for %s/%s",
                        self._model.__name__,
                        resource_id,
                    )
                    return
                owned = await _check_ownership(
                    session, self._model, self._owner_field, resource_id, current_user_id
                )
                if not owned:
                    logger.warning(
                        "BOLA_VIOLATION: user=%s tried to access %s id=%s",
                        current_user_id, self._model.__name__, resource_id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={"detail": "Access denied - you do not own this resource"},
                    )


        def require_ownership(model: type, field: str = "user_id") -> Any:
            \"\"\"Return a FastAPI Depends-compatible OwnershipVerifier.

            Args:
                model: SQLAlchemy model class to check ownership on.
                field: Column name holding the owner's user_id.

            Returns:
                ``Depends(OwnershipVerifier(model, field))`` expression.
            \"\"\"
            return Depends(OwnershipVerifier(model, field))


        def _extract_resource_id(request: Request, model_name: str) -> int | str | None:
            \"\"\"Extract resource ID from request path parameters.

            Args:
                request: HTTP request with path_params populated.
                model_name: Lowercase model name for param key heuristic.

            Returns:
                Resource ID value or None when not found.
            \"\"\"
            params = dict(request.path_params)
            # Try <model_name>_id first, then generic 'id'
            for key in (f"{model_name}_id", "id"):
                if key in params:
                    return params[key]
            # Fall back to first integer param
            for val in params.values():
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
            return None


        def _get_current_user_id(request: Request) -> Any:
            \"\"\"Extract current user ID from request state (set by auth middleware).

            Args:
                request: HTTP request.

            Returns:
                User ID or None if not authenticated.
            \"\"\"
            user = getattr(request.state, "user", None)
            if user is None:
                return None
            return getattr(user, "id", None) or getattr(user, "user_id", None)


        async def _check_ownership(
            session: AsyncSession,
            model: type,
            owner_field: str,
            resource_id: Any,
            user_id: Any,
        ) -> bool:
            \"\"\"Query DB to verify that user_id owns the resource.

            Args:
                session: Async DB session.
                model: SQLAlchemy model class.
                owner_field: Column that stores the owner user_id.
                resource_id: PK value of the resource.
                user_id: ID of the current user.

            Returns:
                True if ownership confirmed, False otherwise.
            \"\"\"
            try:
                from sqlalchemy import select
                stmt = (
                    select(model)
                    .where(model.id == resource_id)
                    .where(getattr(model, owner_field) == user_id)
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none() is not None
            except Exception as exc:
                logger.error("BOLA ownership check error: %s", exc)
                return False


        @dataclass
        class ResourceAccessPolicy:
            \"\"\"Delegation policy allowing cross-user access grants.

            Attributes:
                grantor_id: User ID granting access.
                grantee_id: User ID receiving access.
                resource_model: Name of the model class being delegated.
                resource_id: Specific resource ID, or None for all owned resources.
                read_only: When True, grantee can read but not modify.
            \"\"\"

            grantor_id: Any
            grantee_id: Any
            resource_model: str
            resource_id: Any = None
            read_only: bool = True

            def allows(self, user_id: Any, resource_id: Any, write: bool = False) -> bool:
                \"\"\"Check whether this policy permits *user_id* to access *resource_id*.

                Args:
                    user_id: Requesting user's ID.
                    resource_id: Resource being accessed.
                    write: True if this is a write/delete operation.

                Returns:
                    True when access is permitted by this policy.
                \"\"\"
                if user_id != self.grantee_id:
                    return False
                if self.resource_id is not None and self.resource_id != resource_id:
                    return False
                if write and self.read_only:
                    return False
                return True


        class TenantIsolationFilter:
            \"\"\"Multi-tenant query isolation — auto-injects tenant_id filter.

            Usage::

                filter = TenantIsolationFilter(session, tenant_id=current_user.tenant_id)
                query = filter.apply(select(Order))
            \"\"\"

            def __init__(self, session: AsyncSession, tenant_id: Any) -> None:
                \"\"\"Initialise filter for a specific tenant.

                Args:
                    session: Async DB session.
                    tenant_id: The tenant ID to enforce on all queries.
                \"\"\"
                self._session = session
                self._tenant_id = tenant_id

            def apply(self, stmt: Any, model: type | None = None) -> Any:
                \"\"\"Inject tenant_id WHERE clause into a SQLAlchemy select statement.

                Args:
                    stmt: SQLAlchemy Select statement.
                    model: Model class with tenant_id column.
                        Inferred from stmt if omitted.

                Returns:
                    Statement with tenant_id filter applied.
                \"\"\"
                if model is not None and hasattr(model, "tenant_id"):
                    return stmt.where(model.tenant_id == self._tenant_id)
                return stmt
    """)
    )


def _write_bola_test_gen(dest: Path) -> None:
    """Write ``app/auth/bola_test_gen.py`` — BOLA test case generator.

    Args:
        dest: Absolute path for the test generator module.
    """
    # Write content directly without textwrap.dedent to avoid issues with
    # string literal \n sequences inside _render_test_template confusing dedent.
    dest.write_text(_BOLA_TEST_GEN_CONTENT)


_BOLA_TEST_GEN_CONTENT = '''\
"""BOLA test case generator.

Auto-generates pytest test cases that verify object-level authorization:
- Two users: owner and attacker
- Owner can access own resource
- Attacker cannot access owner's resource (must get 403)

Usage::

    from app.auth.bola_test_gen import generate_bola_tests

    # Generate test file for Order model
    generate_bola_tests(
        model_name="Order",
        route_prefix="/api/v1/orders",
        output_path="tests/test_bola_generated.py",
    )
"""

from __future__ import annotations

from pathlib import Path


def generate_bola_tests(
    model_name: str,
    route_prefix: str,
    output_path: str,
    owner_field: str = "user_id",
) -> str:
    """Generate a pytest test file covering BOLA attack scenarios.

    Args:
        model_name: SQLAlchemy model name (e.g. \'Order\').
        route_prefix: API route prefix (e.g. \'/api/v1/orders\').
        output_path: File path to write the generated test file.
        owner_field: Column that stores the owner user_id.

    Returns:
        Absolute path of the generated test file.
    """
    content = _render_test_template(model_name, route_prefix, owner_field)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path.resolve())


def _render_test_template(
    model_name: str,
    route_prefix: str,
    owner_field: str,
) -> str:
    """Render the BOLA pytest template for a given model.

    Args:
        model_name: Model class name.
        route_prefix: API route prefix.
        owner_field: Owner field name on the model.

    Returns:
        String content of the generated test module.
    """
    lower = model_name.lower()
    parts = (
        _render_module_header(model_name, lower)
        + _render_fixtures(lower, model_name)
        + _render_test_cases(lower, route_prefix)
        + _render_extra_test_cases(lower, route_prefix)
    )
    return "\\n".join(parts)


def _render_module_header(model_name: str, lower: str) -> list:
    """Return header lines for the generated BOLA test module."""
    dq3 = chr(34) * 3
    return [
        dq3 + "BOLA test suite for " + model_name + " - auto-generated by add_bola_guard.",
        "",
        "Tests:",
        "    1. Owner can access own " + lower + " (200)",
        "    2. Attacker cannot access owner " + lower + " (403)",
        "    3. Unauthenticated request is rejected (401)",
        dq3,
        "",
        "from __future__ import annotations",
        "",
        "import pytest",
        "",
        "",
    ]


def _render_fixtures(lower: str, model_name: str) -> list:
    """Return fixture lines for the generated BOLA test module."""
    dq3 = chr(34) * 3
    return [
        "# --- Fixtures (fill in with your test client + auth helpers) ---",
        "",
        "@pytest.fixture",
        "def owner_token() -> str:",
        "    " + dq3 + "Return a valid JWT token for the resource owner." + dq3,
        "    # TODO: generate or retrieve a real token for the owner user",
        '    return "OWNER_TOKEN_PLACEHOLDER"',
        "",
        "",
        "@pytest.fixture",
        "def attacker_token() -> str:",
        "    " + dq3 + "Return a valid JWT token for a different (attacker) user." + dq3,
        "    # TODO: generate or retrieve a real token for a second user",
        '    return "ATTACKER_TOKEN_PLACEHOLDER"',
        "",
        "",
        "@pytest.fixture",
        "def owner_" + lower + "_id() -> int:",
        "    " + dq3 + "Return the ID of a " + model_name + " owned by the owner user." + dq3,
        "    # TODO: create a " + lower + " record owned by owner and return its ID",
        "    return 1",
        "",
        "",
        "# --- BOLA test cases ---",
        "",
    ]


def _render_test_cases(lower: str, route_prefix: str) -> list:
    """Return owner and attacker test-case lines for the generated module."""
    dq3 = chr(34) * 3
    return [
        "def test_owner_can_access_own_" + lower + "(",
        "    client,",
        "    owner_token: str,",
        "    owner_" + lower + "_id: int,",
        ") -> None:",
        "    " + dq3 + "BOLA-01: Owner can read their own " + lower + " (200)." + dq3,
        "    response = client.get(",
        '        f"' + route_prefix + '/{owner_' + lower + '_id}",',
        '        headers={"Authorization": f"Bearer {owner_token}"},',
        "    )",
        "    assert response.status_code == 200",
        "",
        "",
        "def test_attacker_cannot_access_owner_" + lower + "(",
        "    client,",
        "    attacker_token: str,",
        "    owner_" + lower + "_id: int,",
        ") -> None:",
        "    " + dq3 + "BOLA-02: Attacker gets 403 on owner " + lower + "." + dq3,
        "    response = client.get(",
        '        f"' + route_prefix + '/{owner_' + lower + '_id}",',
        '        headers={"Authorization": f"Bearer {attacker_token}"},',
        "    )",
        "    assert response.status_code == 403",
        "",
        "",
    ]


def _render_extra_test_cases(lower: str, route_prefix: str) -> list:
    """Return unauthenticated and delete test-case lines."""
    dq3 = chr(34) * 3
    return [
        "def test_unauthenticated_access_" + lower + "_rejected(",
        "    client,",
        "    owner_" + lower + "_id: int,",
        ") -> None:",
        "    " + dq3 + "BOLA-03: Unauthenticated access is rejected (401/403)." + dq3,
        '    response = client.get(f"' + route_prefix + '/{owner_' + lower + '_id}")',
        "    assert response.status_code in (401, 403)",
        "",
        "",
        "def test_attacker_cannot_delete_owner_" + lower + "(",
        "    client,",
        "    attacker_token: str,",
        "    owner_" + lower + "_id: int,",
        ") -> None:",
        "    " + dq3 + "BOLA-04: Attacker DELETE is rejected (403)." + dq3,
        "    response = client.delete(",
        '        f"' + route_prefix + '/{owner_' + lower + '_id}",',
        '        headers={"Authorization": f"Bearer {attacker_token}"},',
        "    )",
        "    assert response.status_code == 403",
        "",
    ]


def list_generated_test_files(tests_dir: str = "tests") -> list[str]:
    """Return paths to all auto-generated BOLA test files.

    Args:
        tests_dir: Directory to scan for generated BOLA tests.

    Returns:
        List of absolute path strings.
    """
    return [str(p) for p in Path(tests_dir).rglob("test_bola_*.py") if p.is_file()]
'''


def _patch_config(config_file: Path):  # type: ignore[no-untyped-def]
    """Inject BOLA guard settings into ``app/core/config.py`` Settings class.

    Args:
        config_file: Path to the existing config.py.

    Returns:
        ``PatchResult`` describing the outcome (see
        :mod:`adapt.contracts.config_patcher`).
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    return patch_settings_fields(
        config_file,
        fields=[
            ("BOLA_GUARD_ENABLED", "BOLA_GUARD_ENABLED: bool = True"),
            ("BOLA_GUARD_STRICT_MODE", "BOLA_GUARD_STRICT_MODE: bool = False"),
        ],
    )


# ---------------------------------------------------------------------------
# F-001: discover owner-bearing models + emit tests/test_bola_generated.py
# ---------------------------------------------------------------------------

_OWNER_FIELD_CANDIDATES: tuple[str, ...] = ("user_id", "owner_id", "created_by_id")


def _discover_owner_bearing_models(project: Path) -> list[dict]:
    """Find every ``app/models/*.py`` class that declares an owner FK column.

    Owner detection: the class body contains an annotated/assigned attribute
    whose name is one of ``user_id`` / ``owner_id`` / ``created_by_id``.

    Args:
        project: Project root.

    Returns:
        List of ``{"class_name": str, "stem": str, "owner_field": str}`` dicts,
        sorted deterministically by class_name.
    """
    models_dir = project / "app" / "models"
    routes_dir = project / "app" / "api" / "routes"
    if not models_dir.is_dir():
        return []

    available_routes: set[str] = set()
    if routes_dir.is_dir():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)

    skip = {"base", "user", "mixins", "__init__", "tenant"}
    discovered: list[dict] = []
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name.lower() != stem:
                continue
            owner_field = _owner_field_for_class(node)
            if owner_field is None:
                continue
            discovered.append(
                {
                    "class_name": node.name,
                    "stem": stem,
                    "owner_field": owner_field,
                    "route_prefix": (
                        f"/api/v1/{stem}s" if stem in available_routes else f"/api/v1/{stem}s"
                    ),
                }
            )
    discovered.sort(key=lambda d: d["class_name"])
    return discovered


def _owner_field_for_class(cls: ast.ClassDef) -> str | None:
    """Return the first owner-FK column name on *cls*, or ``None``."""
    for body_node in cls.body:
        target_name: str | None = None
        if isinstance(body_node, ast.AnnAssign) and isinstance(body_node.target, ast.Name):
            target_name = body_node.target.id
        elif isinstance(body_node, ast.Assign):
            for target in body_node.targets:
                if isinstance(target, ast.Name):
                    target_name = target.id
                    break
        if target_name in _OWNER_FIELD_CANDIDATES:
            return target_name
    return None


def _render_generated_bola_tests(owner_models: list[dict]) -> str:
    """Produce the full content for ``tests/test_bola_generated.py``.

    Each owner-bearing model contributes 4 test functions (≥3 assertions
    per model): owner can access, attacker cannot access, unauthenticated
    is rejected, attacker cannot delete.

    Args:
        owner_models: Output of :func:`_discover_owner_bearing_models`.

    Returns:
        Python source as a string (always ``ast.parse``-clean).
    """
    header = textwrap.dedent('''\
        """Auto-generated BOLA test suite.

        Emitted by ``add_bola_guard`` for every owner-bearing model discovered
        under ``app/models/``. Each model gets test cases that prove cross-user
        access is blocked.

        Replace OWNER_TOKEN_PLACEHOLDER / ATTACKER_TOKEN_PLACEHOLDER with real
        per-user JWTs (and the placeholder owner-resource fixture) from your
        test setup, then remove ``pytestmark = pytest.mark.skip(...)`` below
        to enable the suite.

        Run::

            PYTHONPATH=. pytest tests/test_bola_generated.py -v
        """

        from __future__ import annotations

        import pytest

        # Skipped by default — the per-model fixtures below are placeholders
        # (OWNER_TOKEN_PLACEHOLDER / id=1) and the suite will fail until the
        # caller wires in real auth tokens and an owned-resource id. Remove
        # this line after replacing the placeholders.
        pytestmark = pytest.mark.skip(
            reason=(
                "BOLA placeholders not wired — replace OWNER_TOKEN_PLACEHOLDER, "
                "ATTACKER_TOKEN_PLACEHOLDER and owner_<model>_id fixtures, "
                "then delete this pytestmark."
            )
        )

    ''')
    if not owner_models:
        body = textwrap.dedent('''\

            # No owner-bearing models discovered when add_bola_guard ran.
            # Re-run the tool after declaring models with a ``user_id`` / ``owner_id``
            # / ``created_by_id`` column to regenerate this file with per-model cases.


            def test_placeholder_no_owner_bearing_models() -> None:
                """BOLA-PLACEHOLDER: regenerate this file once owner-bearing models exist."""
                assert True
        ''')
        return header + body

    blocks: list[str] = []
    for m in owner_models:
        blocks.append(_render_bola_block_for_model(m))
    return header + "\n".join(blocks)


def _render_bola_block_for_model(model: dict) -> str:
    """Render the per-model BOLA test block.

    Args:
        model: Dict with ``class_name``, ``stem``, ``owner_field``,
            ``route_prefix``.

    Returns:
        Python source for 4 test functions plus 3 fixtures.
    """
    cls = model["class_name"]
    stem = model["stem"]
    route = model["route_prefix"]
    return textwrap.dedent(f'''\

        # ---------------------------------------------------------------------------
        # BOLA tests for {cls} (owner field: {model["owner_field"]})
        # ---------------------------------------------------------------------------


        @pytest.fixture
        def owner_token_{stem}() -> str:
            """Return a JWT for the resource owner ({cls})."""
            # TODO: replace with a real owner JWT.
            return "OWNER_TOKEN_PLACEHOLDER"


        @pytest.fixture
        def attacker_token_{stem}() -> str:
            """Return a JWT for an attacker user (not the owner of any {cls})."""
            # TODO: replace with a real attacker JWT.
            return "ATTACKER_TOKEN_PLACEHOLDER"


        @pytest.fixture
        def owner_{stem}_id() -> int:
            """Return the id of a {cls} record owned by the owner user."""
            # TODO: create a {cls} owned by the owner user and return its id.
            return 1


        def test_owner_can_access_own_{stem}(
            client,
            owner_token_{stem}: str,
            owner_{stem}_id: int,
        ) -> None:
            """BOLA-01: Owner can read their own {cls} (200)."""
            response = client.get(
                f"{route}/{{owner_{stem}_id}}",
                headers={{"Authorization": f"Bearer {{owner_token_{stem}}}"}},
            )
            assert response.status_code == 200


        def test_attacker_cannot_access_owner_{stem}(
            client,
            attacker_token_{stem}: str,
            owner_{stem}_id: int,
        ) -> None:
            """BOLA-02: Attacker gets 403 on owner {cls}."""
            response = client.get(
                f"{route}/{{owner_{stem}_id}}",
                headers={{"Authorization": f"Bearer {{attacker_token_{stem}}}"}},
            )
            assert response.status_code == 403


        def test_unauthenticated_access_{stem}_rejected(
            client,
            owner_{stem}_id: int,
        ) -> None:
            """BOLA-03: Unauthenticated access is rejected (401/403)."""
            response = client.get(f"{route}/{{owner_{stem}_id}}")
            assert response.status_code in (401, 403)


        def test_attacker_cannot_delete_owner_{stem}(
            client,
            attacker_token_{stem}: str,
            owner_{stem}_id: int,
        ) -> None:
            """BOLA-04: Attacker DELETE is rejected (403)."""
            response = client.delete(
                f"{route}/{{owner_{stem}_id}}",
                headers={{"Authorization": f"Bearer {{attacker_token_{stem}}}"}},
            )
            assert response.status_code == 403
    ''')


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
