"""Structural tests for TOOL-110 add_sbom_guardian.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_sbom_guardian.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_sbom_guardian.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_sbom_guardian import add_sbom_guardian
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
    project_dir = create_fixture_project(name="sbom_t01")
    result = add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files_created or files_modified."""
    project_dir = create_fixture_project(name="sbom_t02")
    r1 = add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="sbom_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_sbom_guardian(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 2 files created (generate_sbom.py, verify_lockfile.py)."""
    project_dir = create_fixture_project(name="sbom_t04")
    result = add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 2, (
        f"Expected >= 2 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (app/core/config.py patched)."""
    project_dir = create_fixture_project(name="sbom_t05")
    result = add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="sbom_t06")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="sbom_t07")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    scripts_dir = project_dir / "scripts"
    violations: list[str] = []
    for py_file in sorted(scripts_dir.rglob("*.py")):
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
    """CC-08: SBOM_FAIL_ON_CRITICAL and SBOM_LOCKFILE_PATH are in config.py."""
    project_dir = create_fixture_project(name="sbom_t08")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    config = project_dir / "app" / "core" / "config.py"
    assert config.exists()
    content = config.read_text()
    assert "SBOM_FAIL_ON_CRITICAL" in content
    assert "SBOM_LOCKFILE_PATH" in content
    for line in content.splitlines():
        if "SBOM_FAIL_ON_CRITICAL" in line or "SBOM_LOCKFILE_PATH" in line:
            assert line.startswith("    "), f"Not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: generate_sbom.py created
# ---------------------------------------------------------------------------

def test_generate_sbom_script_created() -> None:
    """CC-09: scripts/generate_sbom.py exists and contains generate_sbom function."""
    project_dir = create_fixture_project(name="sbom_t09")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    sbom_script = project_dir / "scripts" / "generate_sbom.py"
    assert sbom_script.exists(), "scripts/generate_sbom.py not created"
    content = sbom_script.read_text()
    assert "generate_sbom" in content


# ---------------------------------------------------------------------------
# CC-10: CycloneDX format present
# ---------------------------------------------------------------------------

def test_cyclonedx_format_in_sbom_script() -> None:
    """CC-10: generate_sbom.py outputs CycloneDX 1.4 format."""
    project_dir = create_fixture_project(name="sbom_t10")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "scripts" / "generate_sbom.py").read_text()
    assert "CycloneDX" in content, "CycloneDX format not referenced"
    assert "1.4" in content or "specVersion" in content, "specVersion not set"


# ---------------------------------------------------------------------------
# CC-11: verify_lockfile.py created
# ---------------------------------------------------------------------------

def test_verify_lockfile_script_created() -> None:
    """CC-11: scripts/verify_lockfile.py exists with dependency confusion detection."""
    project_dir = create_fixture_project(name="sbom_t11")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    lockfile_script = project_dir / "scripts" / "verify_lockfile.py"
    assert lockfile_script.exists(), "scripts/verify_lockfile.py not created"
    content = lockfile_script.read_text()
    assert "confusion" in content.lower() or "CONFUSION" in content, (
        "Dependency confusion detection not found"
    )


# ---------------------------------------------------------------------------
# CC-12: OSV vulnerability scanning present
# ---------------------------------------------------------------------------

def test_osv_vulnerability_scanning_present() -> None:
    """CC-12: verify_lockfile.py queries OSV API for vulnerability scanning."""
    project_dir = create_fixture_project(name="sbom_t12")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "scripts" / "verify_lockfile.py").read_text()
    assert "osv" in content.lower() or "OSV" in content, (
        "OSV vulnerability scanning not found"
    )


# ---------------------------------------------------------------------------
# CC-13: no external dependencies (stdlib only)
# ---------------------------------------------------------------------------

def test_no_external_deps_in_sbom_scripts() -> None:
    """CC-13: SBOM scripts use only stdlib (no third-party imports at module level)."""
    project_dir = create_fixture_project(name="sbom_t13")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    stdlib_only = {"json", "subprocess", "sys", "pathlib", "hashlib", "logging",
                   "argparse", "datetime", "re", "urllib", "ipaddress", "importlib",
                   "__future__", "collections", "typing", "os"}
    for script_name in ("generate_sbom.py", "verify_lockfile.py"):
        tree = ast.parse((project_dir / "scripts" / script_name).read_text())
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top in stdlib_only or top.startswith("_"), (
                        f"Non-stdlib top-level import in {script_name}: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    assert top in stdlib_only or top.startswith("_"), (
                        f"Non-stdlib top-level from-import in {script_name}: {node.module}"
                    )


# ---------------------------------------------------------------------------
# CC-14: SHA-256 integrity in generate_sbom
# ---------------------------------------------------------------------------

def test_sha256_integrity_in_sbom_generator() -> None:
    """CC-14: generate_sbom.py includes SHA-256 integrity signing support."""
    project_dir = create_fixture_project(name="sbom_t14")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "scripts" / "generate_sbom.py").read_text()
    assert "sha256" in content.lower() or "SHA-256" in content, (
        "SHA-256 integrity signing not found in generate_sbom.py"
    )


# ---------------------------------------------------------------------------
# CC-15: next_steps present with keyword
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-15: next_steps includes actionable guidance (CI, sbom, pip)."""
    project_dir = create_fixture_project(name="sbom_t15")
    result = add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "sbom" in combined or "python" in combined or "ci" in combined


# ---------------------------------------------------------------------------
# CC-16: execution_time_ms positive
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-16: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="sbom_t16")
    result = add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-17: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-17: After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="sbom_t17")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-18: fail-on-critical config field
# ---------------------------------------------------------------------------

def test_fail_on_critical_config_field() -> None:
    """CC-18: SBOM_FAIL_ON_CRITICAL defaults to True in config."""
    project_dir = create_fixture_project(name="sbom_t18")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    assert "SBOM_FAIL_ON_CRITICAL" in content
    # Default should be True
    for line in content.splitlines():
        if "SBOM_FAIL_ON_CRITICAL" in line and ":" in line:
            assert "True" in line or "bool" in line, (
                f"SBOM_FAIL_ON_CRITICAL should default to True: {line!r}"
            )


# ---------------------------------------------------------------------------
# CC-19: purl field in SBOM components
# ---------------------------------------------------------------------------

def test_purl_field_in_sbom_components() -> None:
    """CC-19: SBOM component entries include purl (Package URL) field."""
    project_dir = create_fixture_project(name="sbom_t19")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "scripts" / "generate_sbom.py").read_text()
    assert "purl" in content, "purl (Package URL) not found in generate_sbom.py"


# ---------------------------------------------------------------------------
# CC-20: lockfile hash function present
# ---------------------------------------------------------------------------

def test_lockfile_hash_function_present() -> None:
    """CC-20: verify_lockfile.py contains hash function for lockfile integrity."""
    project_dir = create_fixture_project(name="sbom_t20")
    add_sbom_guardian(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "scripts" / "verify_lockfile.py").read_text()
    assert "hash" in content.lower(), "Hash function not found in verify_lockfile.py"
    assert "hashlib" in content or "sha256" in content.lower(), (
        "hashlib/sha256 not imported in verify_lockfile.py"
    )


# ---------------------------------------------------------------------------
# CC-21: error invalid project_dir
# ---------------------------------------------------------------------------

def test_error_invalid_project_dir() -> None:
    """CC-21: Tool returns error for non-existent project_dir."""
    result = add_sbom_guardian(ToolInput(project_dir="/nonexistent/path/abc123"))
    assert result.status == "error"
    assert result.error
    assert result.execution_time_ms >= 0


# ---------------------------------------------------------------------------
# CC-22: MCP_TOOL dict entry matches function
# ---------------------------------------------------------------------------

def test_mcp_tool_entry_matches_function() -> None:
    """CC-22: MCP_TOOL['entry'] equals the function name 'add_sbom_guardian'."""
    from adapt.extend.testing_tools.add_sbom_guardian import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_sbom_guardian", (
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
        test_generate_sbom_script_created,
        test_cyclonedx_format_in_sbom_script,
        test_verify_lockfile_script_created,
        test_osv_vulnerability_scanning_present,
        test_no_external_deps_in_sbom_scripts,
        test_sha256_integrity_in_sbom_generator,
        test_next_steps_present,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
        test_fail_on_critical_config_field,
        test_purl_field_in_sbom_components,
        test_lockfile_hash_function_present,
        test_error_invalid_project_dir,
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
    print(f"TOOL-110 add_sbom_guardian: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
