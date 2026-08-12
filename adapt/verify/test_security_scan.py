"""Tests for TOOL-029 security_scan.

Verifies idempotency, file creation, orchestrator content, semgrep rules,
bandit config, exclusion schema, SARIF merge utility, and CI workflow.

Run with::

    PYTHONPATH=. python3 adapt/verify/test_security_scan.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.security_scan import security_scan
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
    project = create_fixture_project(name="sec_t01")
    result = security_scan(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


def test_no_op_on_second_run() -> None:
    """T-02: Second run returns status='no_op' (idempotency)."""
    project = create_fixture_project(name="sec_t02")
    security_scan(ToolInput(project_dir=str(project)))
    result = security_scan(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"


def test_orchestrator_created() -> None:
    """T-03: scripts/security_scan.py is created."""
    project = create_fixture_project(name="sec_t03")
    security_scan(ToolInput(project_dir=str(project)))
    assert (project / "scripts" / "security_scan.py").exists()


def test_orchestrator_has_class() -> None:
    """T-04: scripts/security_scan.py contains SecurityScanOrchestrator."""
    project = create_fixture_project(name="sec_t04")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "security_scan.py").read_text()
    assert "SecurityScanOrchestrator" in content


def test_orchestrator_parses() -> None:
    """T-05: scripts/security_scan.py has no syntax errors."""
    project = create_fixture_project(name="sec_t05")
    security_scan(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "scripts" / "security_scan.py")


def test_semgrep_rules_created() -> None:
    """T-06: .security/semgrep-rules.yaml is created."""
    project = create_fixture_project(name="sec_t06")
    security_scan(ToolInput(project_dir=str(project)))
    assert (project / ".security" / "semgrep-rules.yaml").exists()


def test_semgrep_rules_has_fastapi_rules() -> None:
    """T-07: semgrep-rules.yaml contains FastAPI-specific rules."""
    project = create_fixture_project(name="sec_t07")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / ".security" / "semgrep-rules.yaml").read_text()
    assert "fastapi" in content.lower()
    assert "CORSMiddleware" in content


def test_bandit_config_created() -> None:
    """T-08: .security/bandit.yaml is created."""
    project = create_fixture_project(name="sec_t08")
    security_scan(ToolInput(project_dir=str(project)))
    assert (project / ".security" / "bandit.yaml").exists()


def test_bandit_config_has_exclude() -> None:
    """T-09: bandit.yaml has exclude_dirs or skips."""
    project = create_fixture_project(name="sec_t09")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / ".security" / "bandit.yaml").read_text()
    assert "exclude_dirs" in content or "skips" in content


def test_exclusion_schema_created() -> None:
    """T-10: .security-exclude.yaml is created."""
    project = create_fixture_project(name="sec_t10")
    security_scan(ToolInput(project_dir=str(project)))
    assert (project / ".security-exclude.yaml").exists()


def test_exclusion_schema_has_expiry_field() -> None:
    """T-11: .security-exclude.yaml mentions expiry."""
    project = create_fixture_project(name="sec_t11")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / ".security-exclude.yaml").read_text()
    assert "expiry" in content


def test_sarif_merge_created() -> None:
    """T-12: .security/sarif_merge.py is created."""
    project = create_fixture_project(name="sec_t12")
    security_scan(ToolInput(project_dir=str(project)))
    assert (project / ".security" / "sarif_merge.py").exists()


def test_sarif_merge_parses() -> None:
    """T-13: sarif_merge.py has no syntax errors."""
    project = create_fixture_project(name="sec_t13")
    security_scan(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / ".security" / "sarif_merge.py")


def test_sarif_merge_has_merge_function() -> None:
    """T-14: sarif_merge.py defines merge_sarif function."""
    project = create_fixture_project(name="sec_t14")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / ".security" / "sarif_merge.py").read_text()
    assert "def merge_sarif" in content


def test_ci_workflow_created() -> None:
    """T-15: .github/workflows/security.yml is created."""
    project = create_fixture_project(name="sec_t15")
    security_scan(ToolInput(project_dir=str(project)))
    assert (project / ".github" / "workflows" / "security.yml").exists()


def test_ci_workflow_has_sarif_upload() -> None:
    """T-16: CI workflow references SARIF upload action."""
    project = create_fixture_project(name="sec_t16")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / ".github" / "workflows" / "security.yml").read_text()
    assert "sarif" in content.lower()


def test_orchestrator_has_three_scanners() -> None:
    """T-17: Orchestrator references bandit, semgrep, and pip-audit."""
    project = create_fixture_project(name="sec_t17")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "security_scan.py").read_text()
    assert "bandit" in content
    assert "semgrep" in content
    assert "pip-audit" in content or "pip_audit" in content


def test_orchestrator_has_severity_ordering() -> None:
    """T-18: Orchestrator defines severity order for threshold filtering."""
    project = create_fixture_project(name="sec_t18")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "security_scan.py").read_text()
    assert "SEVERITY_ORDER" in content or "HIGH" in content


def test_dry_run_no_files_written() -> None:
    """T-19: dry_run=True returns success but writes no files."""
    project = create_fixture_project(name="sec_t19")
    result = security_scan(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    assert not (project / "scripts" / "security_scan.py").exists()


def test_files_created_all_exist() -> None:
    """T-20: Every path in files_created actually exists on disk."""
    project = create_fixture_project(name="sec_t20")
    result = security_scan(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Missing: {path_str}"


def test_notes_non_empty() -> None:
    """T-21: notes list is non-empty."""
    project = create_fixture_project(name="sec_t21")
    result = security_scan(ToolInput(project_dir=str(project)))
    assert result.notes


def test_next_steps_non_empty() -> None:
    """T-22: next_steps contains at least one actionable item."""
    project = create_fixture_project(name="sec_t22")
    result = security_scan(ToolInput(project_dir=str(project)))
    assert result.next_steps


def test_orchestrator_has_parallel_execution() -> None:
    """T-23: Orchestrator uses ThreadPoolExecutor for parallel scanner runs."""
    project = create_fixture_project(name="sec_t23")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "security_scan.py").read_text()
    assert "ThreadPoolExecutor" in content


def test_semgrep_rules_has_sql_injection_rule() -> None:
    """T-24: semgrep-rules.yaml has SQL injection detection rule."""
    project = create_fixture_project(name="sec_t24")
    security_scan(ToolInput(project_dir=str(project)))
    content = (project / ".security" / "semgrep-rules.yaml").read_text()
    assert "sql" in content.lower() or "injection" in content.lower()


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
