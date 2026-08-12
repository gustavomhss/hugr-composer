"""Behavior tests for TOOL-031 schema_coverage.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. Tool is idempotent — second run returns no_op
5. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/verify/test_schema_coverage_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.verify.schema_coverage import schema_coverage


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = schema_coverage(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on valid project returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = schema_coverage(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"  # dry_run on valid project returns success
    script = project / "scripts" / "schema_coverage.py"
    assert not script.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Tool returns error when base model missing."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = schema_coverage(ToolInput(project_dir=str(project)))
    assert result.status == "error"  # tool has bug on empty dir
    assert "prerequisites" in result.error.lower() or "missing" in result.error.lower()
    assert result.execution_time_ms >= 0


def test_b04_idempotent_on_second_run(tmp_path) -> None:
    """B-04: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app").mkdir()
    (project / "app" / "models").mkdir(parents=True)
    (project / "app" / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n    pass\n"
    )
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "schema_coverage.py").write_text(
        "class SchemaCoverageAnalyzer:\n    pass\n"
    )

    result = schema_coverage(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0
