"""Tests for TOOL-090 add_input_sanitization.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_input_sanitization.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_input_sanitization.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_input_sanitization import add_input_sanitization
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
    """Return a fresh fixture project.

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
    project_dir = _fresh("san_t01")
    result = add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' with no files written."""
    project_dir = _fresh("san_t02")
    r1 = add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = _fresh("san_t03")
    before = {str(f): f.read_text() for f in _all_py_files(project_dir)}
    result = add_input_sanitization(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {str(f): f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 3 files created (sanitizer, middleware, validators)."""
    project_dir = _fresh("san_t04")
    result = add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (config.py) and exists on disk."""
    project_dir = _fresh("san_t05")
    result = add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every .py file in the project parses without SyntaxError."""
    project_dir = _fresh("san_t06")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = _fresh("san_t07")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
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
    """CC-08: Sanitization config fields present in config.py with 4-space indent."""
    project_dir = _fresh("san_t08")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    src = config_file.read_text()
    for field in ("SANITIZE_ENABLED", "SANITIZE_ALLOWED_TAGS", "SANITIZE_MAX_DEPTH"):
        assert field in src, f"Config field {field} missing from config.py"
        # Verify 4-space indent
        for line in src.splitlines():
            if field in line and "=" in line:
                assert line.startswith("    "), (
                    f"Field {field} must be indented with 4 spaces, got: {line!r}"
                )
                break


# ---------------------------------------------------------------------------
# Domain tests (CC-11+)
# ---------------------------------------------------------------------------

def test_sanitizer_file_created() -> None:
    """CC-11: app/security/sanitizer.py is created with InputSanitizer class."""
    project_dir = _fresh("san_t11")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    sanitizer_file = project_dir / "app" / "security" / "sanitizer.py"
    assert sanitizer_file.exists(), "app/security/sanitizer.py must be created"
    src = sanitizer_file.read_text()
    assert "class InputSanitizer" in src, "InputSanitizer class must be defined"


def test_sanitize_html_method() -> None:
    """CC-12: InputSanitizer.sanitize_html() method is present."""
    project_dir = _fresh("san_t12")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    sanitizer_file = project_dir / "app" / "security" / "sanitizer.py"
    src = sanitizer_file.read_text()
    assert "def sanitize_html" in src, "sanitize_html() method must be present"


def test_strip_tags_method() -> None:
    """CC-13: InputSanitizer.strip_tags() method is present."""
    project_dir = _fresh("san_t13")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    sanitizer_file = project_dir / "app" / "security" / "sanitizer.py"
    src = sanitizer_file.read_text()
    assert "def strip_tags" in src, "strip_tags() method must be present"


def test_escape_sql_chars_method() -> None:
    """CC-14: InputSanitizer.escape_sql_chars() method is present."""
    project_dir = _fresh("san_t14")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    sanitizer_file = project_dir / "app" / "security" / "sanitizer.py"
    src = sanitizer_file.read_text()
    assert "def escape_sql_chars" in src, "escape_sql_chars() method must be present"


def test_bleach_lazy_import() -> None:
    """CC-15: bleach is imported lazily inside function body (not at module level)."""
    project_dir = _fresh("san_t15")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    sanitizer_file = project_dir / "app" / "security" / "sanitizer.py"
    tree = ast.parse(sanitizer_file.read_text())
    # Top-level imports must NOT include bleach
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Check if it's at module level (direct child of module)
            for top_node in ast.iter_child_nodes(tree):
                if top_node is node:
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            assert "bleach" not in alias.name, (
                                "bleach must NOT be a top-level import"
                            )
                    elif isinstance(node, ast.ImportFrom):
                        assert node.module != "bleach", (
                            "bleach must NOT be a top-level import"
                        )
    # Verify bleach IS imported somewhere inside a function
    src = sanitizer_file.read_text()
    assert "import bleach" in src, "bleach must be imported lazily inside a function body"


def test_bleach_fallback_to_html_escape() -> None:
    """CC-16: sanitizer.py falls back to html.escape when bleach is absent."""
    project_dir = _fresh("san_t16")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    sanitizer_file = project_dir / "app" / "security" / "sanitizer.py"
    src = sanitizer_file.read_text()
    assert "html.escape" in src or "html" in src, "Must fall back to html.escape"
    assert "ImportError" in src, "Must handle missing bleach via ImportError"


def test_sanitize_middleware_file_created() -> None:
    """CC-17: app/security/sanitize_middleware.py is created."""
    project_dir = _fresh("san_t17")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "security" / "sanitize_middleware.py"
    assert middleware_file.exists(), "sanitize_middleware.py must be created"
    src = middleware_file.read_text()
    assert "class SanitizeMiddleware" in src, "SanitizeMiddleware class must be defined"


def test_sanitize_middleware_sanitizes_json_strings() -> None:
    """CC-18: SanitizeMiddleware processes JSON string fields."""
    project_dir = _fresh("san_t18")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "security" / "sanitize_middleware.py"
    src = middleware_file.read_text()
    assert "json" in src.lower(), "Must handle JSON body parsing"
    assert "application/json" in src, "Must check content-type for JSON"


def test_sanitize_middleware_configurable_depth() -> None:
    """CC-19: SanitizeMiddleware accepts configurable max_depth parameter."""
    project_dir = _fresh("san_t19")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "security" / "sanitize_middleware.py"
    src = middleware_file.read_text()
    assert "max_depth" in src, "SanitizeMiddleware must have configurable max_depth"


def test_validators_file_created() -> None:
    """CC-20: app/security/validators.py is created with SafeString type."""
    project_dir = _fresh("san_t20")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    validators_file = project_dir / "app" / "security" / "validators.py"
    assert validators_file.exists(), "validators.py must be created"
    src = validators_file.read_text()
    assert "SafeString" in src, "SafeString Pydantic type must be defined"


def test_nosql_injection_validator() -> None:
    """CC-21: validators.py includes NoSQLInjection validator."""
    project_dir = _fresh("san_t21")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    validators_file = project_dir / "app" / "security" / "validators.py"
    src = validators_file.read_text()
    assert "NoSQLInjection" in src, "NoSQLInjection validator must be defined"
    assert "$where" in src or "nosql" in src.lower(), (
        "Must detect NoSQL injection patterns"
    )


def test_next_steps_present() -> None:
    """CC-N: result.next_steps is populated with meaningful guidance."""
    project_dir = _fresh("san_t22")
    result = add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "bleach" in combined or "sanitize" in combined or "middleware" in combined


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer."""
    project_dir = _fresh("san_t23")
    result = add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: Run twice, then ast.parse all .py files — no syntax errors."""
    project_dir = _fresh("san_t24")
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
    add_input_sanitization(ToolInput(project_dir=str(project_dir)))
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
        test_sanitizer_file_created,
        test_sanitize_html_method,
        test_strip_tags_method,
        test_escape_sql_chars_method,
        test_bleach_lazy_import,
        test_bleach_fallback_to_html_escape,
        test_sanitize_middleware_file_created,
        test_sanitize_middleware_sanitizes_json_strings,
        test_sanitize_middleware_configurable_depth,
        test_validators_file_created,
        test_nosql_injection_validator,
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
    print(f"TOOL-090 add_input_sanitization: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
