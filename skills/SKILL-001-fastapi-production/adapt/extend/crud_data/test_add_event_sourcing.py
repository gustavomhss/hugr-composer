"""Structural tests for the refactored TOOL-079 ``add_event_sourcing``.

CONTRACT §B1.3 refactor: copies EventSourcedStore + DomainEvent primitives
and the FastAPI EventSourcedStoreAdapter into the project, then writes a
≤ 20-line ``app/event_store.py`` caller.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_event_sourcing import MCP_TOOL, add_event_sourcing
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
    project_dir = create_fixture_project(name="es_t01")
    r = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    project_dir = create_fixture_project(name="es_t02")
    assert add_event_sourcing(ToolInput(project_dir=str(project_dir))).status == "success"
    r2 = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"
    assert not r2.files_created


def test_dry_run_writes_nothing() -> None:
    project_dir = create_fixture_project(name="es_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    r = add_event_sourcing(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


def test_primitives_copied_into_project() -> None:
    project_dir = create_fixture_project(name="es_t04")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    ess = project_dir / "core" / "venous" / "events" / "EventSourcedStore" / "EventSourcedStore.py"
    de = project_dir / "core" / "venous" / "events" / "DomainEvent" / "DomainEvent.py"
    assert ess.exists()
    assert de.exists()


def test_adapter_copied_into_project() -> None:
    project_dir = create_fixture_project(name="es_t05")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    adapter = (
        project_dir / "core" / "venous" / "_adapters" / "fastapi" / "EventSourcedStoreAdapter.py"
    )
    assert adapter.exists()
    assert "def install(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    project_dir = create_fixture_project(name="es_t06")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    primitives = {p["qualified_name"] for p in manifest["primitives"]}
    adapters = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.events.EventSourcedStore" in primitives
    assert "core.venous.events.DomainEvent" in primitives
    assert "core.venous._adapters.fastapi.EventSourcedStoreAdapter" in adapters


def test_glue_imports_adapter() -> None:
    project_dir = create_fixture_project(name="es_t07")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "event_store.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.EventSourcedStoreAdapter import install" in body
    assert "def install_event_store" in body


def test_glue_superuser_gates_event_routes() -> None:
    """R5-O2-D6: the /events router must be auth-gated, not anonymous.

    The glue must hand the adapter a superuser auth dependency so reading or
    appending another aggregate's raw event stream over HTTP requires auth.
    """
    project_dir = create_fixture_project(name="es_auth_gate")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    glue = (project_dir / "app" / "event_store.py").read_text()
    assert "from app.api.deps import get_current_superuser" in glue, (
        "glue must import the superuser auth dependency"
    )
    assert "auth_dependency=get_current_superuser" in glue, (
        "install() must receive the superuser auth dependency (R5-O2-D6)"
    )


def test_glue_body_under_20_loc() -> None:
    project_dir = create_fixture_project(name="es_t08")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "event_store.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, f"glue body is {body_lines} LoC; budget 20"


def test_all_py_parse_after_two_runs() -> None:
    project_dir = create_fixture_project(name="es_t09")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_lists_imported_primitives() -> None:
    assert MCP_TOOL["entry"] == "add_event_sourcing"
    assert "core.venous.events.EventSourcedStore" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.EventSourcedStoreAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    project_dir = create_fixture_project(name="es_t10")
    r = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r.execution_time_ms > 0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if not failed else 1)
