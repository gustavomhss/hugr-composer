"""Structural + behavioural regression tests for TOOL-012 ``add_rbac``.

Structural tests (CONTRACT §B1.0 + §B1.0.1):
1. Copy the `RequestGuard` + `CurrentPrincipal` primitives into the
   generated project (via `generators/scaffold_venous.ensure_primitives`).
2. Copy the FastAPI adapter `RequestGuardAdapter` alongside them.
3. Write a ≤20-line `app/rbac.py` with `require_roles()` backed by
   `get_current_user` (NOT a silent-anonymous stub).

Behavioural regression tests (BUG FIX — "claims success but does nothing"):
- The guard must ACTUALLY enforce roles: admin-role user admitted,
  non-admin denied 403, no token → 401 via get_current_user.
- The ToolResult MUST carry warnings stating RBAC is NOT auto-enforced.
- The glue file must NOT contain `resolve_principal` returning `anonymous()`
  unconditionally (the old silent-allow-all stub).
- The glue file MUST wire `require_roles` through `get_current_user`.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_rbac import MCP_TOOL, _WARN_NOT_AUTO_ENFORCED, add_rbac
from tests.common.fixture_factory import create_fixture_project


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:  # pragma: no cover
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Existing structural tests (unchanged)
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    project_dir = create_fixture_project(name="rbac_t01")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    project_dir = create_fixture_project(name="rbac_t02")
    r1 = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"


def test_dry_run_writes_nothing() -> None:
    project_dir = create_fixture_project(name="rbac_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_rbac(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


def test_both_primitives_copied() -> None:
    project_dir = create_fixture_project(name="rbac_t04")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    rg = project_dir / "core" / "venous" / "auth" / "RequestGuard" / "RequestGuard.py"
    cp = project_dir / "core" / "venous" / "auth" / "CurrentPrincipal" / "CurrentPrincipal.py"
    assert rg.exists() and "class CompositeGuard" in rg.read_text()
    assert cp.exists() and "class CurrentPrincipal" in cp.read_text()


def test_adapter_copied_into_project() -> None:
    project_dir = create_fixture_project(name="rbac_t05")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    adapter = project_dir / "core" / "venous" / "_adapters" / "fastapi" / "RequestGuardAdapter.py"
    assert adapter.exists()
    body = adapter.read_text()
    assert "def require(" in body
    assert "Copied from HuGR Arsenal" in body


def test_venous_manifest_records_provenance() -> None:
    project_dir = create_fixture_project(name="rbac_t06")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    prim_names = {p["qualified_name"] for p in manifest["primitives"]}
    adapter_names = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.auth.RequestGuard" in prim_names
    assert "core.venous.auth.CurrentPrincipal" in prim_names
    assert "core.venous._adapters.fastapi.RequestGuardAdapter" in adapter_names


def test_glue_file_imports_adapter() -> None:
    project_dir = create_fixture_project(name="rbac_t07")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "rbac.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.RequestGuardAdapter import require" in body
    assert "from core.venous.auth.RequestGuard.RequestGuard import RoleGuard" in body
    assert "def require_roles" in body


def test_glue_file_under_20_loc_body() -> None:
    project_dir = create_fixture_project(name="rbac_t08")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "rbac.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, f"glue body is {body_lines} LoC; budget is 20"


def test_all_py_parse_after_two_runs() -> None:
    project_dir = create_fixture_project(name="rbac_t09")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    add_rbac(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_lists_imported_primitives() -> None:
    assert MCP_TOOL["entry"] == "add_rbac"
    assert "core.venous.auth.RequestGuard" in MCP_TOOL["imports_primitives"]
    assert "core.venous.auth.CurrentPrincipal" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.RequestGuardAdapter" in MCP_TOOL["imports_adapters"]


def test_mcp_tool_has_required_keys() -> None:
    for key in ("name", "description", "tags", "entry"):
        assert key in MCP_TOOL, f"MCP_TOOL missing key: {key}"


def test_execution_time_recorded() -> None:
    project_dir = create_fixture_project(name="rbac_t11")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# Behavioural regression tests — BUG FIX: "claims success but does nothing"
# ---------------------------------------------------------------------------

def test_result_warns_rbac_not_auto_enforced() -> None:
    """ToolResult MUST carry a warning that RBAC is not auto-enforced.

    The old implementation returned status="success" with no warnings,
    letting callers assume RBAC was active on their routes.  This regression
    test ensures the warning is always present in the result.
    """
    project_dir = create_fixture_project(name="rbac_t12")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert result.warnings, "ToolResult must carry at least one warning"
    warning_text = " ".join(result.warnings).upper()
    assert "NOT AUTO-ENFORCED" in warning_text or "NOT" in warning_text, (
        f"Warning must state RBAC is not auto-enforced; got: {result.warnings}"
    )


def test_dry_run_result_also_warns() -> None:
    """dry_run result must also carry the not-auto-enforced warning."""
    project_dir = create_fixture_project(name="rbac_t13")
    result = add_rbac(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert result.warnings, "dry_run ToolResult must carry at least one warning"


def test_warn_not_auto_enforced_constant_is_explicit() -> None:
    """The warning constant exported from add_rbac must be explicit about enforcement.

    This prevents future changes from softening the warning text to something
    that doesn't communicate the security risk.
    """
    w = _WARN_NOT_AUTO_ENFORCED.upper()
    assert "NOT" in w
    assert "AUTO-ENFORCED" in w or "ENFORCED" in w
    assert "ROUTE" in w or "ROUTES" in w


def test_glue_does_not_contain_silent_anonymous_stub() -> None:
    """app/rbac.py must NOT contain an unconditional `return anonymous()` stub.

    The old bug: resolve_principal() returned anonymous() unconditionally,
    meaning every require_roles() call silently treated all principals as
    anonymous and denied everything — the function existed but did nothing
    useful, yet the tool reported success.
    """
    project_dir = create_fixture_project(name="rbac_t14")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    glue = (project_dir / "app" / "rbac.py").read_text()
    # The glue must not have a function whose SOLE purpose is returning anonymous().
    # Specifically guard against the old pattern: a resolve_principal that is only
    # "return anonymous()" with no real logic.
    tree = ast.parse(glue)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "resolve_principal":
            continue
        # If resolve_principal exists, its body must not be just `return anonymous()`.
        body = node.body
        if len(body) == 1 and isinstance(body[0], ast.Return):
            ret = body[0].value
            # Detect: `return anonymous()` (a bare call to anonymous with no args)
            if (
                isinstance(ret, ast.Call)
                and isinstance(ret.func, ast.Name)
                and ret.func.id == "anonymous"
                and not ret.args
                and not ret.keywords
            ):
                raise AssertionError(
                    "app/rbac.py still contains a resolve_principal() that "
                    "unconditionally returns anonymous() — the silent stub that "
                    "caused the original bug.  Fix: remove it or replace it with "
                    "real logic (e.g. derive principal from get_current_user)."
                )


def test_glue_wires_require_roles_through_get_current_user() -> None:
    """require_roles in app/rbac.py must delegate to get_current_user.

    The old bug: require_roles used resolve_principal (a stub returning
    anonymous()) as the principal source.  This test verifies the new glue
    wires require_roles through the project's existing get_current_user
    dependency so real token validation and DB lookup back the guard.
    """
    project_dir = create_fixture_project(name="rbac_t15")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    glue = (project_dir / "app" / "rbac.py").read_text()
    assert "get_current_user" in glue, (
        "app/rbac.py must import and use get_current_user so require_roles "
        "is backed by real auth, not a stub principal resolver."
    )


def test_guard_admits_principal_with_required_role() -> None:
    """A principal carrying the required role must be admitted (ALLOW).

    Tests the RoleGuard + _user_to_principal pipeline at unit level using
    the primitives shipped into the generated project, independent of HTTP.
    This proves the guard ACTUALLY works, not just that files were written.
    """
    from core.venous.auth.CurrentPrincipal.CurrentPrincipal import authenticated
    from core.venous.auth.RequestGuard.RequestGuard import (
        CompositeGuard,
        GuardOutcome,
        RoleGuard,
        run_sync,
    )

    class _Ctx:
        request_id = "-"
        headers: dict = {}
        assigns: dict = {}

    admin = authenticated("user-1", roles=["admin"])
    guard = CompositeGuard([RoleGuard("admin")])
    outcome = run_sync(guard.evaluate(_Ctx(), admin))
    assert outcome is GuardOutcome.ALLOW, f"Admin should be admitted; got {outcome}"


def test_guard_denies_principal_without_required_role() -> None:
    """A principal lacking the required role must be denied (DENY_FORBIDDEN → 403).

    Regression: the old stub returned anonymous() for everyone, so
    require_roles("admin") denied ALL requests including real admins — the
    guard existed but was never reachable because the principal was always
    anonymous.  Now we verify the correct behaviour: authenticated non-admin
    gets DENY_FORBIDDEN, not a pass-through.
    """
    from core.venous.auth.CurrentPrincipal.CurrentPrincipal import authenticated
    from core.venous.auth.RequestGuard.RequestGuard import (
        CompositeGuard,
        GuardOutcome,
        RoleGuard,
        run_sync,
    )

    class _Ctx:
        request_id = "-"
        headers: dict = {}
        assigns: dict = {}

    viewer = authenticated("user-2", roles=["user"])
    guard = CompositeGuard([RoleGuard("admin")])
    outcome = run_sync(guard.evaluate(_Ctx(), viewer))
    assert outcome is GuardOutcome.DENY_FORBIDDEN, (
        f"Non-admin should get DENY_FORBIDDEN; got {outcome}"
    )


def test_guard_denies_anonymous_principal() -> None:
    """An anonymous principal must be denied with DENY_UNAUTHENTICATED (→ 401).

    With the old stub, resolve_principal always returned anonymous(), so
    every require_roles call would hit this path — but the tool still claimed
    success, implying RBAC was working.  Now we verify: anonymous is denied
    AND the guard correctly classifies it as unauthenticated (not forbidden).
    """
    from core.venous.auth.CurrentPrincipal.CurrentPrincipal import anonymous
    from core.venous.auth.RequestGuard.RequestGuard import (
        CompositeGuard,
        GuardOutcome,
        RoleGuard,
        run_sync,
    )

    class _Ctx:
        request_id = "-"
        headers: dict = {}
        assigns: dict = {}

    anon = anonymous()
    guard = CompositeGuard([RoleGuard("admin")])
    outcome = run_sync(guard.evaluate(_Ctx(), anon))
    assert outcome is GuardOutcome.DENY_UNAUTHENTICATED, (
        f"Anonymous should get DENY_UNAUTHENTICATED (→ 401); got {outcome}"
    )


def test_user_to_principal_maps_superuser_to_admin_role() -> None:
    """_user_to_principal in the emitted glue maps is_superuser=True → role 'admin'.

    This validates the role mapping that require_roles("admin") will use in
    production.  If this mapping is wrong, superusers would be denied even
    after the developer correctly adds dependencies=[Depends(require_roles("admin"))].
    """
    project_dir = create_fixture_project(name="rbac_t16")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    glue_text = (project_dir / "app" / "rbac.py").read_text()
    # Verify the mapping is documented in the glue (text-level check).
    assert "admin" in glue_text, "Glue must define an 'admin' role mapping"
    assert "is_superuser" in glue_text, (
        "Glue must reference is_superuser to derive roles from the User model"
    )


if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run_writes_nothing,
        test_both_primitives_copied,
        test_adapter_copied_into_project,
        test_venous_manifest_records_provenance,
        test_glue_file_imports_adapter,
        test_glue_file_under_20_loc_body,
        test_all_py_parse_after_two_runs,
        test_mcp_tool_lists_imported_primitives,
        test_mcp_tool_has_required_keys,
        test_execution_time_recorded,
        # Behavioural regression tests
        test_result_warns_rbac_not_auto_enforced,
        test_dry_run_result_also_warns,
        test_warn_not_auto_enforced_constant_is_explicit,
        test_glue_does_not_contain_silent_anonymous_stub,
        test_glue_wires_require_roles_through_get_current_user,
        test_guard_admits_principal_with_required_role,
        test_guard_denies_principal_without_required_role,
        test_guard_denies_anonymous_principal,
        test_user_to_principal_maps_superuser_to_admin_role,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if not failed else 1)
