"""Behavior tests for add_batch_endpoint."""

import shutil
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint
from tests.common.fixture_factory import create_fixture_project


def test_batch_endpoint_dry_run_no_files() -> None:
    project_dir = create_fixture_project(name="batch_dry_run")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)
        result = add_batch_endpoint(inp)
        assert result.status in ("success", "preview")
        assert result.files_created == []
    finally:
        shutil.rmtree(project_dir)


def test_batch_endpoint_creates_valid_python() -> None:
    project_dir = create_fixture_project(name="batch_valid_python")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=False)
        result = add_batch_endpoint(inp)
        if result.status == "success":
            for fpath in result.files_created:
                if fpath.endswith(".py"):
                    import ast

                    ast.parse(Path(fpath).read_text())
    finally:
        shutil.rmtree(project_dir)


def test_batch_endpoint_idempotent() -> None:
    project_dir = create_fixture_project(name="batch_idempotent")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=False)
        r1 = add_batch_endpoint(inp)
        r2 = add_batch_endpoint(inp)
        assert r1.status == "success", "first run must succeed"
        assert r2.status in ("success", "no_op")
    finally:
        shutil.rmtree(project_dir)


def test_batch_endpoint_elapsed_ms() -> None:
    project_dir = create_fixture_project(name="batch_elapsed")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)
        result = add_batch_endpoint(inp)
        assert result.execution_time_ms is not None
        assert result.execution_time_ms >= 0
    finally:
        shutil.rmtree(project_dir)
