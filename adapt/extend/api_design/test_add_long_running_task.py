"""Structural tests for the refactored TOOL-020 ``add_long_running_task``.

Refactor (CONTRACT §B1.0 + §B1.0.1):

1. Copy primitives ``core.venous.jobs.WorkflowRun`` + ``core.venous.jobs.DurableTimer``.
2. Copy adapter ``core.venous._adapters.fastapi.WorkflowAdapter``.
3. Emit a ≤ 20-line ``app/tasks.py`` calling the adapter's install(), plus
   the ``app/api/routes/tasks.py`` POST/GET/DELETE surface.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_long_running_task import MCP_TOOL, add_long_running_task
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
    d = create_fixture_project(name="lrt_t01")
    r = add_long_running_task(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    d = create_fixture_project(name="lrt_t02")
    assert add_long_running_task(ToolInput(project_dir=str(d))).status == "success"
    r2 = add_long_running_task(ToolInput(project_dir=str(d)))
    assert r2.status == "no_op"


def test_dry_run_writes_nothing() -> None:
    d = create_fixture_project(name="lrt_t03")
    before = {f: f.read_text() for f in _all_py(d)}
    r = add_long_running_task(ToolInput(project_dir=str(d), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py(d)}
    assert before == after


def test_both_primitives_copied() -> None:
    d = create_fixture_project(name="lrt_t04")
    add_long_running_task(ToolInput(project_dir=str(d)))
    wf = d / "core" / "venous" / "jobs" / "WorkflowRun" / "WorkflowRun.py"
    dt = d / "core" / "venous" / "jobs" / "DurableTimer" / "DurableTimer.py"
    assert wf.exists()
    assert dt.exists()
    assert "class InMemoryWorkflowClient" in wf.read_text()
    assert "class InMemoryTimerService" in dt.read_text()


def test_adapter_copied() -> None:
    d = create_fixture_project(name="lrt_t05")
    add_long_running_task(ToolInput(project_dir=str(d)))
    a = d / "core" / "venous" / "_adapters" / "fastapi" / "WorkflowAdapter.py"
    assert a.exists()
    assert "def install(" in a.read_text()


def test_manifest_records_both_primitives_and_adapter() -> None:
    d = create_fixture_project(name="lrt_t06")
    add_long_running_task(ToolInput(project_dir=str(d)))
    manifest = json.loads((d / ".venous_manifest.json").read_text())
    prims = {p["qualified_name"] for p in manifest["primitives"]}
    adapters = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.jobs.WorkflowRun" in prims
    assert "core.venous.jobs.DurableTimer" in prims
    assert "core.venous._adapters.fastapi.WorkflowAdapter" in adapters


def test_glue_imports_adapter() -> None:
    d = create_fixture_project(name="lrt_t07")
    add_long_running_task(ToolInput(project_dir=str(d)))
    body = (d / "app" / "tasks.py").read_text()
    assert "from core.venous._adapters.fastapi.WorkflowAdapter import" in body
    assert "def install_long_running_tasks" in body


def test_glue_body_under_20_loc() -> None:
    d = create_fixture_project(name="lrt_t08")
    add_long_running_task(ToolInput(project_dir=str(d)))
    tree = ast.parse((d / "app" / "tasks.py").read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, body_lines


def test_task_routes_created() -> None:
    d = create_fixture_project(name="lrt_t09")
    add_long_running_task(ToolInput(project_dir=str(d)))
    routes = d / "app" / "api" / "routes" / "tasks.py"
    assert routes.exists()
    body = routes.read_text()
    assert '@router.post("", status_code=202)' in body
    assert '@router.get("/{workflow_id}")' in body
    assert '@router.delete("/{workflow_id}"' in body


def test_parses_after_two_runs() -> None:
    d = create_fixture_project(name="lrt_t10")
    add_long_running_task(ToolInput(project_dir=str(d)))
    add_long_running_task(ToolInput(project_dir=str(d)))
    _assert_parse(d)


def test_mcp_tool_metadata() -> None:
    assert MCP_TOOL["entry"] == "add_long_running_task"
    assert "core.venous.jobs.WorkflowRun" in MCP_TOOL["imports_primitives"]
    assert "core.venous.jobs.DurableTimer" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.WorkflowAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    d = create_fixture_project(name="lrt_t11")
    r = add_long_running_task(ToolInput(project_dir=str(d)))
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
