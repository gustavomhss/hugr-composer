"""Tests for TOOL-030 dependency_audit.

Verifies idempotency, file creation, orchestrator content, audit config,
.audit-ignore schema, license checker, and CI workflow.

Run with::

    PYTHONPATH=. python3 adapt/verify/test_dependency_audit.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.dependency_audit import dependency_audit
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ok(path: Path) -> bool:
    try:
        ast.parse(path.read_text())
        return True
    except SyntaxError:
        return False


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project = create_fixture_project(name="dep_t01")
    result = dependency_audit(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


def test_no_op_on_second_run() -> None:
    """T-02: Second run returns status='no_op' (idempotency)."""
    project = create_fixture_project(name="dep_t02")
    dependency_audit(ToolInput(project_dir=str(project)))
    result = dependency_audit(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"


def test_orchestrator_created() -> None:
    """T-03: scripts/run_audit.py is created."""
    project = create_fixture_project(name="dep_t03")
    dependency_audit(ToolInput(project_dir=str(project)))
    assert (project / "scripts" / "run_audit.py").exists()


def test_orchestrator_has_class() -> None:
    """T-04: run_audit.py contains DependencyAuditOrchestrator."""
    project = create_fixture_project(name="dep_t04")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "run_audit.py").read_text()
    assert "DependencyAuditOrchestrator" in content


def test_orchestrator_parses() -> None:
    """T-05: run_audit.py has no syntax errors."""
    project = create_fixture_project(name="dep_t05")
    dependency_audit(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "scripts" / "run_audit.py")


def test_audit_config_created() -> None:
    """T-06: .audit.yaml is created."""
    project = create_fixture_project(name="dep_t06")
    dependency_audit(ToolInput(project_dir=str(project)))
    assert (project / ".audit.yaml").exists()


def test_audit_config_has_allowed_licenses() -> None:
    """T-07: .audit.yaml contains an allowed_licenses list."""
    project = create_fixture_project(name="dep_t07")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / ".audit.yaml").read_text()
    assert "allowed_licenses" in content
    assert "MIT" in content


def test_audit_ignore_created() -> None:
    """T-08: .audit-ignore is created."""
    project = create_fixture_project(name="dep_t08")
    dependency_audit(ToolInput(project_dir=str(project)))
    assert (project / ".audit-ignore").exists()


def test_audit_ignore_has_expiry_comment() -> None:
    """T-09: .audit-ignore explains expiry field requirement."""
    project = create_fixture_project(name="dep_t09")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / ".audit-ignore").read_text()
    assert "expiry" in content.lower()


def test_license_checker_created() -> None:
    """T-10: scripts/check_licenses.py is created."""
    project = create_fixture_project(name="dep_t10")
    dependency_audit(ToolInput(project_dir=str(project)))
    assert (project / "scripts" / "check_licenses.py").exists()


def test_license_checker_parses() -> None:
    """T-11: check_licenses.py has no syntax errors."""
    project = create_fixture_project(name="dep_t11")
    dependency_audit(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "scripts" / "check_licenses.py")


def test_license_checker_has_function() -> None:
    """T-12: check_licenses.py defines check_licenses() function."""
    project = create_fixture_project(name="dep_t12")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "check_licenses.py").read_text()
    assert "def check_licenses" in content


def test_ci_workflow_created() -> None:
    """T-13: .github/workflows/dependency-audit.yml is created."""
    project = create_fixture_project(name="dep_t13")
    dependency_audit(ToolInput(project_dir=str(project)))
    assert (project / ".github" / "workflows" / "dependency-audit.yml").exists()


def test_ci_workflow_has_pip_audit() -> None:
    """T-14: CI workflow installs pip-audit."""
    project = create_fixture_project(name="dep_t14")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / ".github" / "workflows" / "dependency-audit.yml").read_text()
    assert "pip-audit" in content


def test_orchestrator_has_three_checkers() -> None:
    """T-15: Orchestrator has pip_audit, deptry, and license checks."""
    project = create_fixture_project(name="dep_t15")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "run_audit.py").read_text()
    assert "pip_audit" in content or "pip-audit" in content
    assert "deptry" in content
    assert "license" in content.lower()


def test_orchestrator_has_parallel_execution() -> None:
    """T-16: Orchestrator uses ThreadPoolExecutor."""
    project = create_fixture_project(name="dep_t16")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "run_audit.py").read_text()
    assert "ThreadPoolExecutor" in content


def test_dry_run_no_files_written() -> None:
    """T-17: dry_run=True returns success but writes no files."""
    project = create_fixture_project(name="dep_t17")
    result = dependency_audit(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    assert not (project / "scripts" / "run_audit.py").exists()


def test_files_created_all_exist() -> None:
    """T-18: Every path in files_created actually exists on disk."""
    project = create_fixture_project(name="dep_t18")
    result = dependency_audit(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Missing: {path_str}"


def test_notes_mention_three_checks() -> None:
    """T-19: notes mention pip-audit, deptry, and license checks."""
    project = create_fixture_project(name="dep_t19")
    result = dependency_audit(ToolInput(project_dir=str(project)))
    combined = " ".join(result.notes).lower()
    assert "pip-audit" in combined or "cve" in combined
    assert "deptry" in combined or "unused" in combined


def test_audit_config_has_fail_on_cve_true() -> None:
    """T-20: .audit.yaml sets fail_on_cve: true."""
    project = create_fixture_project(name="dep_t20")
    dependency_audit(ToolInput(project_dir=str(project)))
    content = (project / ".audit.yaml").read_text()
    assert "fail_on_cve: true" in content


def test_execution_time_recorded() -> None:
    """T-21: execution_time_ms is a non-negative integer."""
    project = create_fixture_project(name="dep_t21")
    result = dependency_audit(ToolInput(project_dir=str(project)))
    assert isinstance(result.execution_time_ms, int)
    assert result.execution_time_ms >= 0


def test_next_steps_mention_pip_install() -> None:
    """T-22: next_steps mention installing the required tools."""
    project = create_fixture_project(name="dep_t22")
    result = dependency_audit(ToolInput(project_dir=str(project)))
    combined = " ".join(result.next_steps).lower()
    assert "pip install" in combined


# ---------------------------------------------------------------------------
# Self-runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
