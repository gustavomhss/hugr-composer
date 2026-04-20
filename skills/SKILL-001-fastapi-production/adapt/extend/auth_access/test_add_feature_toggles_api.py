"""Structural tests for the refactored TOOL-064 ``add_feature_toggles_api``.

Mirrors the three-step `add_graceful_shutdown` delivery contract.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_feature_toggles_api import MCP_TOOL, add_feature_toggles_api
from tests.common.fixture_factory import create_fixture_project


def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_success_status() -> None:
    p = create_fixture_project(name="ft_t01")
    r = add_feature_toggles_api(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    p = create_fixture_project(name="ft_t02")
    add_feature_toggles_api(ToolInput(project_dir=str(p)))
    r2 = add_feature_toggles_api(ToolInput(project_dir=str(p)))
    assert r2.status == "no_op"


def test_dry_run_writes_nothing() -> None:
    p = create_fixture_project(name="ft_t03")
    before = {f: f.read_text() for f in _all_py(p)}
    add_feature_toggles_api(ToolInput(project_dir=str(p), dry_run=True))
    after = {f: f.read_text() for f in _all_py(p)}
    assert before == after


def test_primitive_copied() -> None:
    p = create_fixture_project(name="ft_t04")
    add_feature_toggles_api(ToolInput(project_dir=str(p)))
    prim = p / "core" / "venous" / "flags" / "FeatureToggle" / "FeatureToggle.py"
    assert prim.exists()
    assert "class FeatureToggleRegistry" in prim.read_text()


def test_adapter_copied() -> None:
    p = create_fixture_project(name="ft_t05")
    add_feature_toggles_api(ToolInput(project_dir=str(p)))
    adapter = p / "core" / "venous" / "_adapters" / "fastapi" / "FeatureToggleAdapter.py"
    assert adapter.exists()
    body = adapter.read_text()
    assert "def install(" in body and "def is_active(" in body


def test_manifest_records_provenance() -> None:
    p = create_fixture_project(name="ft_t06")
    add_feature_toggles_api(ToolInput(project_dir=str(p)))
    m = json.loads((p / ".venous_manifest.json").read_text())
    assert "core.venous.flags.FeatureToggle" in {x["qualified_name"] for x in m["primitives"]}
    assert "core.venous._adapters.fastapi.FeatureToggleAdapter" in {x["qualified_name"] for x in m["adapters"]}


def test_glue_imports_adapter() -> None:
    p = create_fixture_project(name="ft_t07")
    add_feature_toggles_api(ToolInput(project_dir=str(p)))
    body = (p / "app" / "feature_toggles.py").read_text()
    assert "from core.venous._adapters.fastapi.FeatureToggleAdapter import" in body
    assert "install_feature_toggles" in body


def test_glue_under_20_loc_body() -> None:
    p = create_fixture_project(name="ft_t08")
    add_feature_toggles_api(ToolInput(project_dir=str(p)))
    glue = p / "app" / "feature_toggles.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines += (node.end_lineno or node.body[0].lineno) - node.body[0].lineno + 1
    assert body_lines <= 20


def test_mcp_tool_lists_imports() -> None:
    assert "core.venous.flags.FeatureToggle" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.FeatureToggleAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    p = create_fixture_project(name="ft_t10")
    r = add_feature_toggles_api(ToolInput(project_dir=str(p)))
    assert r.execution_time_ms > 0


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
