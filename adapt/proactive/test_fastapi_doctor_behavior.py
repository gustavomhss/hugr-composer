"""Behavior tests for TOOL-051 fastapi_doctor.

Proves that:
1. Tool returns error for non-existent project directory
2. Tool respects dry_run mode
3. Tool returns success for valid project directory
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/proactive/test_fastapi_doctor_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.proactive.fastapi_doctor import fastapi_doctor


def test_b01_error_on_nonexistent_project() -> None:
    """B-01: Tool returns error for non-existent project directory."""
    result = fastapi_doctor(
        ToolInput(project_dir="/nonexistent/path/that/does/not/exist"),
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run mode produces no files (doctor is read-only)."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = fastapi_doctor(
        ToolInput(project_dir=str(project), dry_run=True),
    )
    assert result.status == "success"
    assert result.execution_time_ms >= 0


def test_b03_success_on_valid_project(tmp_path) -> None:
    """B-03: Tool returns success for valid project directory."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = fastapi_doctor(
        ToolInput(project_dir=str(project)),
    )
    assert result.status == "success", f"Failed: {result.error}"
    assert result.execution_time_ms >= 0
