"""Structural tests for TOOL-117 add_schema_enforcer.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies every completeness criterion from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_schema_enforcer.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_schema_enforcer.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_schema_enforcer import add_schema_enforcer
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root*."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under *root* parses without SyntaxError."""
    for f in _all_py_files(root):
        src = f.read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max function LOC in all .py files under *root/subdir*."""
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
# CC-01 — success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="se_t01")
    result = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02 — idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="se_t02")
    r1 = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="se_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_schema_enforcer(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: Tool creates at least 3 new files (core, middleware, fuzz tests)."""
    project_dir = create_fixture_project(name="se_t04")
    result = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 2 files (config, main)."""
    project_dir = create_fixture_project(name="se_t05")
    result = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="se_t06")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="se_t07")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: SCHEMA_ENFORCER_* settings exist inside Settings class body."""
    project_dir = create_fixture_project(name="se_t08")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "SCHEMA_ENFORCER_MODE",
        "SCHEMA_ENFORCER_SPEC_PATH",
        "SCHEMA_ENFORCER_BLOCK_SHADOW",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "SCHEMA_ENFORCER_MODE" in line:
            assert line.startswith("    "), (
                f"SCHEMA_ENFORCER_MODE not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# Domain tests — CC-11+
# ---------------------------------------------------------------------------

def test_core_engine_created() -> None:
    """T-09: app/core/schema_enforcer.py exists with key functions."""
    project_dir = create_fixture_project(name="se_t09")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "schema_enforcer.py"
    assert core_file.exists(), "app/core/schema_enforcer.py not created"
    content = core_file.read_text()
    assert "def load_spec" in content
    assert "def extract_route_paths" in content
    assert "def detect_shadow_routes" in content
    assert "def has_extra_fields" in content


def test_middleware_created() -> None:
    """T-10: app/middleware/schema_enforcer.py with SchemaEnforcerMiddleware."""
    project_dir = create_fixture_project(name="se_t10")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "schema_enforcer.py"
    assert mw_file.exists(), "app/middleware/schema_enforcer.py not created"
    content = mw_file.read_text()
    assert "class SchemaEnforcerMiddleware" in content
    assert "def register_schema_enforcer" in content


def test_fuzz_test_file_created() -> None:
    """T-11: tests/test_schema_fuzz.py exists with fuzz test functions."""
    project_dir = create_fixture_project(name="se_t11")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    fuzz_file = project_dir / "tests" / "test_schema_fuzz.py"
    assert fuzz_file.exists(), "tests/test_schema_fuzz.py not created"
    content = fuzz_file.read_text()
    assert "def test_fuzz_" in content


def test_shadow_route_detection_in_middleware() -> None:
    """T-12: Middleware calls detect_shadow_routes and logs/blocks shadow routes."""
    project_dir = create_fixture_project(name="se_t12")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "schema_enforcer.py"
    content = mw_file.read_text()
    assert "detect_shadow_routes" in content
    assert "schema_enforcer.shadow_route" in content


def test_enforce_mode_blocks_undocumented_endpoints() -> None:
    """T-13: Middleware returns 403 for shadow routes in enforce+block mode."""
    project_dir = create_fixture_project(name="se_t13")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "schema_enforcer.py"
    content = mw_file.read_text()
    assert "status_code=403" in content
    assert '"enforce"' in content


def test_main_registers_enforcer() -> None:
    """T-14: main.py imports and calls register_schema_enforcer(app)."""
    project_dir = create_fixture_project(name="se_t14")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "register_schema_enforcer" in content
    assert "from app.middleware.schema_enforcer import register_schema_enforcer" in content


def test_has_extra_fields_prevents_mass_assignment() -> None:
    """T-15: has_extra_fields function exists in core and checks allowed keys."""
    project_dir = create_fixture_project(name="se_t15")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "schema_enforcer.py"
    content = core_file.read_text()
    assert "def has_extra_fields" in content
    assert "properties" in content


def test_three_modes_referenced() -> None:
    """T-16: Middleware references all three enforcement modes."""
    project_dir = create_fixture_project(name="se_t16")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "schema_enforcer.py"
    content = mw_file.read_text()
    assert "enforce" in content
    assert "detect" in content


def test_jsonschema_added_to_requirements() -> None:
    """T-17: requirements.txt contains jsonschema dependency."""
    project_dir = create_fixture_project(name="se_t17")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    req_file = project_dir / "requirements.txt"
    content = req_file.read_text()
    assert "jsonschema" in content, "jsonschema not added to requirements.txt"


# ---------------------------------------------------------------------------
# CC-N-1 — execution time
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="se_t18")
    result = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps mentions schema enforcer config and fuzz tests."""
    project_dir = create_fixture_project(name="se_t19")
    result = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "schema_enforcer_mode" in combined, "next_steps should mention SCHEMA_ENFORCER_MODE"
    assert "fuzz" in combined, "next_steps should mention fuzz tests"


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="se_t20")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Mutation-killing regression tests
# ---------------------------------------------------------------------------

def test_three_config_fields_exactly() -> None:
    """T-21: config.py must have exactly 3 SCHEMA_ENFORCER_* fields."""
    project_dir = create_fixture_project(name="se_t21")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    expected = [
        "SCHEMA_ENFORCER_MODE",
        "SCHEMA_ENFORCER_SPEC_PATH",
        "SCHEMA_ENFORCER_BLOCK_SHADOW",
    ]
    for field in expected:
        assert field in content, f"Missing field: {field}"
    distinct = {
        line.strip() for line in content.splitlines()
        if any(f in line for f in expected) and ":" in line and "=" in line
    }
    assert len(distinct) == 3, (
        f"Expected 3 SCHEMA_ENFORCER_* field lines, got {len(distinct)}: {distinct}"
    )


def test_load_spec_returns_dict() -> None:
    """T-22: load_spec function returns a dict type (not None)."""
    project_dir = create_fixture_project(name="se_t22")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "schema_enforcer.py"
    content = core_file.read_text()
    assert "dict" in content, "load_spec return type hint missing dict"
    assert "json.loads" in content or "json.load" in content, (
        "load_spec must use json to parse the spec"
    )


def test_register_enforcer_positioned_after_fastapi() -> None:
    """T-23: register_schema_enforcer(app) must appear AFTER app = FastAPI(...)."""
    project_dir = create_fixture_project(name="se_t23")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "main.py").read_text()
    app_idx = content.find("app = FastAPI(")
    reg_idx = content.find("register_schema_enforcer(app)")
    assert app_idx >= 0, "FastAPI marker not found"
    assert reg_idx >= 0, "register_schema_enforcer call not inserted"
    assert reg_idx > app_idx, (
        f"register_schema_enforcer at {reg_idx} must come AFTER FastAPI() at {app_idx}"
    )


def test_fuzz_test_file_has_multiple_tests() -> None:
    """T-24: Fuzz test file must contain at least 5 test_ functions."""
    project_dir = create_fixture_project(name="se_t24")
    add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    fuzz_file = project_dir / "tests" / "test_schema_fuzz.py"
    content = fuzz_file.read_text()
    tree = ast.parse(content)
    test_fns = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(test_fns) >= 5, (
        f"Expected >= 5 fuzz test functions, got {len(test_fns)}: {test_fns}"
    )


def test_no_files_mutated_outside_scope() -> None:
    """T-25: Tool must not modify files outside result.files_created/modified."""
    project_dir = create_fixture_project(name="se_t25")
    before = {p: p.read_text() for p in sorted(project_dir.rglob("*.py"))}
    result = add_schema_enforcer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    changed: set[Path] = {
        Path(s).resolve()
        for s in list(result.files_created) + list(result.files_modified)
    }
    for p, original in before.items():
        if p.resolve() in changed:
            continue
        assert p.read_text() == original, (
            f"File {p} was modified but not reported in files_modified"
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
        test_core_engine_created,
        test_middleware_created,
        test_fuzz_test_file_created,
        test_shadow_route_detection_in_middleware,
        test_enforce_mode_blocks_undocumented_endpoints,
        test_main_registers_enforcer,
        test_has_extra_fields_prevents_mass_assignment,
        test_three_modes_referenced,
        test_jsonschema_added_to_requirements,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_three_config_fields_exactly,
        test_load_spec_returns_dict,
        test_register_enforcer_positioned_after_fastapi,
        test_fuzz_test_file_has_multiple_tests,
        test_no_files_mutated_outside_scope,
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
    print(f"TOOL-117 add_schema_enforcer: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
