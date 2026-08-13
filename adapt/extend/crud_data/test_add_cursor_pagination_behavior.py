"""Behavior tests for add_cursor_pagination."""

import pytest
import shutil
from pathlib import Path

from tests.common.fixture_factory import create_fixture_project

from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
from adapt.contracts import ToolInput


def test_add_cursor_pagination_dry_run_no_files() -> None:
    project_dir = create_fixture_project(name="cursor_dry_run")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)
        result = add_cursor_pagination(inp)
        assert result.status in ("success", "preview")
        assert result.files_created == []
    finally:
        shutil.rmtree(project_dir)


def test_add_cursor_pagination_creates_valid_python() -> None:
    project_dir = create_fixture_project(name="cursor_valid_python")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=False)
        result = add_cursor_pagination(inp)
        if result.status == "success":
            for fpath in result.files_created:
                if fpath.endswith(".py"):
                    import ast
                    ast.parse(Path(fpath).read_text())
    finally:
        shutil.rmtree(project_dir)


def test_add_cursor_pagination_idempotent() -> None:
    project_dir = create_fixture_project(name="cursor_idempotent")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=False)
        r1 = add_cursor_pagination(inp)
        r2 = add_cursor_pagination(inp)
        assert r2.status in ("success", "no_op")
    finally:
        shutil.rmtree(project_dir)


def test_add_cursor_pagination_elapsed_ms() -> None:
    project_dir = create_fixture_project(name="cursor_elapsed")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)
        result = add_cursor_pagination(inp)
        assert result.execution_time_ms is not None
        assert result.execution_time_ms >= 0
    finally:
        shutil.rmtree(project_dir)
