"""Behavior tests for TOOL-037 dead_code_finder.

Proves that:
1. Tool returns error for non-existent project directory
2. Tool respects dry_run mode
3. Tool generates report file
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/operate/test_dead_code_finder_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.operate.dead_code_finder import dead_code_finder


def test_b01_error_on_nonexistent_project() -> None:
    """B-01: Tool returns error for non-existent project directory."""
    result = dead_code_finder(
        ToolInput(project_dir="/nonexistent/path/that/does/not/exist"),
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app.py").write_text("x = 1\n")

    result = dead_code_finder(
        ToolInput(project_dir=str(project), dry_run=True),
    )
    assert result.status == "success"
    report_file = project / "dead_code_report.md"
    assert not report_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_generates_report(tmp_path) -> None:
    """B-03: Tool generates dead code report."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "unused_module.py").write_text(
        "def unused_function():\n    pass\n"
    )

    result = dead_code_finder(
        ToolInput(project_dir=str(project)),
        confidence_threshold=50,
    )
    assert result.status == "success", f"Failed: {result.error}"
    report_file = project / "dead_code_report.md"
    assert report_file.exists()
    assert result.execution_time_ms >= 0
