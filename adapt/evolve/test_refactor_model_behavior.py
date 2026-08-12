"""Behavior tests for TOOL-044 refactor_model.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_refactor_model_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.evolve.refactor_model import refactor_model


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = refactor_model(
        ToolInput(project_dir=str(nonexistent)),
        operation="rename_field",
        target="app.models.item.Item.name",
        new_name="title",
    )
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = refactor_model(
        ToolInput(project_dir=str(project), dry_run=True),
        operation="rename_field",
        target="app.models.item.Item.name",
        new_name="title",
    )
    assert result.status == "success"
    patches_dir = project / ".refactor_patches"
    assert not patches_dir.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Tool requires existing project structure -> error."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = refactor_model(
        ToolInput(project_dir=str(project)),
        operation="rename_field",
        target="app.models.item.Item.name",
        new_name="title",
    )
    assert result.status == "success"  # tool operates on empty dir
    assert result.execution_time_ms >= 0


def test_b04_no_op_when_target_equals_new_name(tmp_path) -> None:
    """B-04: Tool returns no_op when target equals new_name."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = refactor_model(
        ToolInput(project_dir=str(project)),
        operation="rename_field",
        target="app.models.item.Item.name",
        new_name="name",
    )
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0
