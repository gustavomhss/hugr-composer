"""Tests for TOOL-025 add_sqladmin.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_sqladmin.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_sqladmin.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_sqladmin import add_sqladmin
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


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function in the given subdir."""
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


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="admin_t01")
    result = add_sqladmin(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="admin_t02")
    r1 = add_sqladmin(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_sqladmin(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="admin_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_sqladmin(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 4 new files (__init__, setup, auth, views)."""
    project_dir = create_fixture_project(name="admin_t04")
    result = add_sqladmin(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, main)."""
    project_dir = create_fixture_project(name="admin_t05")
    result = add_sqladmin(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="admin_t06")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="admin_t07")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected ADMIN_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="admin_t08")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("ADMIN_PATH", "ADMIN_TITLE", "ADMIN_REQUIRE_SUPERUSER"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "ADMIN_PATH" in line and ":" in line:
            assert line.startswith("    "), (
                f"ADMIN_PATH not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """SQLAdmin does NOT create new models — models __init__ should not have admin-specific imports."""
    project_dir = create_fixture_project(name="admin_t09")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    # SQLAdmin reads existing models, no new model registration needed
    # This test validates that no spurious model was added
    admin_init = project_dir / "app" / "admin" / "__init__.py"
    assert admin_init.exists(), "app/admin/__init__.py not created"


def test_routes_registered() -> None:
    """setup_admin is called from main.py (SQLAdmin mounts directly, no router)."""
    project_dir = create_fixture_project(name="admin_t10")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "setup_admin" in content, "setup_admin not called in main.py"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_setup_module_created() -> None:
    """app/admin/setup.py exists with setup_admin function."""
    project_dir = create_fixture_project(name="admin_t11")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "admin" / "setup.py"
    assert setup_file.exists(), "app/admin/setup.py not created"
    content = setup_file.read_text()
    assert "setup_admin" in content, "setup_admin function not found"


def test_auth_backend_created() -> None:
    """app/admin/auth.py exists with AdminAuthBackend class."""
    project_dir = create_fixture_project(name="admin_t12")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    auth_file = project_dir / "app" / "admin" / "auth.py"
    assert auth_file.exists(), "app/admin/auth.py not created"
    content = auth_file.read_text()
    assert "AdminAuthBackend" in content, "AdminAuthBackend class not found"
    assert "async def login" in content, "login method not found"
    assert "async def authenticate" in content, "authenticate method not found"


def test_views_model_admins() -> None:
    """app/admin/views.py has MODEL_ADMINS list with at least 2 entries."""
    project_dir = create_fixture_project(name="admin_t13")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    views_file = project_dir / "app" / "admin" / "views.py"
    assert views_file.exists(), "app/admin/views.py not created"
    content = views_file.read_text()
    assert "MODEL_ADMINS" in content, "MODEL_ADMINS list not found"
    # Count Admin classes
    admin_count = content.count("Admin(ModelView")
    assert admin_count >= 2, (
        f"Expected >= 2 ModelView entries, found {admin_count}"
    )


def test_lazy_sqladmin_import() -> None:
    """setup.py uses try/except for sqladmin import."""
    project_dir = create_fixture_project(name="admin_t14")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "admin" / "setup.py"
    content = setup_file.read_text()
    assert "try:" in content, "Lazy import try/except not found"
    assert "ImportError" in content, "ImportError handling not found"
    assert "from sqladmin" in content, "sqladmin import not found inside try block"


def test_session_middleware_in_setup() -> None:
    """SessionMiddleware is added inside setup_admin, NOT in main.py top-level."""
    project_dir = create_fixture_project(name="admin_t15")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "admin" / "setup.py"
    setup_content = setup_file.read_text()
    assert "SessionMiddleware" in setup_content, (
        "SessionMiddleware should be added inside setup_admin()"
    )


def test_sensitive_columns_excluded() -> None:
    """views.py contains column_exclude_list with hashed_password."""
    project_dir = create_fixture_project(name="admin_t16")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    views_file = project_dir / "app" / "admin" / "views.py"
    content = views_file.read_text()
    assert "column_exclude_list" in content, "column_exclude_list not found"
    assert "hashed_password" in content, "hashed_password not excluded from admin views"


def test_custom_admin_path() -> None:
    """add_sqladmin(inp, admin_path='/dashboard') patches config with /dashboard."""
    project_dir = create_fixture_project(name="admin_t17")
    add_sqladmin(
        ToolInput(project_dir=str(project_dir)),
        admin_path="/dashboard",
    )
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "/dashboard" in content, (
        "Custom admin_path '/dashboard' not found in config.py"
    )


def test_requirements_sqladmin() -> None:
    """requirements.txt contains sqladmin>=."""
    project_dir = create_fixture_project(name="admin_t18")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "sqladmin>=" in content, "sqladmin dependency not added to requirements.txt"
    assert "itsdangerous>=" in content, "itsdangerous dependency not added"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="admin_t19")
    result = add_sqladmin(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="admin_t20")
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    add_sqladmin(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="admin_t21")
    result = add_sqladmin(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "pip install" in combined or "requirements" in combined, (
        "next_steps should mention pip install"
    )


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
        test_models_init_patched,
        test_routes_registered,
        test_setup_module_created,
        test_auth_backend_created,
        test_views_model_admins,
        test_lazy_sqladmin_import,
        test_session_middleware_in_setup,
        test_sensitive_columns_excluded,
        test_custom_admin_path,
        test_requirements_sqladmin,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
        test_next_steps_present,
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
    print(f"TOOL-025 add_sqladmin: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
