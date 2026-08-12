"""Behavior tests for TOOL-035 blast_radius.

Proves that:
1. Tool returns error for non-existent project directory
2. Tool respects dry_run mode
3. Tool requires target or diff_ref
4. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/operate/test_blast_radius_behavior.py -v
"""

from __future__ import annotations

import pytest

from adapt.contracts import ToolInput
from adapt.operate.blast_radius import blast_radius


def test_b01_error_on_nonexistent_project() -> None:
    """B-01: Tool returns error for non-existent project directory."""
    result = blast_radius(
        ToolInput(project_dir="/nonexistent/path/that/does/not/exist"),
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on valid project returns success."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app").mkdir()
    (project / "app" / "models").mkdir()
    (project / "app" / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n    pass\n"
    )

    result = blast_radius(
        ToolInput(project_dir=str(project), dry_run=True),
        target="app/models/base.py::Base",
    )
    assert result.status == "success"  # dry_run on valid project returns success
    report_file = project / "blast_radius_report.md"
    assert not report_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_requires_target_or_diff_ref(tmp_path) -> None:
    """B-03: Tool returns error when neither target nor diff_ref is provided."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app").mkdir()
    (project / "app" / "models").mkdir()
    (project / "app" / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n    pass\n"
    )

    result = blast_radius(
        ToolInput(project_dir=str(project)),
        target="",
    )
    assert result.status == "error"
    assert "target" in result.error.lower() or "diff_ref" in result.error.lower()
    assert result.execution_time_ms >= 0
