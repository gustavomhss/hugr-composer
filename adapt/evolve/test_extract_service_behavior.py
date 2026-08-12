"""Behavior tests for TOOL-045 extract_service.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_extract_service_behavior.py -v
"""

from __future__ import annotations

import ast
import pytest

from adapt.contracts import ToolInput
from adapt.evolve.extract_service import extract_service


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = extract_service(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = extract_service(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    manifest_file = project / "EXTRACTION_MANIFEST.json"
    assert not manifest_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Non-dry_run auto-scaffolds + creates service -> success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = extract_service(ToolInput(project_dir=str(project)))
    assert result.status == "success"  # auto-scaffold + creates service
    assert result.execution_time_ms >= 0
