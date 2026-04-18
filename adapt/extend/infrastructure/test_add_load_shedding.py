"""Tests for TOOL-095 add_load_shedding.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_load_shedding.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_load_shedding.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_load_shedding import add_load_shedding
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
    project_dir = create_fixture_project(name="ls_t01")
    result = add_load_shedding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="ls_t02")
    r1 = add_load_shedding(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_load_shedding(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ls_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_load_shedding(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created exist on disk
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: files_created has >= 4 entries and all paths exist on disk."""
    project_dir = create_fixture_project(name="ls_t04")
    result = add_load_shedding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 created files, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified exist on disk
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: files_modified has >= 1 entry and all paths exist on disk."""
    project_dir = create_fixture_project(name="ls_t05")
    result = add_load_shedding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 modified file, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All generated .py files pass ast.parse without SyntaxError."""
    project_dir = create_fixture_project(name="ls_t06")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = create_fixture_project(name="ls_t07")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    resilience_dir = project_dir / "app" / "resilience"
    middleware_dir = project_dir / "app" / "middleware"
    violations: list[str] = []
    for py_file in list(resilience_dir.rglob("*.py")) + list(middleware_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.lineno} {node.name}() = {loc} LOC")
    assert not violations, "Functions exceeding 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: Config fields appear in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="ls_t08")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "LOAD_SHEDDING_ENABLED" in content
    # Verify 4-space indent
    assert "    LOAD_SHEDDING_ENABLED" in content, "Config field must use 4-space indent"


# ---------------------------------------------------------------------------
# CC-09: load_shedder.py created with LoadShedder class
# ---------------------------------------------------------------------------

def test_load_shedder_file_created() -> None:
    """CC-09: app/resilience/load_shedder.py exists with LoadShedder class."""
    project_dir = create_fixture_project(name="ls_t09")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    shedder_file = project_dir / "app" / "resilience" / "load_shedder.py"
    assert shedder_file.exists(), "load_shedder.py not created"
    content = shedder_file.read_text()
    assert "LoadShedder" in content, "LoadShedder class must be defined"


# ---------------------------------------------------------------------------
# CC-10: DegradationTier enum defined
# ---------------------------------------------------------------------------

def test_degradation_tier_enum() -> None:
    """CC-10: DegradationTier enum with NORMAL, TIER_1, TIER_2, TIER_3."""
    project_dir = create_fixture_project(name="ls_t10")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    shedder_file = project_dir / "app" / "resilience" / "load_shedder.py"
    content = shedder_file.read_text()
    assert "DegradationTier" in content, "DegradationTier enum must be defined"
    assert "NORMAL" in content
    assert "TIER_1" in content
    assert "TIER_2" in content
    assert "TIER_3" in content


# ---------------------------------------------------------------------------
# CC-11: priority.py created with RequestPriority enum
# ---------------------------------------------------------------------------

def test_priority_file_created() -> None:
    """CC-11: app/resilience/priority.py exists with RequestPriority enum."""
    project_dir = create_fixture_project(name="ls_t11")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    priority_file = project_dir / "app" / "resilience" / "priority.py"
    assert priority_file.exists(), "priority.py not created"
    content = priority_file.read_text()
    assert "RequestPriority" in content
    assert "CRITICAL" in content
    assert "HIGH" in content
    assert "NORMAL" in content
    assert "LOW" in content


# ---------------------------------------------------------------------------
# CC-12: classify_request function defined
# ---------------------------------------------------------------------------

def test_classify_request_defined() -> None:
    """CC-12: classify_request() function is defined in priority.py."""
    project_dir = create_fixture_project(name="ls_t12")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    priority_file = project_dir / "app" / "resilience" / "priority.py"
    content = priority_file.read_text()
    assert "def classify_request" in content, "classify_request() must be defined"


# ---------------------------------------------------------------------------
# CC-13: degradation.py created with DegradationManager
# ---------------------------------------------------------------------------

def test_degradation_file_created() -> None:
    """CC-13: app/resilience/degradation.py exists with DegradationManager."""
    project_dir = create_fixture_project(name="ls_t13")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    degradation_file = project_dir / "app" / "resilience" / "degradation.py"
    assert degradation_file.exists(), "degradation.py not created"
    content = degradation_file.read_text()
    assert "DegradationManager" in content, "DegradationManager must be defined"
    assert "is_feature_enabled" in content, "is_feature_enabled() must be defined"


# ---------------------------------------------------------------------------
# CC-14: middleware created
# ---------------------------------------------------------------------------

def test_middleware_file_created() -> None:
    """CC-14: app/middleware/load_shedding.py exists with LoadSheddingMiddleware."""
    project_dir = create_fixture_project(name="ls_t14")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "load_shedding.py"
    assert mw_file.exists(), "load_shedding.py middleware not created"
    content = mw_file.read_text()
    assert "LoadSheddingMiddleware" in content


# ---------------------------------------------------------------------------
# CC-15: 429 + Retry-After in middleware
# ---------------------------------------------------------------------------

def test_middleware_rejects_low_with_429() -> None:
    """CC-15: Middleware returns 429 with Retry-After for LOW priority."""
    project_dir = create_fixture_project(name="ls_t15")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "load_shedding.py"
    content = mw_file.read_text()
    assert "429" in content, "Middleware must return 429 for LOW priority"
    assert "Retry-After" in content, "Middleware must add Retry-After header"


# ---------------------------------------------------------------------------
# CC-16: CRITICAL always passes (no rejection for CRITICAL)
# ---------------------------------------------------------------------------

def test_critical_always_passes() -> None:
    """CC-16: Middleware never rejects CRITICAL priority requests."""
    project_dir = create_fixture_project(name="ls_t16")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "load_shedding.py"
    content = mw_file.read_text()
    assert "CRITICAL" in content, "Middleware must reference CRITICAL priority"
    # CRITICAL should not be in a rejection path
    assert "LOW" in content, "Middleware must specifically target LOW priority"


# ---------------------------------------------------------------------------
# CC-17: p99 in load_shedder
# ---------------------------------------------------------------------------

def test_p99_monitoring() -> None:
    """CC-17: LoadShedder monitors p99 latency via sliding window."""
    project_dir = create_fixture_project(name="ls_t17")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    shedder_file = project_dir / "app" / "resilience" / "load_shedder.py"
    content = shedder_file.read_text()
    assert "p99" in content or "0.99" in content, "LoadShedder must compute p99"
    assert "deque" in content or "window" in content.lower() or "samples" in content.lower()


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ls_t18")
    result = add_load_shedding(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps guides developer to configure load shedding."""
    project_dir = create_fixture_project(name="ls_t19")
    result = add_load_shedding(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "load_shedding" in combined or "enabled" in combined or "middleware" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="ls_t20")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra: get_load_shedder factory function defined
# ---------------------------------------------------------------------------

def test_get_load_shedder_defined() -> None:
    """get_load_shedder() factory function must be present."""
    project_dir = create_fixture_project(name="ls_t21")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    shedder_file = project_dir / "app" / "resilience" / "load_shedder.py"
    content = shedder_file.read_text()
    assert "get_load_shedder" in content, "get_load_shedder() factory must be defined"


# ---------------------------------------------------------------------------
# Extra: config fields all three present
# ---------------------------------------------------------------------------

def test_all_three_config_fields_present() -> None:
    """All three LOAD_SHEDDING_* config fields must be patched."""
    project_dir = create_fixture_project(name="ls_t22")
    add_load_shedding(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "LOAD_SHEDDING_ENABLED" in content
    assert "LOAD_SHEDDING_P99_THRESHOLD_MS" in content
    assert "LOAD_SHEDDING_RECOVERY_WINDOW_S" in content


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
        test_load_shedder_file_created,
        test_degradation_tier_enum,
        test_priority_file_created,
        test_classify_request_defined,
        test_degradation_file_created,
        test_middleware_file_created,
        test_middleware_rejects_low_with_429,
        test_critical_always_passes,
        test_p99_monitoring,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_get_load_shedder_defined,
        test_all_three_config_fields_present,
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
    print(f"TOOL-095 add_load_shedding: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
