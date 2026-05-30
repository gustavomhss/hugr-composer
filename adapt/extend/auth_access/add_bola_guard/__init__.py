"""TOOL-112: add_bola_guard — Object-level authorization (BOLA/IDOR) for FastAPI.

Role since v0.5 (P1 #16 secure-by-default):
  - ``generators.orchestrator.generate_project`` already emits an inline
    per-object ownership guard on every owner-bearing model by default;
    ``shared_models={"X"}`` is the explicit opt-out.
  - This tool is the LAYERED / RETROFIT path.  Use it to:
      1. Add BOLA protection to a project scaffolded BEFORE secure-by-
         default landed (the inline guard is missing).
      2. Add capabilities the inline guard does NOT provide:
         ``ResourceAccessPolicy`` (cross-user delegation) and
         ``TenantIsolationFilter`` (multi-tenant query scoping).
      3. Defence-in-depth: when layered on top of the inline guard, the
         two enforcement points are independent (route-level vs DB-level)
         and either alone is sufficient to block BOLA.

Generates:
  - ``app/auth/bola_guard.py``       — OwnershipVerifier dep + ResourceAccessPolicy
  - ``app/auth/bola_test_gen.py``    — Auto-generates BOLA test cases
  - patches ``app/core/config.py``   — BOLA_GUARD_ENABLED (kill-switch)

Tool is idempotent: second run detects ``OwnershipVerifier`` in
``app/auth/bola_guard.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import load_template
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

from . import _helpers as helpers

_HERE = Path(__file__).parent

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
        "verification.  The guard is fail-CLOSED by default: when the "
        "resource id cannot be extracted from the path (param name does "
        "not match ``<model>_id`` / ``id`` / first-integer heuristic) "
        "the verifier raises HTTP 403 — there is no opt-out."
    ),
    "tags": ["extend", "auth_access", "security", "bola", "idor"],
    "entry": "add_bola_guard",
}


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def add_bola_guard(inp: ToolInput) -> ToolResult:
    """Add BOLA guard to a FastAPI project."""
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

    # Step 1: auth package
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_init = auth_dir / "__init__.py"
    if not auth_init.exists():
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    # Step 2-3: bola_guard.py + bola_test_gen.py
    bola_file.write_text(load_template(_HERE, "bola_guard.py.tmpl").template)
    files_created.append(str(bola_file))
    test_gen_file = auth_dir / "bola_test_gen.py"
    test_gen_file.write_text(load_template(_HERE, "bola_test_gen.py.tmpl").template)
    files_created.append(str(test_gen_file))

    # Step 3b: tests/test_bola_generated.py
    owner_models = helpers.discover_owner_bearing_models(project)
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    generated_tests_file = tests_dir / "test_bola_generated.py"
    generated_tests_file.write_text(helpers.render_generated_bola_tests(_HERE, owner_models))
    files_created.append(str(generated_tests_file))

    # Step 4: patch config.py
    config_file = project / "app" / "core" / "config.py"
    config_notes: list[str] = []
    if config_file.exists():
        from adapt.contracts.config_patcher import PatchResult

        patch_outcome = helpers.patch_config(config_file)
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

    # Step 5: ast.parse validation
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
            "Guard is fail-CLOSED by default (R5-O1-F1): unmatched path-param names raise 403. Use <model>_id or id as the path param name.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )
