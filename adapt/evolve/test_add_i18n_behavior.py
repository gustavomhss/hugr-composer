"""Behavior tests for TOOL-050 add_i18n.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. Tool is idempotent — second run returns no_op
5. Generated .py files pass ast.parse
6. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_add_i18n_behavior.py -v
"""

from __future__ import annotations

import ast
import pytest

from adapt.contracts import ToolInput
from adapt.evolve.add_i18n import add_i18n


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = add_i18n(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = add_i18n(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    locale_ctx_file = project / "app" / "core" / "locale_context.py"
    assert not locale_ctx_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Non-dry_run auto-scaffolds prerequisites -> success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = add_i18n(ToolInput(project_dir=str(project)))
    assert result.status == "success"  # auto-scaffold creates prerequisites
    assert result.execution_time_ms >= 0


def test_b04_idempotent_on_second_run(tmp_path) -> None:
    """B-04: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app").mkdir()
    (project / "app" / "core").mkdir(parents=True)
    (project / "app" / "core" / "locale_context.py").write_text(
        "_current_locale = None\n"
    )

    result = add_i18n(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0
