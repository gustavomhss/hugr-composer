"""Tests for TOOL-089 add_csrf_protection.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_csrf_protection.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_csrf_protection.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_csrf_protection import add_csrf_protection
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root* sorted by path.

    Args:
        root: Directory to walk.

    Returns:
        Sorted list of .py Path objects.
    """
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under *root* has valid syntax.

    Args:
        root: Project root to walk.

    Raises:
        AssertionError: If any file fails ast.parse.
    """
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _fresh(name: str) -> Path:
    """Return a fresh fixture project for test isolation.

    Args:
        name: Unique project name.

    Returns:
        Path to generated project root.
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = _fresh("csrf_t01")
    result = add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' with no files written."""
    project_dir = _fresh("csrf_t02")
    r1 = add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = _fresh("csrf_t03")
    before = {str(f): f.read_text() for f in _all_py_files(project_dir)}
    result = add_csrf_protection(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {str(f): f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 4 files created and all exist on disk."""
    project_dir = _fresh("csrf_t04")
    result = add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified and all exist on disk."""
    project_dir = _fresh("csrf_t05")
    result = add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every .py file in the project parses without SyntaxError."""
    project_dir = _fresh("csrf_t06")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = _fresh("csrf_t07")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    security_dir = project_dir / "app" / "security"
    for py_file in sorted(security_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = node.end_lineno - node.lineno + 1
                assert loc <= 50, (
                    f"Function {node.name!r} in {py_file} has {loc} lines (max 50)"
                )


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: CSRF config fields present in config.py with 4-space indent."""
    project_dir = _fresh("csrf_t08")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    src = config_file.read_text()
    assert "CSRF_ENABLED" in src
    assert "CSRF_SECRET_KEY" in src
    assert "CSRF_COOKIE_NAME" in src
    assert "CSRF_HEADER_NAME" in src
    assert "CSRF_EXEMPT_PATHS" in src
    # Verify 4-space indent on config fields
    for field in ("CSRF_ENABLED", "CSRF_SECRET_KEY", "CSRF_COOKIE_NAME"):
        for line in src.splitlines():
            if field in line and "=" in line:
                assert line.startswith("    "), (
                    f"Field {field} must be indented with 4 spaces, got: {line!r}"
                )
                break


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: csrf.py router is created in app/api/routes/."""
    project_dir = _fresh("csrf_t10")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_route = project_dir / "app" / "api" / "routes" / "csrf.py"
    assert csrf_route.exists(), "app/api/routes/csrf.py must be created"
    src = csrf_route.read_text()
    assert "router" in src, "csrf route file must define a router"


# ---------------------------------------------------------------------------
# Domain tests (CC-11+)
# ---------------------------------------------------------------------------

def test_csrf_security_init_created() -> None:
    """CC-11: app/security/__init__.py is created."""
    project_dir = _fresh("csrf_t11")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "security" / "__init__.py"
    assert init_file.exists(), "app/security/__init__.py must be created"
    src = init_file.read_text()
    assert "CSRFProtection" in src, "security __init__.py must export CSRFProtection"


def test_csrf_core_file_created() -> None:
    """CC-12: app/security/csrf.py is created with CSRFProtection class."""
    project_dir = _fresh("csrf_t12")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_file = project_dir / "app" / "security" / "csrf.py"
    assert csrf_file.exists(), "app/security/csrf.py must be created"
    src = csrf_file.read_text()
    assert "class CSRFProtection" in src, "CSRFProtection class must be defined"


def test_csrf_generate_token_method() -> None:
    """CC-13: CSRFProtection.generate_token() method is present."""
    project_dir = _fresh("csrf_t13")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_file = project_dir / "app" / "security" / "csrf.py"
    src = csrf_file.read_text()
    assert "def generate_token" in src, "generate_token() method must be present"


def test_csrf_validate_token_method() -> None:
    """CC-14: CSRFProtection.validate_token() method is present."""
    project_dir = _fresh("csrf_t14")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_file = project_dir / "app" / "security" / "csrf.py"
    src = csrf_file.read_text()
    assert "def validate_token" in src, "validate_token() method must be present"


def test_csrf_get_csrf_cookie_method() -> None:
    """CC-15: CSRFProtection.get_csrf_cookie() method is present."""
    project_dir = _fresh("csrf_t15")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_file = project_dir / "app" / "security" / "csrf.py"
    src = csrf_file.read_text()
    assert "def get_csrf_cookie" in src, "get_csrf_cookie() method must be present"


def test_csrf_middleware_file_created() -> None:
    """CC-16: app/security/csrf_middleware.py is created with CSRFMiddleware."""
    project_dir = _fresh("csrf_t16")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "security" / "csrf_middleware.py"
    assert middleware_file.exists(), "csrf_middleware.py must be created"
    src = middleware_file.read_text()
    assert "class CSRFMiddleware" in src, "CSRFMiddleware class must be defined"


def test_csrf_middleware_checks_unsafe_methods() -> None:
    """CC-17: CSRFMiddleware checks POST/PUT/PATCH/DELETE."""
    project_dir = _fresh("csrf_t17")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "security" / "csrf_middleware.py"
    src = middleware_file.read_text()
    assert "POST" in src, "CSRFMiddleware must check POST"
    assert "PUT" in src, "CSRFMiddleware must check PUT"
    assert "PATCH" in src, "CSRFMiddleware must check PATCH"
    assert "DELETE" in src, "CSRFMiddleware must check DELETE"


def test_csrf_middleware_double_submit_pattern() -> None:
    """CC-18: CSRFMiddleware implements double-submit (cookie + header comparison)."""
    project_dir = _fresh("csrf_t18")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "security" / "csrf_middleware.py"
    src = middleware_file.read_text()
    assert "cookie" in src.lower(), "Must check cookie token"
    assert "header" in src.lower(), "Must check header token"


def test_csrf_token_route_get_endpoint() -> None:
    """CC-19: GET /csrf/token endpoint is defined."""
    project_dir = _fresh("csrf_t19")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_route = project_dir / "app" / "api" / "routes" / "csrf.py"
    src = csrf_route.read_text()
    assert "router.get" in src or "@router.get" in src, "GET endpoint must be defined"
    assert "/token" in src, "Endpoint path must include /token"


def test_csrf_no_external_deps() -> None:
    """CC-20: csrf.py uses only stdlib (hmac, hashlib, secrets) — no external deps."""
    project_dir = _fresh("csrf_t20")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_file = project_dir / "app" / "security" / "csrf.py"
    src = csrf_file.read_text()
    assert "hmac" in src, "Must use stdlib hmac"
    assert "hashlib" in src, "Must use stdlib hashlib"
    assert "secrets" in src, "Must use stdlib secrets"
    # No external crypto libraries
    for ext_lib in ("cryptography", "itsdangerous", "passlib"):
        assert ext_lib not in src, f"Must not depend on {ext_lib}"


def test_csrf_samesite_cookie() -> None:
    """CC-21: SameSite cookie attribute is used."""
    project_dir = _fresh("csrf_t21")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    csrf_file = project_dir / "app" / "security" / "csrf.py"
    src = csrf_file.read_text()
    assert "samesite" in src.lower(), "Must set SameSite cookie attribute"


def test_csrf_403_on_missing_token() -> None:
    """CC-22: CSRFMiddleware returns 403 when token is missing."""
    project_dir = _fresh("csrf_t22")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "security" / "csrf_middleware.py"
    src = middleware_file.read_text()
    assert "403" in src, "Must return 403 when CSRF token is missing"
    assert "CSRF token missing" in src or "detail" in src


def test_next_steps_present() -> None:
    """CC-N: result.next_steps is populated with meaningful guidance."""
    project_dir = _fresh("csrf_t23")
    result = add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "csrf" in combined or "secret" in combined


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer."""
    project_dir = _fresh("csrf_t24")
    result = add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: Run twice, then ast.parse all .py files — no syntax errors."""
    project_dir = _fresh("csrf_t25")
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    add_csrf_protection(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


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
        test_routes_registered,
        test_csrf_security_init_created,
        test_csrf_core_file_created,
        test_csrf_generate_token_method,
        test_csrf_validate_token_method,
        test_csrf_get_csrf_cookie_method,
        test_csrf_middleware_file_created,
        test_csrf_middleware_checks_unsafe_methods,
        test_csrf_middleware_double_submit_pattern,
        test_csrf_token_route_get_endpoint,
        test_csrf_no_external_deps,
        test_csrf_samesite_cookie,
        test_csrf_403_on_missing_token,
        test_next_steps_present,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
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

    print(f"\n{'=' * 60}")
    print(f"TOOL-089 add_csrf_protection: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
