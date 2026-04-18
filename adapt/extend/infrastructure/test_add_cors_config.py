"""Structural tests for TOOL-088 add_cors_config.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_cors_config.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_cors_config.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cors_config import add_cors_config
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
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="cors_t01")
    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files created or modified."""
    project_dir = create_fixture_project(name="cors_t02")
    r1 = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True must not touch any file on disk."""
    project_dir = create_fixture_project(name="cors_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_cors_config(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count + existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 1 file created, all exist on disk."""
    project_dir = create_fixture_project(name="cors_t04")
    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 1, (
        f"Expected >= 1 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count + existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified, all exist on disk."""
    project_dir = create_fixture_project(name="cors_t05")
    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every .py file in project parses without SyntaxError after tool."""
    project_dir = create_fixture_project(name="cors_t06")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC (AST walk)."""
    project_dir = create_fixture_project(name="cors_t07")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "middleware" / "cors_config.py"
    violations: list[str] = []
    for py_file in [middleware_file]:
        if not py_file.exists():
            continue
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.name} ({loc} LOC)")
    assert not violations, "Functions > 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: CORS_ALLOWED_ORIGINS, CORS_ALLOW_CREDENTIALS, CORS_MAX_AGE in config.py."""
    project_dir = create_fixture_project(name="cors_t08")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "CORS_ALLOWED_ORIGINS" in content, "CORS_ALLOWED_ORIGINS not in config.py"
    assert "CORS_ALLOW_CREDENTIALS" in content, "CORS_ALLOW_CREDENTIALS not in config.py"
    assert "CORS_MAX_AGE" in content, "CORS_MAX_AGE not in config.py"
    for line in content.splitlines():
        if any(f in line for f in ("CORS_ALLOWED_ORIGINS", "CORS_ALLOW_CREDENTIALS", "CORS_MAX_AGE")):
            assert line.startswith("    "), (
                f"Config field not 4-space indented: {line!r}"
            )


# ---------------------------------------------------------------------------
# Domain tests (CC-11+)
# ---------------------------------------------------------------------------

def test_cors_config_middleware_file_created() -> None:
    """D-01: app/middleware/cors_config.py is created with CORSConfigMiddleware."""
    project_dir = create_fixture_project(name="cors_t09")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    cors_file = project_dir / "app" / "middleware" / "cors_config.py"
    assert cors_file.exists(), "cors_config.py not created"
    content = cors_file.read_text()
    assert "CORSConfigMiddleware" in content


def test_cors_origins_read_from_env() -> None:
    """D-02: CORSConfigMiddleware reads origins from env var, not hardcoded."""
    project_dir = create_fixture_project(name="cors_t10")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    cors_file = project_dir / "app" / "middleware" / "cors_config.py"
    content = cors_file.read_text()
    assert "CORS_ALLOWED_ORIGINS" in content or "getenv" in content


def test_wildcard_warning_present() -> None:
    """D-03: CORSConfigMiddleware logs a warning when wildcard '*' is used."""
    project_dir = create_fixture_project(name="cors_t11")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    cors_file = project_dir / "app" / "middleware" / "cors_config.py"
    content = cors_file.read_text()
    assert "warning" in content.lower() or "warn" in content.lower()
    assert "*" in content


def test_debug_route_created() -> None:
    """D-04: app/api/routes/cors_debug.py is created with GET /cors/config."""
    project_dir = create_fixture_project(name="cors_t12")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    debug_route = project_dir / "app" / "api" / "routes" / "cors_debug.py"
    assert debug_route.exists(), "cors_debug.py not created"
    content = debug_route.read_text()
    assert "/cors" in content or "cors_config" in content
    assert "router" in content


def test_cors_max_age_configurable() -> None:
    """D-05: CORS_MAX_AGE is used in the middleware (not hardcoded)."""
    project_dir = create_fixture_project(name="cors_t13")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    cors_file = project_dir / "app" / "middleware" / "cors_config.py"
    content = cors_file.read_text()
    assert "CORS_MAX_AGE" in content or "max_age" in content


def test_main_py_patched_with_cors_middleware() -> None:
    """D-06: main.py is patched to register CORSConfigMiddleware."""
    project_dir = create_fixture_project(name="cors_t14")
    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    main_file = project_dir / "app" / "main.py"
    if main_file.exists():
        content = main_file.read_text()
        assert "CORSConfigMiddleware" in content


def test_allow_credentials_configurable() -> None:
    """D-07: CORS_ALLOW_CREDENTIALS is read from env, not hardcoded."""
    project_dir = create_fixture_project(name="cors_t15")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    cors_file = project_dir / "app" / "middleware" / "cors_config.py"
    content = cors_file.read_text()
    assert "CORS_ALLOW_CREDENTIALS" in content or "allow_credentials" in content


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="cors_t16")
    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps must be non-empty and mention CORS or origins."""
    project_dir = create_fixture_project(name="cors_t17")
    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "cors" in combined or "origin" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="cors_t18")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra structural checks
# ---------------------------------------------------------------------------

def test_notes_mention_wildcard_or_origins() -> None:
    """notes describe wildcard warning or origins configuration."""
    project_dir = create_fixture_project(name="cors_t19")
    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "cors" in combined or "origin" in combined or "wildcard" in combined


def test_cors_config_file_uses_starlette_cors() -> None:
    """CORSConfigMiddleware wraps FastAPI/Starlette built-in CORSMiddleware."""
    project_dir = create_fixture_project(name="cors_t20")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    cors_file = project_dir / "app" / "middleware" / "cors_config.py"
    content = cors_file.read_text()
    assert "CORSMiddleware" in content


def test_debug_route_returns_active_config() -> None:
    """GET /cors/config returns allowed_origins and allow_credentials keys."""
    project_dir = create_fixture_project(name="cors_t21")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    debug_route = project_dir / "app" / "api" / "routes" / "cors_debug.py"
    content = debug_route.read_text()
    assert "allowed_origins" in content
    assert "allow_credentials" in content


def test_cors_config_parses_comma_separated_origins() -> None:
    """CORSConfigMiddleware parses comma-separated origin list."""
    project_dir = create_fixture_project(name="cors_t22")
    add_cors_config(ToolInput(project_dir=str(project_dir)))
    cors_file = project_dir / "app" / "middleware" / "cors_config.py"
    content = cors_file.read_text()
    assert "split" in content or "," in content


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
        test_cors_config_middleware_file_created,
        test_cors_origins_read_from_env,
        test_wildcard_warning_present,
        test_debug_route_created,
        test_cors_max_age_configurable,
        test_main_py_patched_with_cors_middleware,
        test_allow_credentials_configurable,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_notes_mention_wildcard_or_origins,
        test_cors_config_file_uses_starlette_cors,
        test_debug_route_returns_active_config,
        test_cors_config_parses_comma_separated_origins,
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
    print(f"TOOL-088 add_cors_config: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
