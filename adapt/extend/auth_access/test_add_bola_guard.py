"""Structural tests for TOOL-112 add_bola_guard.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_bola_guard.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_bola_guard.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_bola_guard import add_bola_guard
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="bola_t01")
    result = add_bola_guard(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files_created or files_modified."""
    project_dir = create_fixture_project(name="bola_t02")
    r1 = add_bola_guard(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_bola_guard(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="bola_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_bola_guard(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 2 files created (bola_guard.py, bola_test_gen.py)."""
    project_dir = create_fixture_project(name="bola_t04")
    result = add_bola_guard(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 2, (
        f"Expected >= 2 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (app/core/config.py patched)."""
    project_dir = create_fixture_project(name="bola_t05")
    result = add_bola_guard(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All generated .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="bola_t06")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="bola_t07")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    auth_dir = project_dir / "app" / "auth"
    violations: list[str] = []
    for py_file in sorted(auth_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file.name}:{node.name} ({loc} LOC)")
    assert not violations, "Functions > 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: BOLA_GUARD_ENABLED in config.py (single kill-switch).

    R5-O1-F1 (juror a96f3835e9f3a913e): ``BOLA_GUARD_STRICT_MODE`` was
    removed — it was the only knob for fail-open-on-missing-resource-id
    behaviour and that branch is now unconditionally fail-CLOSED.
    """
    project_dir = create_fixture_project(name="bola_t08")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    config = project_dir / "app" / "core" / "config.py"
    assert config.exists()
    content = config.read_text()
    field = "BOLA_GUARD_ENABLED"
    assert field in content, f"{field} not patched into config.py"
    for line in content.splitlines():
        if field in line and ":" in line:
            assert line.startswith("    "), f"Not 4-space indented: {line!r}"
    assert "BOLA_GUARD_STRICT_MODE" not in content, (
        "BOLA_GUARD_STRICT_MODE should be removed (R5-O1-F1): the field "
        "was the fail-open knob and no longer has any runtime effect."
    )


# ---------------------------------------------------------------------------
# CC-09: bola_guard.py OwnershipVerifier
# ---------------------------------------------------------------------------

def test_bola_guard_ownership_verifier_created() -> None:
    """CC-09: app/auth/bola_guard.py with OwnershipVerifier exists."""
    project_dir = create_fixture_project(name="bola_t09")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    bola_file = project_dir / "app" / "auth" / "bola_guard.py"
    assert bola_file.exists(), "app/auth/bola_guard.py not created"
    content = bola_file.read_text()
    assert "OwnershipVerifier" in content


# ---------------------------------------------------------------------------
# CC-10: require_ownership decorator factory
# ---------------------------------------------------------------------------

def test_require_ownership_decorator_factory() -> None:
    """CC-10: require_ownership() returns a FastAPI Depends expression."""
    project_dir = create_fixture_project(name="bola_t10")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "auth" / "bola_guard.py").read_text()
    assert "require_ownership" in content
    assert "Depends" in content, "require_ownership must use FastAPI Depends"


# ---------------------------------------------------------------------------
# CC-11: HTTP 403 raised on ownership failure
# ---------------------------------------------------------------------------

def test_http_403_raised_on_ownership_failure() -> None:
    """CC-11: OwnershipVerifier raises HTTP 403 when ownership check fails."""
    project_dir = create_fixture_project(name="bola_t11")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "auth" / "bola_guard.py").read_text()
    assert "403" in content or "HTTP_403_FORBIDDEN" in content, (
        "HTTP 403 not raised on BOLA violation"
    )


# ---------------------------------------------------------------------------
# CC-12: TenantIsolationFilter
# ---------------------------------------------------------------------------

def test_tenant_isolation_filter_present() -> None:
    """CC-12: TenantIsolationFilter for multi-tenant query isolation exists."""
    project_dir = create_fixture_project(name="bola_t12")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "auth" / "bola_guard.py").read_text()
    assert "TenantIsolationFilter" in content, "TenantIsolationFilter not found"
    assert "tenant_id" in content, "tenant_id isolation not implemented"


# ---------------------------------------------------------------------------
# CC-13: ResourceAccessPolicy delegation
# ---------------------------------------------------------------------------

def test_resource_access_policy_present() -> None:
    """CC-13: ResourceAccessPolicy for cross-user delegation exists."""
    project_dir = create_fixture_project(name="bola_t13")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "auth" / "bola_guard.py").read_text()
    assert "ResourceAccessPolicy" in content, "ResourceAccessPolicy not found"


# ---------------------------------------------------------------------------
# CC-14: bola_test_gen.py auto-generates test cases
# ---------------------------------------------------------------------------

def test_bola_test_gen_created() -> None:
    """CC-14: app/auth/bola_test_gen.py generates BOLA test cases."""
    project_dir = create_fixture_project(name="bola_t14")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    test_gen = project_dir / "app" / "auth" / "bola_test_gen.py"
    assert test_gen.exists(), "app/auth/bola_test_gen.py not created"
    content = test_gen.read_text()
    assert "generate_bola_tests" in content


# ---------------------------------------------------------------------------
# CC-15: BOLA test covers two-user cross-access scenario
# ---------------------------------------------------------------------------

def test_bola_test_gen_two_user_scenario() -> None:
    """CC-15: bola_test_gen.py generates tests with owner and attacker users."""
    project_dir = create_fixture_project(name="bola_t15")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "auth" / "bola_test_gen.py").read_text()
    assert "attacker" in content.lower() or "owner" in content.lower(), (
        "Two-user (owner/attacker) test scenario not found"
    )
    assert "403" in content, "403 assertion not found in generated tests"


# ---------------------------------------------------------------------------
# CC-16: execution_time_ms positive
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-16: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="bola_t16")
    result = add_bola_guard(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-17: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-17: next_steps guides developer to use require_ownership decorator."""
    project_dir = create_fixture_project(name="bola_t17")
    result = add_bola_guard(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "ownership" in combined or "bola" in combined or "require" in combined


# ---------------------------------------------------------------------------
# CC-18: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-18: After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="bola_t18")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-19: bola_guard_enabled env check
# ---------------------------------------------------------------------------

def test_bola_enabled_env_check() -> None:
    """CC-19: bola_guard.py respects BOLA_GUARD_ENABLED env var."""
    project_dir = create_fixture_project(name="bola_t19")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "auth" / "bola_guard.py").read_text()
    assert "BOLA_GUARD_ENABLED" in content, (
        "BOLA_GUARD_ENABLED env var not checked in bola_guard.py"
    )


# ---------------------------------------------------------------------------
# CC-20: strict mode logic present
# ---------------------------------------------------------------------------

def test_strict_mode_logic_present() -> None:
    """CC-20 (R5-O1-F1, juror a96f3835e9f3a913e): the verifier raises 403
    when ``_extract_resource_id`` returns ``None``.

    Pre-fix this branch was gated by ``_strict_mode()`` (default False)
    and silently allowed access — fail-OPEN on routes with path-param
    names outside the ``<model>_id`` / ``id`` / first-integer
    heuristic (e.g. ``/orders/{order_uuid}``).  Post-fix it
    unconditionally raises ``HTTPException(status_code=403)``.
    """
    project_dir = create_fixture_project(name="bola_t20")
    add_bola_guard(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "auth" / "bola_guard.py").read_text()
    # The dead ``_strict_mode`` env helper must be gone.
    assert "_strict_mode" not in content, (
        "_strict_mode helper must be removed (R5-O1-F1): it was the "
        "fail-open switch."
    )
    # The fail-CLOSED branch must reach a fail-closed code path
    # (HTTPException 403 directly OR a delegating helper call).
    tree = ast.parse(content)
    extract_call_found = False
    fail_closed_on_missing = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_extract_resource_id"
        ):
            extract_call_found = True
        if isinstance(node, ast.If):
            test_src = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
            if "resource_id" in test_src and "None" in test_src:
                body_src = ast.unparse(node) if hasattr(ast, "unparse") else ""
                # Either: raises HTTPException 403 directly,
                # OR: delegates to a fail-closed helper method.
                has_403_raise = ("raise HTTPException" in body_src and "403" in body_src)
                has_fail_closed_call = "fail_closed" in body_src
                if has_403_raise or has_fail_closed_call:
                    fail_closed_on_missing = True
    assert extract_call_found, "_extract_resource_id call not found"
    assert fail_closed_on_missing, (
        "BOLA guard must fail-CLOSED when resource_id is None "
        "(R5-O1-F1 fix); found fail-OPEN code path."
    )
    # Sanity: a fail-closed helper must exist and raise 403.
    assert "HTTP_403_FORBIDDEN" in content or "status_code=403" in content, (
        "No 403 path found in bola_guard.py"
    )


# ---------------------------------------------------------------------------
# CC-21: error invalid project_dir
# ---------------------------------------------------------------------------

def test_error_invalid_project_dir() -> None:
    """CC-21: Tool returns error for non-existent project_dir."""
    result = add_bola_guard(ToolInput(project_dir="/nonexistent/path/abc123"))
    assert result.status == "error"
    assert result.error
    assert result.execution_time_ms >= 0


# ---------------------------------------------------------------------------
# CC-22: MCP_TOOL dict entry matches function
# ---------------------------------------------------------------------------

def test_mcp_tool_entry_matches_function() -> None:
    """CC-22: MCP_TOOL['entry'] equals the function name 'add_bola_guard'."""
    from adapt.extend.auth_access.add_bola_guard import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_bola_guard", (
        f"MCP_TOOL entry mismatch: {MCP_TOOL['entry']!r}"
    )
    assert "name" in MCP_TOOL
    assert "description" in MCP_TOOL
    assert "tags" in MCP_TOOL


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_bola_guard_ownership_verifier_created,
        test_require_ownership_decorator_factory,
        test_http_403_raised_on_ownership_failure,
        test_tenant_isolation_filter_present,
        test_resource_access_policy_present,
        test_bola_test_gen_created,
        test_bola_test_gen_two_user_scenario,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_bola_enabled_env_check,
        test_strict_mode_logic_present,
        test_error_invalid_project_dir,
        test_mcp_tool_entry_matches_function,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-112 add_bola_guard: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
