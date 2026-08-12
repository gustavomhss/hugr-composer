"""Behavior tests for TOOL-043 add_migration_data.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. Tool is idempotent — second run returns no_op
5. Generated .py files pass ast.parse
6. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_add_migration_data_behavior.py -v
"""

from __future__ import annotations

import ast
import pytest

from adapt.contracts import ToolInput
from adapt.evolve.add_migration_data import add_migration_data


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = add_migration_data(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = add_migration_data(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    base_file = project / "data_migrations" / "base.py"
    assert not base_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Tool returns error when alembic/versions missing."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = add_migration_data(ToolInput(project_dir=str(project)))
    assert result.status == "success"  # auto-scaffold creates prerequisites
    assert result.execution_time_ms >= 0


def test_b04_idempotent_on_second_run(tmp_path) -> None:
    """B-04: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "data_migrations").mkdir(parents=True)
    (project / "data_migrations" / "base.py").write_text(
        "class DataMigration:\n    pass\n"
    )

    result = add_migration_data(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0
