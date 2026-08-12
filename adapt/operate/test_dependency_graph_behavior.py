"""Behavior tests for TOOL-039 dependency_graph.

Proves that:
1. Tool returns error for non-existent project directory
2. Tool respects dry_run mode
3. Tool generates output file
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/operate/test_dependency_graph_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.operate.dependency_graph import dependency_graph


def test_b01_error_on_nonexistent_project() -> None:
    """B-01: Tool returns error for non-existent project directory."""
    result = dependency_graph(
        ToolInput(project_dir="/nonexistent/path/that/does/not/exist"),
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "module_a.py").write_text("x = 1\n")
    (project / "module_b.py").write_text("import module_a\n")

    result = dependency_graph(
        ToolInput(project_dir=str(project), dry_run=True),
    )
    assert result.status == "success"
    output_file = project / "dependency_graph.dot"
    assert not output_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_generates_output(tmp_path) -> None:
    """B-03: Tool generates dependency graph output."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "module_a.py").write_text("x = 1\n")
    (project / "module_b.py").write_text("import module_a\n")

    result = dependency_graph(
        ToolInput(project_dir=str(project)),
        output_format="json",
    )
    assert result.status == "success", f"Failed: {result.error}"
    output_file = project / "dependency_graph.json"
    assert output_file.exists()
    assert result.execution_time_ms >= 0
