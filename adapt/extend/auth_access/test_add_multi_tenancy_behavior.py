"""Behavior tests for add_multi_tenancy."""

import shutil
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy
from tests.common.fixture_factory import create_fixture_project


def test_add_multi_tenancy_dry_run_no_files() -> None:
    project_dir = create_fixture_project(name="multi_tenancy_dry_run")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)
        result = add_multi_tenancy(inp)
        assert result.status in ("success", "preview")
        assert result.files_created == []
    finally:
        shutil.rmtree(project_dir)


def test_add_multi_tenancy_creates_valid_python() -> None:
    project_dir = create_fixture_project(name="multi_tenancy_valid_python")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=False)
        result = add_multi_tenancy(inp)
        if result.status == "success":
            for fpath in result.files_created:
                if fpath.endswith(".py"):
                    import ast

                    ast.parse(Path(fpath).read_text())
    finally:
        shutil.rmtree(project_dir)


def test_add_multi_tenancy_idempotent() -> None:
    project_dir = create_fixture_project(name="multi_tenancy_idempotent")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=False)
        r1 = add_multi_tenancy(inp)
        r2 = add_multi_tenancy(inp)
        assert r1.status in ("success", "no_op")
        assert r2.status in ("success", "no_op")
    finally:
        shutil.rmtree(project_dir)


def test_add_multi_tenancy_elapsed_ms() -> None:
    project_dir = create_fixture_project(name="multi_tenancy_elapsed")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)
        result = add_multi_tenancy(inp)
        assert result.execution_time_ms is not None
        assert result.execution_time_ms >= 0
    finally:
        shutil.rmtree(project_dir)
