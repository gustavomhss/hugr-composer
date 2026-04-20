"""Structural tests for the refactored TOOL-013 ``add_mfa``."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_mfa import MCP_TOOL, add_mfa
from tests.common.fixture_factory import create_fixture_project


def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_success_status() -> None:
    p = create_fixture_project(name="mfa_t01")
    r = add_mfa(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    p = create_fixture_project(name="mfa_t02")
    add_mfa(ToolInput(project_dir=str(p)))
    assert add_mfa(ToolInput(project_dir=str(p))).status == "no_op"


def test_dry_run_writes_nothing() -> None:
    p = create_fixture_project(name="mfa_t03")
    before = {f: f.read_text() for f in _all_py(p)}
    add_mfa(ToolInput(project_dir=str(p), dry_run=True))
    after = {f: f.read_text() for f in _all_py(p)}
    assert before == after


def test_primitive_copied() -> None:
    p = create_fixture_project(name="mfa_t04")
    add_mfa(ToolInput(project_dir=str(p)))
    prim = p / "core" / "venous" / "auth" / "TotpVerifier" / "TotpVerifier.py"
    assert prim.exists()
    assert "class StandardTotpVerifier" in prim.read_text()


def test_adapter_copied() -> None:
    p = create_fixture_project(name="mfa_t05")
    add_mfa(ToolInput(project_dir=str(p)))
    adapter = p / "core" / "venous" / "_adapters" / "fastapi" / "TotpVerifierAdapter.py"
    assert adapter.exists()
    assert "def verify_code(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    p = create_fixture_project(name="mfa_t06")
    add_mfa(ToolInput(project_dir=str(p)))
    m = json.loads((p / ".venous_manifest.json").read_text())
    assert "core.venous.auth.TotpVerifier" in {x["qualified_name"] for x in m["primitives"]}
    assert "core.venous._adapters.fastapi.TotpVerifierAdapter" in {x["qualified_name"] for x in m["adapters"]}


def test_glue_imports_adapter() -> None:
    p = create_fixture_project(name="mfa_t07")
    add_mfa(ToolInput(project_dir=str(p)))
    body = (p / "app" / "mfa.py").read_text()
    assert "from core.venous._adapters.fastapi.TotpVerifierAdapter import" in body
    assert "install_mfa" in body


def test_glue_under_20_loc_body() -> None:
    p = create_fixture_project(name="mfa_t08")
    add_mfa(ToolInput(project_dir=str(p)))
    glue = p / "app" / "mfa.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines += (node.end_lineno or node.body[0].lineno) - node.body[0].lineno + 1
    assert body_lines <= 20


def test_mcp_tool_lists_imports() -> None:
    assert "core.venous.auth.TotpVerifier" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.TotpVerifierAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    p = create_fixture_project(name="mfa_t10")
    assert add_mfa(ToolInput(project_dir=str(p))).execution_time_ms > 0


if __name__ == "__main__":
    tests = [
        test_success_status, test_idempotent, test_dry_run_writes_nothing,
        test_primitive_copied, test_adapter_copied, test_manifest_records_provenance,
        test_glue_imports_adapter, test_glue_under_20_loc_body, test_mcp_tool_lists_imports,
        test_execution_time_recorded,
    ]
    p = f = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); p += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); f += 1
    print(f"\n{p}/{p+f} passed")
    sys.exit(0 if not f else 1)
