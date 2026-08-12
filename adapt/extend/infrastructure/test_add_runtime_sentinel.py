"""Structural tests for TOOL-111 add_runtime_sentinel.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_runtime_sentinel.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_runtime_sentinel.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_runtime_sentinel import add_runtime_sentinel
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
    project_dir = create_fixture_project(name="sentinel_t01")
    result = add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files_created or files_modified."""
    project_dir = create_fixture_project(name="sentinel_t02")
    r1 = add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="sentinel_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_runtime_sentinel(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 2 files created (runtime_sentinel.py, sentinel_registry.py)."""
    project_dir = create_fixture_project(name="sentinel_t04")
    result = add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 2, (
        f"Expected >= 2 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (app/core/config.py patched)."""
    project_dir = create_fixture_project(name="sentinel_t05")
    result = add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All generated .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="sentinel_t06")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="sentinel_t07")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    sentinel_file = project_dir / "app" / "middleware" / "runtime_sentinel.py"
    registry_file = project_dir / "app" / "core" / "sentinel_registry.py"
    violations: list[str] = []
    for py_file in (sentinel_file, registry_file):
        if not py_file.exists():
            continue
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file.name}:{node.name} ({loc} LOC)")
    assert not violations, "Functions > 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: SENTINEL_ENABLED, SENTINEL_MODE, SENTINEL_ALLOWED_HOSTS in config.py."""
    project_dir = create_fixture_project(name="sentinel_t08")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    config = project_dir / "app" / "core" / "config.py"
    assert config.exists()
    content = config.read_text()
    for field in ("SENTINEL_ENABLED", "SENTINEL_MODE", "SENTINEL_ALLOWED_HOSTS"):
        assert field in content, f"{field} not patched into config.py"
        for line in content.splitlines():
            if field in line and ":" in line:
                assert line.startswith("    "), f"Not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: RuntimeSentinelMiddleware created
# ---------------------------------------------------------------------------

def test_runtime_sentinel_middleware_created() -> None:
    """CC-09: app/middleware/runtime_sentinel.py with RuntimeSentinelMiddleware exists."""
    project_dir = create_fixture_project(name="sentinel_t09")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    sentinel_file = project_dir / "app" / "middleware" / "runtime_sentinel.py"
    assert sentinel_file.exists(), "runtime_sentinel.py not created"
    content = sentinel_file.read_text()
    assert "RuntimeSentinelMiddleware" in content


# ---------------------------------------------------------------------------
# CC-10: InjectionDetector class present
# ---------------------------------------------------------------------------

def test_injection_detector_class_present() -> None:
    """CC-10: InjectionDetector class with check_sql, check_command, check_ssrf."""
    project_dir = create_fixture_project(name="sentinel_t10")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "runtime_sentinel.py").read_text()
    assert "InjectionDetector" in content
    assert "check_sql" in content
    assert "check_command" in content
    assert "check_ssrf" in content


# ---------------------------------------------------------------------------
# CC-11: SQL injection patterns (tautology/UNION/stacked/comment)
# ---------------------------------------------------------------------------

def test_sql_injection_patterns_comprehensive() -> None:
    """CC-11: SQL detection covers tautology, UNION, stacked queries, and comments."""
    project_dir = create_fixture_project(name="sentinel_t11")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "runtime_sentinel.py").read_text()
    assert "UNION" in content, "UNION injection pattern missing"
    assert "tautology" in content.lower() or "OR" in content, "Tautology pattern missing"
    assert "stacked" in content.lower() or "DROP" in content, "Stacked query pattern missing"
    assert "comment" in content.lower() or "--" in content, "Comment injection pattern missing"


# ---------------------------------------------------------------------------
# CC-12: SSRF internal network blocking
# ---------------------------------------------------------------------------

def test_ssrf_internal_network_blocking() -> None:
    """CC-12: SSRF detector blocks internal networks including 169.254 metadata."""
    project_dir = create_fixture_project(name="sentinel_t12")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "runtime_sentinel.py").read_text()
    assert "169.254" in content, "Cloud metadata IP not blocked"
    assert "127.0.0" in content or "127.0.0.0" in content, "Loopback not blocked"
    assert "10.0.0.0" in content or "ipaddress" in content, "Internal network 10.x not handled"


# ---------------------------------------------------------------------------
# CC-13: AttackPatternRegistry created
# ---------------------------------------------------------------------------

def test_attack_pattern_registry_created() -> None:
    """CC-13: app/core/sentinel_registry.py with AttackPatternRegistry exists."""
    project_dir = create_fixture_project(name="sentinel_t13")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "core" / "sentinel_registry.py"
    assert registry_file.exists(), "sentinel_registry.py not created"
    content = registry_file.read_text()
    assert "AttackPatternRegistry" in content


# ---------------------------------------------------------------------------
# CC-14: SecurityEvent model present
# ---------------------------------------------------------------------------

def test_security_event_model_present() -> None:
    """CC-14: SecurityEvent dataclass/model is defined in sentinel_registry.py."""
    project_dir = create_fixture_project(name="sentinel_t14")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "sentinel_registry.py").read_text()
    assert "SecurityEvent" in content
    assert "attack_type" in content
    assert "blocked" in content


# ---------------------------------------------------------------------------
# CC-15: learning mode behavior
# ---------------------------------------------------------------------------

def test_learning_mode_present() -> None:
    """CC-15: Learning mode referenced (logs without blocking for 24h)."""
    project_dir = create_fixture_project(name="sentinel_t15")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "runtime_sentinel.py").read_text()
    assert "learning" in content, "Learning mode not referenced"
    assert "enforcing" in content, "Enforcing mode not referenced"


# ---------------------------------------------------------------------------
# CC-16: execution_time_ms positive
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-16: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="sentinel_t16")
    result = add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-17: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-17: next_steps guides developer to register middleware and set env vars."""
    project_dir = create_fixture_project(name="sentinel_t17")
    result = add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "middleware" in combined or "sentinel" in combined or "env" in combined


# ---------------------------------------------------------------------------
# CC-18: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-18: After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="sentinel_t18")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-19: command injection metacharacters
# ---------------------------------------------------------------------------

def test_command_injection_metacharacters() -> None:
    """CC-19: Command injection detector covers shell metacharacters."""
    project_dir = create_fixture_project(name="sentinel_t19")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "runtime_sentinel.py").read_text()
    assert "metacharacter" in content.lower() or "CMD" in content or "command" in content.lower(), (
        "Command injection detection not referenced"
    )


# ---------------------------------------------------------------------------
# CC-20: error invalid project_dir
# ---------------------------------------------------------------------------

def test_error_invalid_project_dir() -> None:
    """CC-20: Tool returns error for non-existent project_dir."""
    result = add_runtime_sentinel(ToolInput(project_dir="/nonexistent/path/abc123"))
    assert result.status == "error"
    assert result.error
    assert result.execution_time_ms >= 0


# ---------------------------------------------------------------------------
# CC-21: SENTINEL_MODE defaults to learning
# ---------------------------------------------------------------------------

def test_sentinel_mode_defaults_to_learning() -> None:
    """CC-21: SENTINEL_MODE defaults to 'learning' in config."""
    project_dir = create_fixture_project(name="sentinel_t21")
    add_runtime_sentinel(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    for line in content.splitlines():
        if "SENTINEL_MODE" in line and ":" in line:
            assert "learning" in line, f"SENTINEL_MODE should default to 'learning': {line!r}"


# ---------------------------------------------------------------------------
# CC-22: MCP_TOOL dict entry matches function
# ---------------------------------------------------------------------------

def test_mcp_tool_entry_matches_function() -> None:
    """CC-22: MCP_TOOL['entry'] equals the function name 'add_runtime_sentinel'."""
    from adapt.extend.infrastructure.add_runtime_sentinel import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_runtime_sentinel", (
        f"MCP_TOOL entry mismatch: {MCP_TOOL['entry']!r}"
    )
    assert "name" in MCP_TOOL
    assert "description" in MCP_TOOL
    assert "tags" in MCP_TOOL


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
        test_runtime_sentinel_middleware_created,
        test_injection_detector_class_present,
        test_sql_injection_patterns_comprehensive,
        test_ssrf_internal_network_blocking,
        test_attack_pattern_registry_created,
        test_security_event_model_present,
        test_learning_mode_present,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_command_injection_metacharacters,
        test_error_invalid_project_dir,
        test_sentinel_mode_defaults_to_learning,
        test_mcp_tool_entry_matches_function,
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
    print(f"TOOL-111 add_runtime_sentinel: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
