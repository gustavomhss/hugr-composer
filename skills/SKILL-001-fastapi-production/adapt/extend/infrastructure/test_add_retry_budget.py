"""Structural tests for the refactored TOOL-098 ``add_retry_budget``.

Refactor (CONTRACT §B1.0 + §B1.0.1):

1. Copy primitive ``core.venous.resiliency.RetryPolicy``.
2. Copy adapter ``core.venous._adapters.fastapi.RetryPolicyAdapter``.
3. Emit a ≤ 20-line ``app/retry.py`` calling the adapter's install().
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_retry_budget import MCP_TOOL, add_retry_budget
from tests.common.fixture_factory import create_fixture_project


def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py(root):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:  # pragma: no cover
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def test_success_status() -> None:
    d = create_fixture_project(name="rb_t01")
    r = add_retry_budget(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    d = create_fixture_project(name="rb_t02")
    assert add_retry_budget(ToolInput(project_dir=str(d))).status == "success"
    r2 = add_retry_budget(ToolInput(project_dir=str(d)))
    assert r2.status == "no_op"


def test_dry_run_writes_nothing() -> None:
    d = create_fixture_project(name="rb_t03")
    before = {f: f.read_text() for f in _all_py(d)}
    r = add_retry_budget(ToolInput(project_dir=str(d), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py(d)}
    assert before == after


def test_primitive_copied() -> None:
    d = create_fixture_project(name="rb_t04")
    add_retry_budget(ToolInput(project_dir=str(d)))
    p = d / "core" / "venous" / "resiliency" / "RetryPolicy" / "RetryPolicy.py"
    assert p.exists()
    assert "class ExponentialBackoffRetryPolicy" in p.read_text()


def test_adapter_copied() -> None:
    d = create_fixture_project(name="rb_t05")
    add_retry_budget(ToolInput(project_dir=str(d)))
    a = d / "core" / "venous" / "_adapters" / "fastapi" / "RetryPolicyAdapter.py"
    assert a.exists()
    assert "def install(" in a.read_text()


def test_manifest_records_provenance() -> None:
    d = create_fixture_project(name="rb_t06")
    add_retry_budget(ToolInput(project_dir=str(d)))
    manifest = json.loads((d / ".venous_manifest.json").read_text())
    assert "core.venous.resiliency.RetryPolicy" in {p["qualified_name"] for p in manifest["primitives"]}
    assert "core.venous._adapters.fastapi.RetryPolicyAdapter" in {a["qualified_name"] for a in manifest["adapters"]}


def test_glue_imports_adapter() -> None:
    d = create_fixture_project(name="rb_t07")
    add_retry_budget(ToolInput(project_dir=str(d)))
    body = (d / "app" / "retry.py").read_text()
    assert "from core.venous._adapters.fastapi.RetryPolicyAdapter" in body
    assert "def install_retry_policy" in body


def test_glue_body_under_20_loc() -> None:
    d = create_fixture_project(name="rb_t08")
    add_retry_budget(ToolInput(project_dir=str(d)))
    tree = ast.parse((d / "app" / "retry.py").read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, body_lines


def test_config_patched() -> None:
    d = create_fixture_project(name="rb_t09")
    add_retry_budget(ToolInput(project_dir=str(d)))
    body = (d / "app" / "core" / "config.py").read_text()
    assert "RETRY_MAX_ATTEMPTS" in body
    assert "RETRY_BUDGET_RATIO" in body


def test_parses_after_two_runs() -> None:
    d = create_fixture_project(name="rb_t10")
    add_retry_budget(ToolInput(project_dir=str(d)))
    add_retry_budget(ToolInput(project_dir=str(d)))
    _assert_parse(d)


def test_mcp_tool_metadata() -> None:
    assert MCP_TOOL["entry"] == "add_retry_budget"
    assert "core.venous.resiliency.RetryPolicy" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.RetryPolicyAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    d = create_fixture_project(name="rb_t11")
    r = add_retry_budget(ToolInput(project_dir=str(d)))
    assert r.execution_time_ms > 0


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
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
