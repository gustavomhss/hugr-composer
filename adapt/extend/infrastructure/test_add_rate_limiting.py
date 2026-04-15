"""Tests for TOOL-057 add_rate_limiting.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies every completeness criterion from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_rate_limiting.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_rate_limiting.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_rate_limiting import add_rate_limiting
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        src = f.read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
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
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="rl_t01")
    result = add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """T-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="rl_t02")
    r1 = add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """T-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="rl_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_rate_limiting(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """T-04: Tool creates at least 3 new files (core, middleware, status route)."""
    project_dir = create_fixture_project(name="rl_t04")
    result = add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """T-05: Tool modifies at least 2 files (config, requirements)."""
    project_dir = create_fixture_project(name="rl_t05")
    result = add_rate_limiting(ToolInput(project_dir=str(project_dir)))
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
    """T-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="rl_t06")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """T-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="rl_t07")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """T-08: RATE_LIMIT_* settings exist inside Settings class body."""
    project_dir = create_fixture_project(name="rl_t08")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "RATE_LIMIT_ENABLED",
        "RATE_LIMIT_DEFAULT",
        "RATE_LIMIT_STRATEGY",
        "RATE_LIMIT_HEADERS_ENABLED",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify at least one field is inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "RATE_LIMIT_ENABLED" in line:
            assert line.startswith("    "), (
                f"RATE_LIMIT_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_main_registers_rate_limiting() -> None:
    """T-09: main.py imports and calls register_rate_limiting(app)."""
    project_dir = create_fixture_project(name="rl_t09")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "register_rate_limiting" in content
    assert "from app.middleware.rate_limit import register_rate_limiting" in content


def test_requirements_patched() -> None:
    """T-10: requirements.txt contains slowapi and limits."""
    project_dir = create_fixture_project(name="rl_t10")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    req_file = project_dir / "requirements.txt"
    content = req_file.read_text()
    assert "slowapi" in content, "slowapi not added to requirements.txt"
    assert "limits" in content, "limits not added to requirements.txt"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_core_module_created() -> None:
    """T-11: app/core/rate_limit.py exists with RateLimitConfig and get_limiter."""
    project_dir = create_fixture_project(name="rl_t11")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "rate_limit.py"
    assert core_file.exists(), "app/core/rate_limit.py not created"
    content = core_file.read_text()
    assert "class RateLimitConfig" in content
    assert "def get_limiter" in content
    assert "def build_config" in content


def test_three_key_strategies() -> None:
    """T-12: Core module exports key_ip, key_user, key_user_endpoint."""
    project_dir = create_fixture_project(name="rl_t12")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "rate_limit.py"
    content = core_file.read_text()
    for key_fn in ("key_ip", "key_user", "key_user_endpoint"):
        assert f"def {key_fn}" in content, f"Key function {key_fn} missing"


def test_middleware_module_created() -> None:
    """T-13: app/middleware/rate_limit.py exists with register_rate_limiting."""
    project_dir = create_fixture_project(name="rl_t13")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "rate_limit.py"
    assert mw_file.exists(), "app/middleware/rate_limit.py not created"
    content = mw_file.read_text()
    assert "def register_rate_limiting" in content
    assert "SlowAPIMiddleware" in content
    assert "rate_limit_exceeded_handler" in content


def test_exception_handler_emits_429() -> None:
    """T-14: Exception handler returns 429 with Retry-After header."""
    project_dir = create_fixture_project(name="rl_t14")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "rate_limit.py"
    content = mw_file.read_text()
    assert "status_code=429" in content
    assert "Retry-After" in content
    assert "X-RateLimit-Limit" in content


def test_status_route_created() -> None:
    """T-15: app/api/routes/rate_limit.py exposes GET /rate-limit/status."""
    project_dir = create_fixture_project(name="rl_t15")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "rate_limit.py"
    assert route_file.exists(), "status route not created"
    content = route_file.read_text()
    assert "/status" in content
    assert "RateLimitStatus" in content
    assert "APIRouter" in content


def test_storage_uri_falls_back_to_memory() -> None:
    """T-16: When REDIS_URL is unset, storage falls back to memory://."""
    project_dir = create_fixture_project(name="rl_t16")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "rate_limit.py"
    content = core_file.read_text()
    assert '"memory://"' in content or "'memory://'" in content


def test_default_limits_from_settings() -> None:
    """T-17: Limiter reads default_limits from settings.RATE_LIMIT_DEFAULT."""
    project_dir = create_fixture_project(name="rl_t17")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "rate_limit.py"
    content = core_file.read_text()
    assert "settings.RATE_LIMIT_DEFAULT" in content


def test_execution_time_recorded() -> None:
    """T-18: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="rl_t18")
    result = add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """T-19: next_steps mentions slowapi and REDIS_URL."""
    project_dir = create_fixture_project(name="rl_t19")
    result = add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "slowapi" in combined, "next_steps should mention slowapi"
    assert "redis_url" in combined, "next_steps should mention REDIS_URL"


def test_idempotent_project_still_parses() -> None:
    """T-20: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="rl_t20")
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
    add_rate_limiting(ToolInput(project_dir=str(project_dir)))
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
        test_main_registers_rate_limiting,
        test_requirements_patched,
        test_core_module_created,
        test_three_key_strategies,
        test_middleware_module_created,
        test_exception_handler_emits_429,
        test_status_route_created,
        test_storage_uri_falls_back_to_memory,
        test_default_limits_from_settings,
        test_execution_time_recorded,
        test_next_steps_present,
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

    print(f"\n{'='*60}")
    print(f"TOOL-057 add_rate_limiting: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
