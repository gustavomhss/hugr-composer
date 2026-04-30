"""Structural tests for the refactored TOOL-012 ``add_rbac``.

The refactor (CONTRACT §B1.0 + §B1.0.1) replaces the old inline RBAC
boilerplate with a three-step flow:

1. Copy the `RequestGuard` + `CurrentPrincipal` primitives into the
   generated project (via `generators/scaffold_venous.ensure_primitives`).
2. Copy the FastAPI adapter `RequestGuardAdapter` alongside them.
3. Write a ≤20-line `app/rbac.py` that imports the adapter and calls
   `require(RoleGuard(...))`.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_rbac import MCP_TOOL, add_rbac
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
    project_dir = create_fixture_project(name="rbac_t01")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    project_dir = create_fixture_project(name="rbac_t02")
    r1 = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"


def test_dry_run_writes_nothing() -> None:
    project_dir = create_fixture_project(name="rbac_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_rbac(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


def test_both_primitives_copied() -> None:
    project_dir = create_fixture_project(name="rbac_t04")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    rg = project_dir / "core" / "venous" / "auth" / "RequestGuard" / "RequestGuard.py"
    cp = project_dir / "core" / "venous" / "auth" / "CurrentPrincipal" / "CurrentPrincipal.py"
    assert rg.exists() and "class CompositeGuard" in rg.read_text()
    assert cp.exists() and "class CurrentPrincipal" in cp.read_text()


def test_adapter_copied_into_project() -> None:
    project_dir = create_fixture_project(name="rbac_t05")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    adapter = project_dir / "core" / "venous" / "_adapters" / "fastapi" / "RequestGuardAdapter.py"
    assert adapter.exists()
    body = adapter.read_text()
    assert "def require(" in body
    assert "Copied from HuGR Smith" in body


def test_venous_manifest_records_provenance() -> None:
    project_dir = create_fixture_project(name="rbac_t06")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    prim_names = {p["qualified_name"] for p in manifest["primitives"]}
    adapter_names = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.auth.RequestGuard" in prim_names
    assert "core.venous.auth.CurrentPrincipal" in prim_names
    assert "core.venous._adapters.fastapi.RequestGuardAdapter" in adapter_names


def test_glue_file_imports_adapter() -> None:
    project_dir = create_fixture_project(name="rbac_t07")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "rbac.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.RequestGuardAdapter import require" in body
    assert "from core.venous.auth.RequestGuard.RequestGuard import RoleGuard" in body
    assert "def require_roles" in body


def test_glue_file_under_20_loc_body() -> None:
    project_dir = create_fixture_project(name="rbac_t08")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "rbac.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, f"glue body is {body_lines} LoC; budget is 20"


def test_all_py_parse_after_two_runs() -> None:
    project_dir = create_fixture_project(name="rbac_t09")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    add_rbac(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_lists_imported_primitives() -> None:
    assert MCP_TOOL["entry"] == "add_rbac"
    assert "core.venous.auth.RequestGuard" in MCP_TOOL["imports_primitives"]
    assert "core.venous.auth.CurrentPrincipal" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.RequestGuardAdapter" in MCP_TOOL["imports_adapters"]


def test_mcp_tool_has_required_keys() -> None:
    for key in ("name", "description", "tags", "entry"):
        assert key in MCP_TOOL, f"MCP_TOOL missing key: {key}"


def test_execution_time_recorded() -> None:
    project_dir = create_fixture_project(name="rbac_t11")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run_writes_nothing,
        test_both_primitives_copied,
        test_adapter_copied_into_project,
        test_venous_manifest_records_provenance,
        test_glue_file_imports_adapter,
        test_glue_file_under_20_loc_body,
        test_all_py_parse_after_two_runs,
        test_mcp_tool_lists_imported_primitives,
        test_mcp_tool_has_required_keys,
        test_execution_time_recorded,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if not failed else 1)
