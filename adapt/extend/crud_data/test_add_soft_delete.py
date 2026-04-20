"""Structural tests for the refactored TOOL-001 ``add_soft_delete``.

Mirrors the three-step `add_graceful_shutdown` delivery contract.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_soft_delete import MCP_TOOL, add_soft_delete
from tests.common.fixture_factory import create_fixture_project


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:  # pragma: no cover
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def test_success_status() -> None:
    p = create_fixture_project(name="sd_t01")
    r = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    p = create_fixture_project(name="sd_t02")
    add_soft_delete(ToolInput(project_dir=str(p)))
    r2 = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r2.status == "no_op"


def test_dry_run_writes_nothing() -> None:
    p = create_fixture_project(name="sd_t03")
    before = {f: f.read_text() for f in _all_py_files(p)}
    r = add_soft_delete(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py_files(p)}
    assert before == after


def test_primitive_copied() -> None:
    p = create_fixture_project(name="sd_t04")
    add_soft_delete(ToolInput(project_dir=str(p)))
    uow = p / "core" / "venous" / "data" / "UnitOfWork" / "UnitOfWork.py"
    assert uow.exists()
    assert "class InMemoryUnitOfWork" in uow.read_text()


def test_adapter_copied() -> None:
    p = create_fixture_project(name="sd_t05")
    add_soft_delete(ToolInput(project_dir=str(p)))
    adapter = p / "core" / "venous" / "_adapters" / "fastapi" / "UnitOfWorkAdapter.py"
    assert adapter.exists()
    assert "def make_dependency(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    p = create_fixture_project(name="sd_t06")
    add_soft_delete(ToolInput(project_dir=str(p)))
    m = json.loads((p / ".venous_manifest.json").read_text())
    assert "core.venous.data.UnitOfWork" in {x["qualified_name"] for x in m["primitives"]}
    assert "core.venous._adapters.fastapi.UnitOfWorkAdapter" in {x["qualified_name"] for x in m["adapters"]}


def test_glue_imports_adapter() -> None:
    p = create_fixture_project(name="sd_t07")
    add_soft_delete(ToolInput(project_dir=str(p)))
    body = (p / "app" / "soft_delete.py").read_text()
    assert "from core.venous._adapters.fastapi.UnitOfWorkAdapter import make_dependency" in body


def test_glue_under_20_loc_body() -> None:
    p = create_fixture_project(name="sd_t08")
    add_soft_delete(ToolInput(project_dir=str(p)))
    glue = p / "app" / "soft_delete.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines += (node.end_lineno or node.body[0].lineno) - node.body[0].lineno + 1
    assert body_lines <= 20


def test_mcp_tool_lists_imports() -> None:
    assert "core.venous.data.UnitOfWork" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.UnitOfWorkAdapter" in MCP_TOOL["imports_adapters"]


def test_all_py_parse_after_two_runs() -> None:
    p = create_fixture_project(name="sd_t10")
    add_soft_delete(ToolInput(project_dir=str(p)))
    add_soft_delete(ToolInput(project_dir=str(p)))
    _assert_parse(p)


def test_execution_time_recorded() -> None:
    p = create_fixture_project(name="sd_t11")
    r = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r.execution_time_ms > 0


if __name__ == "__main__":
    tests = [
        test_success_status, test_idempotent, test_dry_run_writes_nothing,
        test_primitive_copied, test_adapter_copied, test_manifest_records_provenance,
        test_glue_imports_adapter, test_glue_under_20_loc_body, test_mcp_tool_lists_imports,
        test_all_py_parse_after_two_runs, test_execution_time_recorded,
    ]
    p = f = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); p += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); f += 1
    print(f"\n{p}/{p+f} passed")
    sys.exit(0 if not f else 1)
