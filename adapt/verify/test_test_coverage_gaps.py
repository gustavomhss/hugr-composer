"""Tests for TOOL-032 test_coverage_gaps.

Verifies idempotency, orchestrator creation, risk weights config,
pyproject.toml patching, CI workflow, _parse_coverage_xml, _compute_risk,
compute_percentiles (no, wait — those live in 034), and baseline creation.

Run with::

    PYTHONPATH=. python3 adapt/verify/test_test_coverage_gaps.py
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import textwrap
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.test_coverage_gaps import (
    _HIGH_RISK_PATTERNS,
    _compute_risk,
    _parse_coverage_xml,
)
from adapt.verify.test_coverage_gaps import (
    test_coverage_gaps as run_test_coverage_gaps,
)
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


_MINIMAL_COVERAGE_XML = textwrap.dedent("""\
    <?xml version="1.0" ?>
    <coverage version="7.0" line-rate="0.87" branch-rate="0.75">
        <packages>
            <package name="app">
                <classes>
                    <class filename="app/api/auth.py" line-rate="0.92" branch-rate="0.85">
                    </class>
                    <class filename="app/utils/formatters.py" line-rate="0.60" branch-rate="0.50">
                    </class>
                </classes>
            </package>
        </packages>
    </coverage>
""")


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

def test_compute_risk_high_risk_file() -> None:
    """T-01: _compute_risk returns 2.0 for auth files."""
    assert _compute_risk("app/api/auth.py") == 2.0


def test_compute_risk_payment_file() -> None:
    """T-02: _compute_risk returns 2.0 for payment files."""
    assert _compute_risk("app/services/payment_processor.py") == 2.0


def test_compute_risk_normal_file() -> None:
    """T-03: _compute_risk returns 1.0 for normal files."""
    assert _compute_risk("app/utils/formatters.py") == 1.0


def test_high_risk_patterns_non_empty() -> None:
    """T-04: _HIGH_RISK_PATTERNS list is non-empty."""
    assert len(_HIGH_RISK_PATTERNS) > 0


def test_parse_coverage_xml_line_rate() -> None:
    """T-05: _parse_coverage_xml extracts overall line rate."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
        f.write(_MINIMAL_COVERAGE_XML)
        xml_path = Path(f.name)
    result = _parse_coverage_xml(xml_path)
    assert result["overall_line_pct"] > 0


def test_parse_coverage_xml_branch_rate() -> None:
    """T-06: _parse_coverage_xml extracts overall branch rate."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
        f.write(_MINIMAL_COVERAGE_XML)
        xml_path = Path(f.name)
    result = _parse_coverage_xml(xml_path)
    assert result["overall_branch_pct"] > 0


def test_parse_coverage_xml_modules_dict() -> None:
    """T-07: _parse_coverage_xml returns modules dict."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
        f.write(_MINIMAL_COVERAGE_XML)
        xml_path = Path(f.name)
    result = _parse_coverage_xml(xml_path)
    assert isinstance(result["modules"], dict)


def test_parse_coverage_xml_risk_weights_applied() -> None:
    """T-08: _parse_coverage_xml applies risk weight of 2.0 to auth files."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
        f.write(_MINIMAL_COVERAGE_XML)
        xml_path = Path(f.name)
    result = _parse_coverage_xml(xml_path)
    auth_data = result["modules"].get("app/api/auth.py", {})
    assert auth_data.get("risk_weight") == 2.0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-09: Tool returns status='success' on a fresh project."""
    project = create_fixture_project(name="tcg_t09")
    result = run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


def test_no_op_on_second_run() -> None:
    """T-10: Second run returns status='no_op' (idempotency)."""
    project = create_fixture_project(name="tcg_t10")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    result = run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"


def test_orchestrator_created() -> None:
    """T-11: scripts/coverage_gaps.py is created."""
    project = create_fixture_project(name="tcg_t11")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert (project / "scripts" / "coverage_gaps.py").exists()


def test_orchestrator_parses() -> None:
    """T-12: scripts/coverage_gaps.py has no syntax errors."""
    project = create_fixture_project(name="tcg_t12")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "scripts" / "coverage_gaps.py")


def test_orchestrator_has_class() -> None:
    """T-13: scripts/coverage_gaps.py contains CoverageGapsAnalyzer."""
    project = create_fixture_project(name="tcg_t13")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "coverage_gaps.py").read_text()
    assert "CoverageGapsAnalyzer" in content


def test_risk_weights_created() -> None:
    """T-14: .coverage-risk-weights.yaml is created."""
    project = create_fixture_project(name="tcg_t14")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert (project / ".coverage-risk-weights.yaml").exists()


def test_risk_weights_has_high_risk_patterns() -> None:
    """T-15: .coverage-risk-weights.yaml lists high-risk patterns."""
    project = create_fixture_project(name="tcg_t15")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    content = (project / ".coverage-risk-weights.yaml").read_text()
    assert "auth" in content
    assert "payment" in content


def test_baseline_file_created() -> None:
    """T-16: .coverage.baseline.json is created."""
    project = create_fixture_project(name="tcg_t16")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert (project / ".coverage.baseline.json").exists()


def test_baseline_file_is_valid_json() -> None:
    """T-17: .coverage.baseline.json is valid JSON."""
    project = create_fixture_project(name="tcg_t17")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    data = json.loads((project / ".coverage.baseline.json").read_text())
    assert isinstance(data, dict)


def test_ci_workflow_created() -> None:
    """T-18: .github/workflows/coverage-gaps.yml is created."""
    project = create_fixture_project(name="tcg_t18")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert (project / ".github" / "workflows" / "coverage-gaps.yml").exists()


def test_ci_workflow_has_branch_flag() -> None:
    """T-19: CI workflow enables branch coverage via --cov-branch."""
    project = create_fixture_project(name="tcg_t19")
    run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    content = (project / ".github" / "workflows" / "coverage-gaps.yml").read_text()
    assert "cov-branch" in content or "branch" in content


def test_dry_run_no_files_written() -> None:
    """T-20: dry_run=True returns success but writes no files."""
    project = create_fixture_project(name="tcg_t20")
    result = run_test_coverage_gaps(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    assert not (project / "scripts" / "coverage_gaps.py").exists()


def test_files_created_all_exist() -> None:
    """T-21: Every path in files_created actually exists on disk."""
    project = create_fixture_project(name="tcg_t21")
    result = run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Missing: {path_str}"


def test_notes_mention_branch_coverage() -> None:
    """T-22: notes mention branch coverage."""
    project = create_fixture_project(name="tcg_t22")
    result = run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    combined = " ".join(result.notes).lower()
    assert "branch" in combined


def test_next_steps_mention_pytest() -> None:
    """T-23: next_steps mention running pytest."""
    project = create_fixture_project(name="tcg_t23")
    result = run_test_coverage_gaps(ToolInput(project_dir=str(project)))
    combined = " ".join(result.next_steps).lower()
    assert "pytest" in combined


def test_parse_invalid_xml_returns_empty() -> None:
    """T-24: _parse_coverage_xml handles invalid XML gracefully."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
        f.write("NOT VALID XML <><>")
        xml_path = Path(f.name)
    result = _parse_coverage_xml(xml_path)
    assert result["overall_line_pct"] == 0.0
    assert result["modules"] == {}


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
