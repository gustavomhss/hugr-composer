"""Behavior tests for add_circuit_breaker."""

import shutil
import tempfile
from pathlib import Path

from tests.common.fixture_factory import create_fixture_project


def test_add_circuit_breaker_dry_run_no_files():
    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker

    project_dir = create_fixture_project(name="circuit_breaker_dry_run")
    try:
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)
        result = add_circuit_breaker(inp)
        assert result.status in ("success", "preview")
        assert result.files_created == []
    finally:
        shutil.rmtree(project_dir)


def test_add_circuit_breaker_creates_valid_python():
    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker

    project_dir = tempfile.mkdtemp()
    try:
        inp = ToolInput(project_dir=project_dir, dry_run=False)
        result = add_circuit_breaker(inp)
        if result.status == "success":
            for fpath in result.files_created:
                if fpath.endswith(".py"):
                    import ast

                    ast.parse(Path(fpath).read_text())
    finally:
        shutil.rmtree(project_dir)


def test_add_circuit_breaker_idempotent():
    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker

    project_dir = tempfile.mkdtemp()
    try:
        inp = ToolInput(project_dir=project_dir, dry_run=False)
        r1 = add_circuit_breaker(inp)
        r2 = add_circuit_breaker(inp)
        assert r1.status == "success", "first run must succeed"
        assert r2.status in ("success", "no_op")
    finally:
        shutil.rmtree(project_dir)


def test_add_circuit_breaker_elapsed_ms():
    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker

    inp = ToolInput(project_dir=tempfile.mkdtemp(), dry_run=True)
    result = add_circuit_breaker(inp)
    assert result.execution_time_ms is not None
    assert result.execution_time_ms >= 0
