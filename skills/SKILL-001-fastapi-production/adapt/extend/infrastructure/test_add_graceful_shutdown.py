"""Structural tests for TOOL-100 add_graceful_shutdown.

Generates real fixture projects, runs the tool, and verifies all completeness
criteria from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_graceful_shutdown.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_graceful_shutdown.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_graceful_shutdown import add_graceful_shutdown
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
    project_dir = create_fixture_project(name="gs_t01")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on second run."""
    project_dir = create_fixture_project(name="gs_t02")
    r1 = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run writes nothing
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="gs_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 3 files created and all exist on disk."""
    project_dir = create_fixture_project(name="gs_t04")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified and all exist on disk."""
    project_dir = create_fixture_project(name="gs_t05")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 file modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All .py files in project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="gs_t06")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="gs_t07")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    violations: list[str] = []
    for search_dir in [
        project_dir / "app" / "lifecycle",
        project_dir / "app" / "middleware",
    ]:
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.rglob("*.py")):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    loc = (node.end_lineno or node.lineno) - node.lineno + 1
                    if loc > 50:
                        violations.append(f"{py_file.name}:{node.name} ({loc} LOC)")
    assert not violations, "Functions > 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: SHUTDOWN_* fields appear in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="gs_t08")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "SHUTDOWN_DRAIN_SECONDS" in content, "SHUTDOWN_DRAIN_SECONDS missing from config"
    assert "SHUTDOWN_TIMEOUT_SECONDS" in content, "SHUTDOWN_TIMEOUT_SECONDS missing from config"
    for line in content.splitlines():
        if "SHUTDOWN_" in line and ":" in line and "#" not in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-11: GracefulShutdown class defined
# ---------------------------------------------------------------------------

def test_graceful_shutdown_class_defined() -> None:
    """CC-11: GracefulShutdown class is defined in app/lifecycle/shutdown.py."""
    project_dir = create_fixture_project(name="gs_t11")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    shutdown_file = project_dir / "app" / "lifecycle" / "shutdown.py"
    assert shutdown_file.exists(), "shutdown.py not created"
    content = shutdown_file.read_text()
    assert "class GracefulShutdown" in content, "GracefulShutdown class must be defined"


# ---------------------------------------------------------------------------
# CC-12: signal handling present
# ---------------------------------------------------------------------------

def test_signal_handling_present() -> None:
    """CC-12: SIGTERM and SIGINT handling is present in shutdown.py."""
    project_dir = create_fixture_project(name="gs_t12")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    shutdown_file = project_dir / "app" / "lifecycle" / "shutdown.py"
    content = shutdown_file.read_text()
    assert "SIGTERM" in content, "SIGTERM must be handled"
    assert "SIGINT" in content, "SIGINT must be handled"
    assert "signal" in content, "signal module must be used"


# ---------------------------------------------------------------------------
# CC-13: drain phase present
# ---------------------------------------------------------------------------

def test_drain_phase_present() -> None:
    """CC-13: Drain phase (is_draining, drain_seconds) is in shutdown.py."""
    project_dir = create_fixture_project(name="gs_t13")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    shutdown_file = project_dir / "app" / "lifecycle" / "shutdown.py"
    content = shutdown_file.read_text()
    assert "drain" in content.lower(), "drain phase must be present"
    assert "is_draining" in content, "is_draining() method must be defined"


# ---------------------------------------------------------------------------
# CC-14: health gate defined
# ---------------------------------------------------------------------------

def test_shutdown_health_gate_defined() -> None:
    """CC-14: ShutdownHealthGate is defined in app/lifecycle/health_gate.py."""
    project_dir = create_fixture_project(name="gs_t14")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    health_gate_file = project_dir / "app" / "lifecycle" / "health_gate.py"
    assert health_gate_file.exists(), "health_gate.py not created"
    content = health_gate_file.read_text()
    assert "ShutdownHealthGate" in content, "ShutdownHealthGate must be defined"


# ---------------------------------------------------------------------------
# CC-15: middleware defined
# ---------------------------------------------------------------------------

def test_shutdown_middleware_defined() -> None:
    """CC-15: ShutdownMiddleware is defined in app/middleware/shutdown.py."""
    project_dir = create_fixture_project(name="gs_t15")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    shutdown_mw = project_dir / "app" / "middleware" / "shutdown.py"
    assert shutdown_mw.exists(), "app/middleware/shutdown.py not created"
    content = shutdown_mw.read_text()
    assert "ShutdownMiddleware" in content, "ShutdownMiddleware must be defined"


# ---------------------------------------------------------------------------
# CC-16: 503 + Retry-After in middleware
# ---------------------------------------------------------------------------

def test_middleware_returns_503_with_retry_after() -> None:
    """CC-16: ShutdownMiddleware returns 503 with Retry-After header during drain."""
    project_dir = create_fixture_project(name="gs_t16")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    shutdown_mw = project_dir / "app" / "middleware" / "shutdown.py"
    content = shutdown_mw.read_text()
    assert "503" in content, "503 status code must be in ShutdownMiddleware"
    assert "Retry-After" in content, "Retry-After header must be present"


# ---------------------------------------------------------------------------
# CC-17: in-flight tracking
# ---------------------------------------------------------------------------

def test_in_flight_tracking_present() -> None:
    """CC-17: In-flight request tracking methods are present in GracefulShutdown."""
    project_dir = create_fixture_project(name="gs_t17")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    shutdown_file = project_dir / "app" / "lifecycle" / "shutdown.py"
    content = shutdown_file.read_text()
    assert "in_flight" in content, "in-flight tracking must be present"
    assert "increment_in_flight" in content or "in_flight" in content


# ---------------------------------------------------------------------------
# CC-18: max 30s timeout referenced
# ---------------------------------------------------------------------------

def test_timeout_seconds_present() -> None:
    """CC-18: SHUTDOWN_TIMEOUT_SECONDS or 30 is referenced in shutdown.py."""
    project_dir = create_fixture_project(name="gs_t18")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    shutdown_file = project_dir / "app" / "lifecycle" / "shutdown.py"
    content = shutdown_file.read_text()
    assert "timeout" in content.lower(), "timeout must be referenced in shutdown.py"
    assert "30" in content or "SHUTDOWN_TIMEOUT" in content


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms positive
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="gs_t19")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps must be non-empty and mention SHUTDOWN_DRAIN_SECONDS."""
    project_dir = create_fixture_project(name="gs_t20")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps)
    assert "SHUTDOWN" in combined or "drain" in combined.lower()


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="gs_t21")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Domain-specific: MCP_TOOL validation
# ---------------------------------------------------------------------------

def test_mcp_tool_entry_matches_function() -> None:
    """MCP_TOOL['entry'] must equal 'add_graceful_shutdown'."""
    from adapt.extend.infrastructure.add_graceful_shutdown import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_graceful_shutdown"


def test_mcp_tool_has_required_keys() -> None:
    """MCP_TOOL dict must have name, description, tags, entry keys."""
    from adapt.extend.infrastructure.add_graceful_shutdown import MCP_TOOL
    for key in ("name", "description", "tags", "entry"):
        assert key in MCP_TOOL, f"MCP_TOOL missing key: {key}"


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
        test_graceful_shutdown_class_defined,
        test_signal_handling_present,
        test_drain_phase_present,
        test_shutdown_health_gate_defined,
        test_shutdown_middleware_defined,
        test_middleware_returns_503_with_retry_after,
        test_in_flight_tracking_present,
        test_timeout_seconds_present,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_mcp_tool_entry_matches_function,
        test_mcp_tool_has_required_keys,
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
    print(f"TOOL-100 add_graceful_shutdown: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
