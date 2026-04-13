"""Tests for TOOL-034 performance_baseline.

Verifies idempotency, file creation, hardware fingerprint, p-percentile
computation, regression detection, baseline lifecycle, and CI workflow.

Run with::

    PYTHONPATH=. python3 adapt/verify/test_performance_baseline.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.performance_baseline import (
    performance_baseline,
    get_hardware_fingerprint,
    compute_percentiles,
    check_regression,
    _build_empty_baseline,
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


# ---------------------------------------------------------------------------
# Unit tests for pure helpers
# ---------------------------------------------------------------------------

def test_hardware_fingerprint_has_required_keys() -> None:
    """T-01: get_hardware_fingerprint returns dict with cpu, cores, arch, python."""
    fp = get_hardware_fingerprint()
    for key in ("cpu", "cores", "arch", "python"):
        assert key in fp, f"Missing key: {key}"


def test_hardware_fingerprint_python_version() -> None:
    """T-02: hardware fingerprint python field matches actual Python version."""
    import platform
    fp = get_hardware_fingerprint()
    assert fp["python"] == platform.python_version()


def test_compute_percentiles_basic() -> None:
    """T-03: compute_percentiles returns p50, p95, p99 keys."""
    latencies = [float(i) for i in range(1, 101)]
    result = compute_percentiles(latencies)
    assert "p50" in result and "p95" in result and "p99" in result


def test_compute_percentiles_sorted_order() -> None:
    """T-04: p50 <= p95 <= p99."""
    latencies = [float(i) for i in range(100, 0, -1)]
    result = compute_percentiles(latencies)
    assert result["p50"] <= result["p95"] <= result["p99"]


def test_compute_percentiles_empty() -> None:
    """T-05: compute_percentiles handles empty list gracefully."""
    result = compute_percentiles([])
    assert result == {"p50": 0.0, "p95": 0.0, "p99": 0.0}


def test_compute_percentiles_single_value() -> None:
    """T-06: compute_percentiles handles single-element list."""
    result = compute_percentiles([42.0])
    assert result["p50"] == 42.0
    assert result["p99"] == 42.0


def test_check_regression_no_regression() -> None:
    """T-07: check_regression returns empty list when within tolerance."""
    current = {"p50": 10.0, "p95": 20.0, "p99": 30.0}
    baseline = {"p50": 10.0, "p95": 20.0, "p99": 30.0}
    assert check_regression(current, baseline, tolerance_pct=10.0) == []


def test_check_regression_detects_p99_regression() -> None:
    """T-08: check_regression detects p99 regression beyond tolerance."""
    current = {"p50": 10.0, "p95": 20.0, "p99": 50.0}
    baseline = {"p50": 10.0, "p95": 20.0, "p99": 30.0}
    regressions = check_regression(current, baseline, tolerance_pct=10.0)
    assert "p99" in regressions


def test_check_regression_within_tolerance_no_fail() -> None:
    """T-09: check_regression allows changes within tolerance band."""
    current = {"p50": 10.0, "p95": 20.0, "p99": 33.0}  # +10% of 30
    baseline = {"p50": 10.0, "p95": 20.0, "p99": 30.0}
    regressions = check_regression(current, baseline, tolerance_pct=10.0)
    assert "p99" not in regressions


def test_check_regression_zero_baseline() -> None:
    """T-10: check_regression skips metrics with zero baseline."""
    current = {"p50": 0.0, "p95": 0.0, "p99": 100.0}
    baseline = {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    assert check_regression(current, baseline) == []


def test_build_empty_baseline_structure() -> None:
    """T-11: _build_empty_baseline returns dict with hardware and endpoints keys."""
    baseline = _build_empty_baseline()
    assert "hardware" in baseline
    assert "endpoints" in baseline
    assert "tolerance_pct" in baseline


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-12: Tool returns status='success' on a fresh project."""
    project = create_fixture_project(name="pb_t12")
    result = performance_baseline(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


def test_no_op_on_second_run() -> None:
    """T-13: Second run returns status='no_op' (idempotency)."""
    project = create_fixture_project(name="pb_t13")
    performance_baseline(ToolInput(project_dir=str(project)))
    result = performance_baseline(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"


def test_orchestrator_created() -> None:
    """T-14: scripts/perf_baseline.py is created."""
    project = create_fixture_project(name="pb_t14")
    performance_baseline(ToolInput(project_dir=str(project)))
    assert (project / "scripts" / "perf_baseline.py").exists()


def test_orchestrator_parses() -> None:
    """T-15: scripts/perf_baseline.py has no syntax errors."""
    project = create_fixture_project(name="pb_t15")
    performance_baseline(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "scripts" / "perf_baseline.py")


def test_orchestrator_has_class() -> None:
    """T-16: scripts/perf_baseline.py contains PerformanceBaselineRunner."""
    project = create_fixture_project(name="pb_t16")
    performance_baseline(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "perf_baseline.py").read_text()
    assert "PerformanceBaselineRunner" in content


def test_baseline_json_created() -> None:
    """T-17: .perf.baseline.json is created."""
    project = create_fixture_project(name="pb_t17")
    performance_baseline(ToolInput(project_dir=str(project)))
    assert (project / ".perf.baseline.json").exists()


def test_baseline_json_has_hardware() -> None:
    """T-18: .perf.baseline.json contains hardware fingerprint."""
    project = create_fixture_project(name="pb_t18")
    performance_baseline(ToolInput(project_dir=str(project)))
    data = json.loads((project / ".perf.baseline.json").read_text())
    assert "hardware" in data


def test_exclude_yaml_created() -> None:
    """T-19: .perf-exclude.yaml is created."""
    project = create_fixture_project(name="pb_t19")
    performance_baseline(ToolInput(project_dir=str(project)))
    assert (project / ".perf-exclude.yaml").exists()


def test_exclude_yaml_has_health() -> None:
    """T-20: .perf-exclude.yaml excludes /health endpoint."""
    project = create_fixture_project(name="pb_t20")
    performance_baseline(ToolInput(project_dir=str(project)))
    content = (project / ".perf-exclude.yaml").read_text()
    assert "/health" in content


def test_conftest_created() -> None:
    """T-21: tests/conftest_perf.py is created."""
    project = create_fixture_project(name="pb_t21")
    performance_baseline(ToolInput(project_dir=str(project)))
    assert (project / "tests" / "conftest_perf.py").exists()


def test_conftest_parses() -> None:
    """T-22: tests/conftest_perf.py has no syntax errors."""
    project = create_fixture_project(name="pb_t22")
    performance_baseline(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "tests" / "conftest_perf.py")


def test_ci_workflow_created() -> None:
    """T-23: .github/workflows/perf-baseline.yml is created."""
    project = create_fixture_project(name="pb_t23")
    performance_baseline(ToolInput(project_dir=str(project)))
    assert (project / ".github" / "workflows" / "perf-baseline.yml").exists()


def test_files_created_all_exist() -> None:
    """T-24: Every path in files_created actually exists on disk."""
    project = create_fixture_project(name="pb_t24")
    result = performance_baseline(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Missing: {path_str}"


def test_notes_mention_warmup() -> None:
    """T-25: notes mention warmup requests."""
    project = create_fixture_project(name="pb_t25")
    result = performance_baseline(ToolInput(project_dir=str(project)))
    combined = " ".join(result.notes).lower()
    assert "warmup" in combined


def test_orchestrator_mentions_percentiles() -> None:
    """T-26: Orchestrator script references compute_percentiles (which provides p50/p95/p99)."""
    project = create_fixture_project(name="pb_t26")
    performance_baseline(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "perf_baseline.py").read_text()
    assert "compute_percentiles" in content


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
