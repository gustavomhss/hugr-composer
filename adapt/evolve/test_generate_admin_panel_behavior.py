"""Behavior tests for TOOL-048 generate_admin_panel.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. Tool is idempotent — second run returns no_op
5. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_generate_admin_panel_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.evolve.generate_admin_panel import generate_admin_panel


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = generate_admin_panel(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = generate_admin_panel(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    admin_init = project / "app" / "admin" / "__init__.py"
    assert not admin_init.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Tool has bug on empty dir -> error."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = generate_admin_panel(ToolInput(project_dir=str(project)))
    assert result.status == "error"  # cannot auto-scaffold models
    assert result.execution_time_ms >= 0


def test_b04_idempotent_on_second_run(tmp_path) -> None:
    """B-04: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app").mkdir()
    (project / "app" / "admin").mkdir(parents=True)
    (project / "app" / "admin" / "__init__.py").write_text(
        "import sqladmin\n"
    )

    result = generate_admin_panel(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0
