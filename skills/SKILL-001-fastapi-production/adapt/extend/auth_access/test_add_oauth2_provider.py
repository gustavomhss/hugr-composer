"""Structural tests for the refactored TOOL-011 ``add_oauth2_provider``."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_oauth2_provider import MCP_TOOL, add_oauth2_provider
from tests.common.fixture_factory import create_fixture_project


def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_success_status() -> None:
    p = create_fixture_project(name="o2_t01")
    r = add_oauth2_provider(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    p = create_fixture_project(name="o2_t02")
    add_oauth2_provider(ToolInput(project_dir=str(p)))
    assert add_oauth2_provider(ToolInput(project_dir=str(p))).status == "no_op"


def test_dry_run_writes_nothing() -> None:
    p = create_fixture_project(name="o2_t03")
    before = {f: f.read_text() for f in _all_py(p)}
    add_oauth2_provider(ToolInput(project_dir=str(p), dry_run=True))
    after = {f: f.read_text() for f in _all_py(p)}
    assert before == after


def test_both_primitives_copied() -> None:
    p = create_fixture_project(name="o2_t04")
    add_oauth2_provider(ToolInput(project_dir=str(p)))
    ti = p / "core" / "venous" / "auth" / "TokenIntrospector" / "TokenIntrospector.py"
    ss = p / "core" / "venous" / "auth" / "SessionStore" / "SessionStore.py"
    assert ti.exists() and "class CachingTokenIntrospector" in ti.read_text()
    assert ss.exists() and "class InMemorySessionStore" in ss.read_text()


def test_adapter_copied() -> None:
    p = create_fixture_project(name="o2_t05")
    add_oauth2_provider(ToolInput(project_dir=str(p)))
    adapter = p / "core" / "venous" / "_adapters" / "fastapi" / "OAuth2Adapter.py"
    assert adapter.exists()
    body = adapter.read_text()
    assert "def current_claims(" in body and "def install(" in body


def test_manifest_records_provenance() -> None:
    p = create_fixture_project(name="o2_t06")
    add_oauth2_provider(ToolInput(project_dir=str(p)))
    m = json.loads((p / ".venous_manifest.json").read_text())
    prims = {x["qualified_name"] for x in m["primitives"]}
    adapters = {x["qualified_name"] for x in m["adapters"]}
    assert "core.venous.auth.TokenIntrospector" in prims
    assert "core.venous.auth.SessionStore" in prims
    assert "core.venous._adapters.fastapi.OAuth2Adapter" in adapters


def test_glue_imports_adapter() -> None:
    p = create_fixture_project(name="o2_t07")
    add_oauth2_provider(ToolInput(project_dir=str(p)))
    body = (p / "app" / "oauth2.py").read_text()
    assert "from core.venous._adapters.fastapi.OAuth2Adapter import" in body
    assert "install_oauth2" in body


def test_glue_under_20_loc_body() -> None:
    p = create_fixture_project(name="o2_t08")
    add_oauth2_provider(ToolInput(project_dir=str(p)))
    glue = p / "app" / "oauth2.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines += (node.end_lineno or node.body[0].lineno) - node.body[0].lineno + 1
    assert body_lines <= 20


def test_mcp_tool_lists_imports() -> None:
    assert "core.venous.auth.TokenIntrospector" in MCP_TOOL["imports_primitives"]
    assert "core.venous.auth.SessionStore" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.OAuth2Adapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    p = create_fixture_project(name="o2_t10")
    assert add_oauth2_provider(ToolInput(project_dir=str(p))).execution_time_ms > 0


if __name__ == "__main__":
    tests = [
        test_success_status, test_idempotent, test_dry_run_writes_nothing,
        test_both_primitives_copied, test_adapter_copied, test_manifest_records_provenance,
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
