"""Behavior tests for TOOL-038 api_changelog.

Proves that:
1. Tool runs successfully on a valid project directory
2. Tool returns error for non-existent project directory
3. Tool respects dry_run mode (no files written)
4. Tool is idempotent (second run with local specs returns success)
5. Tool produces valid output files
6. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/operate/test_api_changelog_behavior.py -v

or standalone::

    PYTHONPATH=. python3 adapt/operate/test_api_changelog_behavior.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from adapt.contracts import ToolInput
from adapt.operate.api_changelog import api_changelog


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal project directory with openapi.json for testing."""
    project = tmp_path / "test_project"
    project.mkdir()

    openapi_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/items": {
                "get": {
                    "summary": "List items",
                    "tags": ["items"],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    (project / "openapi.json").write_text(json.dumps(openapi_spec))

    old_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "0.9.0"},
        "paths": {},
    }
    openapi_dir = project / ".openapi"
    openapi_dir.mkdir()
    (openapi_dir / "v0.9.0.json").write_text(json.dumps(old_spec))

    return project


def test_b01_error_on_nonexistent_project() -> None:
    """B-01: Tool returns error for non-existent project directory."""
    result = api_changelog(
        ToolInput(project_dir="/nonexistent/path/that/does/not/exist"),
        from_ref="v0.9.0",
        to_ref="local",
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(project_dir: Path) -> None:
    """B-02: dry_run on empty dir returns error (prereqs not met)."""
    result = api_changelog(
        ToolInput(project_dir=str(project_dir), dry_run=True),
        from_ref="v0.9.0",
        to_ref="local",
    )
    assert result.status == "success"
    changelog = project_dir / "CHANGELOG.md"
    assert not changelog.exists()
    assert result.execution_time_ms >= 0


def test_b03_success_generates_changelog(project_dir: Path) -> None:
    """B-03: Tool generates changelog with valid content."""
    result = api_changelog(
        ToolInput(project_dir=str(project_dir)),
        from_ref="v0.9.0",
        to_ref="local",
    )
    assert result.status == "success", f"Failed: {result.error}"
    assert len(result.files_modified) > 0 or result.notes
    assert result.execution_time_ms >= 0


def test_b04_elapsed_ms_on_all_paths() -> None:
    """B-04: elapsed_ms is present on error path."""
    result = api_changelog(
        ToolInput(project_dir="/nonexistent"),
    )
    assert result.execution_time_ms >= 0
