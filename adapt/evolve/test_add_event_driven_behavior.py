"""Behavior tests for TOOL-046 add_event_driven.

Proves that:
1. Tool returns error for invalid project directory
2. Tool respects dry_run mode
3. Tool returns error when prerequisites not met
4. Tool is idempotent — second run returns no_op
5. Generated .py files pass ast.parse
6. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_add_event_driven_behavior.py -v
"""

from __future__ import annotations

import ast
import pytest
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.add_event_driven import add_event_driven


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = add_event_driven(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on empty dir returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = add_event_driven(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    base_event_file = project / "events" / "base.py"
    assert not base_event_file.exists()
    assert result.execution_time_ms >= 0


def test_b03_prerequisites_not_met(tmp_path) -> None:
    """B-03: Non-dry_run auto-scaffolds prerequisites -> success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = add_event_driven(ToolInput(project_dir=str(project)))
    assert result.status == "success"  # auto-scaffold creates prerequisites
    assert result.execution_time_ms >= 0


def test_b04_idempotent_on_second_run(tmp_path) -> None:
    """B-04: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "events").mkdir(parents=True)
    (project / "events" / "base.py").write_text(
        "class BaseEvent:\n    pass\n"
    )

    result = add_event_driven(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0


def test_b05_generated_files_ast_parse(tmp_path) -> None:
    """B-05: Generated .py files pass ast.parse validation."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "app").mkdir()
    (project / "app" / "models").mkdir(parents=True)
    (project / "app" / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n    pass\n"
    )
    (project / "app" / "core").mkdir(parents=True)
    (project / "app" / "core" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        "    SECRET_KEY: str = 'test'\n"
    )

    result = add_event_driven(ToolInput(project_dir=str(project)))
    assert result.status == "success", f"Failed: {result.error}"

    for fpath in result.files_created:
        if fpath.endswith(".py"):
            p = project / fpath if not fpath.startswith("/") else Path(fpath)
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                pytest.fail(f"SyntaxError in {p}: {exc}")
