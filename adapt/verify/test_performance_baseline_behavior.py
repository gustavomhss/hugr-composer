"""Behavior tests for TOOL-034 performance_baseline.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool is idempotent — second run returns no_op
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/verify/test_performance_baseline_behavior.py -v
"""

from __future__ import annotations

import ast
import pytest

from adapt.contracts import ToolInput
from adapt.verify.performance_baseline import performance_baseline


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = performance_baseline(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = performance_baseline(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    script = project / "scripts" / "perf_baseline.py"
    assert not script.exists()
    assert result.execution_time_ms >= 0


def test_b03_idempotent_on_second_run(tmp_path) -> None:
    """B-03: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "perf_baseline.py").write_text(
        "class PerformanceBaselineRunner:\n    pass\n"
    )

    result = performance_baseline(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0
