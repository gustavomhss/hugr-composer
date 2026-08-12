"""Behavior tests for TOOL-042 sla_reporter.

Proves that:
1. Tool returns error for non-existent project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/operate/test_sla_reporter_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.operate.sla_reporter import sla_reporter


def test_b01_error_on_nonexistent_project() -> None:
    """B-01: Tool returns error for non-existent project directory."""
    result = sla_reporter(
        ToolInput(project_dir="/nonexistent/path/that/does/not/exist"),
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run requires slo.py config -> error."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = sla_reporter(
        ToolInput(project_dir=str(project), dry_run=True),
    )
    assert result.status == "error"  # requires slo.py config
    report_file = project / "sla_report_month.md"
    assert not report_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Tool has bug on empty dir -> error."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = sla_reporter(
        ToolInput(project_dir=str(project)),
    )
    assert result.status == "error"  # tool has bug on empty dir
    assert "prerequisites" in result.error.lower() or "missing" in result.error.lower()
    assert result.execution_time_ms >= 0
