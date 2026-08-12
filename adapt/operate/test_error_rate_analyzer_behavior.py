"""Behavior tests for TOOL-041 error_rate_analyzer.

Proves that:
1. Tool returns error for non-existent project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/operate/test_error_rate_analyzer_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.operate.error_rate_analyzer import error_rate_analyzer


def test_b01_error_on_nonexistent_project() -> None:
    """B-01: Tool returns error for non-existent project directory."""
    result = error_rate_analyzer(
        ToolInput(project_dir="/nonexistent/path/that/does/not/exist"),
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on valid project returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = error_rate_analyzer(
        ToolInput(project_dir=str(project), dry_run=True),
    )
    assert result.status == "success"  # dry_run on valid project returns success
    middleware_file = project / "app" / "api" / "middleware" / "error_rate.py"
    assert not middleware_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Tool cannot auto-scaffold on empty dir -> error."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = error_rate_analyzer(
        ToolInput(project_dir=str(project)),
    )
    assert result.status == "error"  # tool cannot auto-scaffold on empty dir
    assert "prerequisites" in result.error.lower() or "missing" in result.error.lower()
    assert result.execution_time_ms >= 0


def test_b04_idempotent_on_second_run(tmp_path) -> None:
    """B-04: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app").mkdir()
    (project / "app" / "core").mkdir(parents=True)
    (project / "app" / "core" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        "    SECRET_KEY: str = 'test'\n"
    )

    result1 = error_rate_analyzer(
        ToolInput(project_dir=str(project)),
    )
    assert result1.status == "success", f"First run failed: {result1.error}"

    result2 = error_rate_analyzer(
        ToolInput(project_dir=str(project)),
    )
    assert result2.status == "no_op"
    assert result2.execution_time_ms >= 0
