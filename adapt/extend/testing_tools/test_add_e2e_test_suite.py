"""Tests for TOOL-094 add_e2e_test_suite.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_e2e_test_suite.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_e2e_test_suite.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_e2e_test_suite import add_e2e_test_suite
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root* sorted alphabetically.

    Args:
        root: Directory to search recursively.

    Returns:
        Sorted list of .py file paths.
    """
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under *root* has valid AST syntax.

    Args:
        root: Directory to walk recursively.

    Raises:
        AssertionError: On syntax error in any generated file.
    """
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "tests") -> int:
    """Return the maximum LOC of any function in the given subdir.

    Args:
        root: Project root directory.
        subdir: Subdirectory to scan (default ``"tests"``).

    Returns:
        Maximum function LOC found, or 0 if none found.
    """
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    max_loc = max(max_loc, loc)
    return max_loc


def _fresh(name: str) -> Path:
    """Return a freshly generated fixture project.

    Args:
        name: Unique project name to avoid cross-test collisions.

    Returns:
        Path to the generated project root.
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# CC-01 — success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = _fresh("e2e_t01")
    result = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02 — idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = _fresh("e2e_t02")
    r1 = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = _fresh("e2e_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_e2e_test_suite(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """Tool creates at least 5 files in tests/e2e/."""
    project_dir = _fresh("e2e_t04")
    result = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    e2e_files = [p for p in result.files_created if "e2e" in p]
    assert len(e2e_files) >= 5, (
        f"Expected >= 5 E2E files_created, got {len(e2e_files)}: {e2e_files}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """Tool modifies at least 1 file (config.py)."""
    project_dir = _fresh("e2e_t05")
    result = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = _fresh("e2e_t06")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated tests/e2e/ exceeds 50 LOC."""
    project_dir = _fresh("e2e_t07")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "tests")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """E2E_* settings fields exist inside Settings in config.py."""
    project_dir = _fresh("e2e_t08")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("E2E_BASE_URL", "E2E_TEST_EMAIL", "E2E_TEST_PASSWORD"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify 4-space indent (field is inside the Settings class body)
    for line in content.splitlines():
        if "E2E_BASE_URL" in line:
            assert line.startswith("    "), (
                f"E2E_BASE_URL not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09 — conftest.py has async_client fixture
# ---------------------------------------------------------------------------

def test_conftest_has_async_client_fixture() -> None:
    """tests/e2e/conftest.py exists with async_client fixture."""
    project_dir = _fresh("e2e_t09")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    conftest = project_dir / "tests" / "e2e" / "conftest.py"
    assert conftest.exists(), "tests/e2e/conftest.py not created"
    content = conftest.read_text()
    assert "async_client" in content, "conftest.py missing async_client fixture"
    assert "ASGITransport" in content, "conftest.py must use httpx.ASGITransport"


# ---------------------------------------------------------------------------
# CC-10 — conftest.py has test_user and auth_headers fixtures
# ---------------------------------------------------------------------------

def test_conftest_has_auth_fixtures() -> None:
    """tests/e2e/conftest.py contains test_user and auth_headers fixtures."""
    project_dir = _fresh("e2e_t10")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "tests" / "e2e" / "conftest.py").read_text()
    assert "test_user" in content, "conftest.py missing test_user fixture"
    assert "auth_headers" in content, "conftest.py missing auth_headers fixture"


# ---------------------------------------------------------------------------
# CC-11 — test_auth_flow.py created
# ---------------------------------------------------------------------------

def test_auth_flow_test_created() -> None:
    """tests/e2e/test_auth_flow.py exists with login and protected route tests."""
    project_dir = _fresh("e2e_t11")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    auth_test = project_dir / "tests" / "e2e" / "test_auth_flow.py"
    assert auth_test.exists(), "tests/e2e/test_auth_flow.py not created"
    content = auth_test.read_text()
    assert "login" in content.lower(), "test_auth_flow.py missing login test"
    assert "register" in content.lower() or "signup" in content.lower(), (
        "test_auth_flow.py missing registration test"
    )


# ---------------------------------------------------------------------------
# CC-12 — test_crud_flow.py created
# ---------------------------------------------------------------------------

def test_crud_flow_test_created() -> None:
    """tests/e2e/test_crud_flow.py exists covering create/read/update/delete."""
    project_dir = _fresh("e2e_t12")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    crud_test = project_dir / "tests" / "e2e" / "test_crud_flow.py"
    assert crud_test.exists(), "tests/e2e/test_crud_flow.py not created"
    content = crud_test.read_text()
    assert "create" in content.lower(), "test_crud_flow.py missing create test"
    assert "delete" in content.lower(), "test_crud_flow.py missing delete test"
    assert "404" in content, "test_crud_flow.py missing verify-gone 404 test"


# ---------------------------------------------------------------------------
# CC-13 — test_error_handling.py created
# ---------------------------------------------------------------------------

def test_error_handling_test_created() -> None:
    """tests/e2e/test_error_handling.py exists with 422, 404, 401 tests."""
    project_dir = _fresh("e2e_t13")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    error_test = project_dir / "tests" / "e2e" / "test_error_handling.py"
    assert error_test.exists(), "tests/e2e/test_error_handling.py not created"
    content = error_test.read_text()
    assert "422" in content, "test_error_handling.py missing 422 test"
    assert "404" in content, "test_error_handling.py missing 404 test"
    assert "401" in content, "test_error_handling.py missing 401 test"


# ---------------------------------------------------------------------------
# CC-14 — tests use pytest.mark.asyncio
# ---------------------------------------------------------------------------

def test_tests_use_asyncio_marker() -> None:
    """Generated test files use @pytest.mark.asyncio decorator."""
    project_dir = _fresh("e2e_t14")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    e2e_dir = project_dir / "tests" / "e2e"
    for test_file in ("test_auth_flow.py", "test_crud_flow.py", "test_error_handling.py"):
        content = (e2e_dir / test_file).read_text()
        assert "pytest.mark.asyncio" in content, (
            f"{test_file} missing @pytest.mark.asyncio decorator"
        )


# ---------------------------------------------------------------------------
# CC-15 — no real HTTP server required (ASGITransport)
# ---------------------------------------------------------------------------

def test_no_real_server_needed() -> None:
    """conftest.py uses ASGITransport — no real HTTP server required."""
    project_dir = _fresh("e2e_t15")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "tests" / "e2e" / "conftest.py").read_text()
    assert "ASGITransport" in content, "conftest.py must use httpx.ASGITransport (no server needed)"


# ---------------------------------------------------------------------------
# CC-16 — __init__.py created
# ---------------------------------------------------------------------------

def test_e2e_init_created() -> None:
    """tests/e2e/__init__.py exists."""
    project_dir = _fresh("e2e_t16")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "tests" / "e2e" / "__init__.py"
    assert init_file.exists(), "tests/e2e/__init__.py not created"


# ---------------------------------------------------------------------------
# CC-N-1 — execution time recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = _fresh("e2e_t17")
    result = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps guides developer to run the E2E tests."""
    project_dir = _fresh("e2e_t18")
    result = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "pytest" in combined, "next_steps should mention pytest"


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = _fresh("e2e_t19")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Additional domain tests
# ---------------------------------------------------------------------------

def test_conftest_imports_app_main() -> None:
    """conftest.py imports app.main to get the ASGI app."""
    project_dir = _fresh("e2e_t20")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "tests" / "e2e" / "conftest.py").read_text()
    assert "app.main" in content or "from app" in content, (
        "conftest.py must import the ASGI app from app.main"
    )


def test_crud_test_has_update_case() -> None:
    """test_crud_flow.py includes an update (PATCH) test case."""
    project_dir = _fresh("e2e_t21")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "tests" / "e2e" / "test_crud_flow.py").read_text()
    assert "patch" in content.lower() or "update" in content.lower(), (
        "test_crud_flow.py must include an update test"
    )


def test_auth_test_has_wrong_password_case() -> None:
    """test_auth_flow.py includes a wrong-password → 401 test."""
    project_dir = _fresh("e2e_t22")
    add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "tests" / "e2e" / "test_auth_flow.py").read_text()
    assert "401" in content, "test_auth_flow.py must test wrong password → 401"


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
        test_conftest_has_async_client_fixture,
        test_conftest_has_auth_fixtures,
        test_auth_flow_test_created,
        test_crud_flow_test_created,
        test_error_handling_test_created,
        test_tests_use_asyncio_marker,
        test_no_real_server_needed,
        test_e2e_init_created,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_conftest_imports_app_main,
        test_crud_test_has_update_case,
        test_auth_test_has_wrong_password_case,
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
    print(f"TOOL-094 add_e2e_test_suite: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
