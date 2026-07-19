"""Tests for TOOL-101 add_api_replay_debugger.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria (CC-01 through CC-LAST).

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_api_replay_debugger.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_api_replay_debugger.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_api_replay_debugger import add_api_replay_debugger
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
    project_dir = create_fixture_project(name="replay_t01")
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="replay_t02")
    r1 = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes nothing."""
    project_dir = create_fixture_project(name="replay_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_api_replay_debugger(
        ToolInput(project_dir=str(project_dir), dry_run=True)
    )
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 5 files created, all existing on disk."""
    project_dir = create_fixture_project(name="replay_t04")
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (config), all existing on disk."""
    project_dir = create_fixture_project(name="replay_t05")
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 file modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All created .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="replay_t06")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    debug_dir = project_dir / "app" / "debug"
    for py_file in sorted(debug_dir.rglob("*.py")):
        source = py_file.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="replay_t07")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    app_dir = project_dir / "app"
    violations: list[str] = []
    for py_file in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    if loc > 50:
                        violations.append(
                            f"{py_file.relative_to(project_dir)}::{node.name} ({loc} LOC)"
                        )
    assert not violations, "Functions exceed 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: DEBUG_RECORDER_ENABLED in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="replay_t08")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists(), "config.py not found"
    content = config_file.read_text()
    assert "DEBUG_RECORDER_ENABLED" in content
    for line in content.splitlines():
        if "DEBUG_RECORDER_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"Config field must have 4-space indent: {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09: models/__init__.py untouched (no model in this tool)
# ---------------------------------------------------------------------------

def test_models_init_not_broken() -> None:
    """CC-09: models/__init__.py still parseable after tool run."""
    project_dir = create_fixture_project(name="replay_t09")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    if models_init.exists():
        ast.parse(models_init.read_text())


# ---------------------------------------------------------------------------
# CC-10: routes registered in debug.py
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: debug.py route file uses APIRouter with /debug prefix."""
    project_dir = create_fixture_project(name="replay_t10")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    debug_route = project_dir / "app" / "api" / "routes" / "debug.py"
    assert debug_route.exists(), "debug.py route not created"
    content = debug_route.read_text()
    assert "APIRouter" in content
    assert "/debug" in content


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_recorder_has_ring_buffer() -> None:
    """CC-11: recorder.py contains RequestRecorder with ring buffer logic."""
    project_dir = create_fixture_project(name="replay_t11")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    recorder_file = project_dir / "app" / "debug" / "recorder.py"
    assert recorder_file.exists(), "recorder.py not created"
    content = recorder_file.read_text()
    assert "RequestRecorder" in content
    assert "init_recorder" in content
    assert "get_recorder" in content
    assert "lpush" in content or "redis" in content.lower()
    assert "ltrim" in content or "max_entries" in content


def test_replayer_has_diff() -> None:
    """CC-12: replayer.py contains RequestReplayer with diff logic."""
    project_dir = create_fixture_project(name="replay_t12")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    replayer_file = project_dir / "app" / "debug" / "replayer.py"
    assert replayer_file.exists(), "replayer.py not created"
    content = replayer_file.read_text()
    assert "RequestReplayer" in content
    assert "replay" in content
    assert "diff" in content.lower() or "body_diff" in content


def test_middleware_captures_background() -> None:
    """CC-13: RecorderMiddleware uses ensure_future for background capture."""
    project_dir = create_fixture_project(name="replay_t13")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "request_recorder.py"
    assert mw_file.exists(), "request_recorder.py middleware not created"
    content = mw_file.read_text()
    assert "RecorderMiddleware" in content
    assert "ensure_future" in content or "background" in content.lower() or "asyncio" in content


def test_debug_routes_have_all_endpoints() -> None:
    """CC-14: debug routes define list, replay, and flush endpoints."""
    project_dir = create_fixture_project(name="replay_t14")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    debug_route = project_dir / "app" / "api" / "routes" / "debug.py"
    content = debug_route.read_text()
    assert "list_requests" in content or "/requests" in content
    assert "replay_request" in content or "/replay" in content
    assert "flush_records" in content or "/flush" in content


def test_recorder_has_ttl_and_max_entries() -> None:
    """CC-15: recorder.py respects TTL and max_entries config."""
    project_dir = create_fixture_project(name="replay_t15")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    recorder_file = project_dir / "app" / "debug" / "recorder.py"
    content = recorder_file.read_text()
    assert "ttl_s" in content or "TTL" in content
    assert "max_entries" in content


def test_recorder_has_sha256_id() -> None:
    """CC-16: recorder.py generates SHA-256 record ids."""
    project_dir = create_fixture_project(name="replay_t16")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    recorder_file = project_dir / "app" / "debug" / "recorder.py"
    content = recorder_file.read_text()
    assert "sha256" in content or "hashlib" in content


def test_debug_init_exports() -> None:
    """CC-17: app/debug/__init__.py re-exports key symbols."""
    project_dir = create_fixture_project(name="replay_t17")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "debug" / "__init__.py"
    assert init_file.exists(), "debug/__init__.py not created"
    content = init_file.read_text()
    assert "RequestRecorder" in content
    assert "RequestReplayer" in content


def test_debug_models_pydantic() -> None:
    """CC-18: debug/models.py contains Pydantic schemas for recorded requests."""
    project_dir = create_fixture_project(name="replay_t18")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    models_file = project_dir / "app" / "debug" / "models.py"
    assert models_file.exists(), "debug/models.py not created"
    content = models_file.read_text()
    assert "RecordedRequest" in content
    assert "ReplayResult" in content
    assert "BaseModel" in content


def test_redis_sdk_lazy_in_recorder() -> None:
    """CC-19: redis.asyncio is imported lazily (inside function body) in recorder.py."""
    project_dir = create_fixture_project(name="replay_t19")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    recorder_file = project_dir / "app" / "debug" / "recorder.py"
    tree = ast.parse(recorder_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = ""
            if isinstance(node, ast.Import):
                name = node.names[0].name if node.names else ""
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ""
            assert "redis" not in name.lower(), (
                f"redis imported at top level in recorder.py: {name}"
            )


def test_exclude_paths_in_middleware() -> None:
    """CC-20: RecorderMiddleware skips configured exclude_paths."""
    project_dir = create_fixture_project(name="replay_t20")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "request_recorder.py"
    content = mw_file.read_text()
    assert "exclude_paths" in content


def test_config_has_all_debug_fields() -> None:
    """CC-21: All four DEBUG_RECORDER_* fields are in config.py."""
    project_dir = create_fixture_project(name="replay_t21")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in [
        "DEBUG_RECORDER_ENABLED",
        "DEBUG_RECORDER_TTL_S",
        "DEBUG_RECORDER_MAX_ENTRIES",
        "DEBUG_RECORDER_EXCLUDE_PATHS",
    ]:
        assert field in content, f"{field} not found in config.py"


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="replay_t22")
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps guides developer to set DEBUG_RECORDER_ENABLED."""
    project_dir = create_fixture_project(name="replay_t23")
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "debug_recorder_enabled" in combined or "recorder" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="replay_t24")
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
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
        test_models_init_not_broken,
        test_routes_registered,
        test_recorder_has_ring_buffer,
        test_replayer_has_diff,
        test_middleware_captures_background,
        test_debug_routes_have_all_endpoints,
        test_recorder_has_ttl_and_max_entries,
        test_recorder_has_sha256_id,
        test_debug_init_exports,
        test_debug_models_pydantic,
        test_redis_sdk_lazy_in_recorder,
        test_exclude_paths_in_middleware,
        test_config_has_all_debug_fields,
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
    print(f"TOOL-101 add_api_replay_debugger: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
