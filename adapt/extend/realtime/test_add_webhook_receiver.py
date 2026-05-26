"""Structural tests for the refactored TOOL-016 ``add_webhook_receiver``.

CONTRACT §B1.3 refactor: copies SignatureVerifier + IdempotentConsumer +
AuditEvent primitives and the FastAPI WebhookReceiverAdapter into the
project, then writes a ≤ 20-line ``app/webhook_receiver.py`` caller.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_webhook_receiver import MCP_TOOL, add_webhook_receiver
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
    project_dir = create_fixture_project(name="whr_t01")
    r = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    project_dir = create_fixture_project(name="whr_t02")
    assert add_webhook_receiver(ToolInput(project_dir=str(project_dir))).status == "success"
    r2 = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"
    assert not r2.files_created


def test_dry_run_writes_nothing() -> None:
    project_dir = create_fixture_project(name="whr_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    r = add_webhook_receiver(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


def test_primitives_copied_into_project() -> None:
    project_dir = create_fixture_project(name="whr_t04")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    for prim in ("SignatureVerifier", "IdempotentConsumer", "AuditEvent"):
        hits = list((project_dir / "core" / "venous").rglob(f"{prim}.py"))
        assert hits, f"primitive {prim} not copied"


def test_adapter_copied_into_project() -> None:
    project_dir = create_fixture_project(name="whr_t05")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    adapter = project_dir / "core" / "venous" / "_adapters" / "fastapi" / "WebhookReceiverAdapter.py"
    assert adapter.exists()
    assert "def install(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    project_dir = create_fixture_project(name="whr_t06")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    primitives = {p["qualified_name"] for p in manifest["primitives"]}
    adapters = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.security.SignatureVerifier" in primitives
    assert "core.venous.events.IdempotentConsumer" in primitives
    assert "core.venous.compliance.AuditEvent" in primitives
    assert "core.venous._adapters.fastapi.WebhookReceiverAdapter" in adapters


def test_glue_imports_adapter() -> None:
    project_dir = create_fixture_project(name="whr_t07")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "webhook_receiver.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.WebhookReceiverAdapter import install" in body
    assert "def install_webhook_receiver" in body


def test_glue_body_under_20_loc() -> None:
    project_dir = create_fixture_project(name="whr_t08")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "webhook_receiver.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, f"glue body is {body_lines} LoC; budget 20"


def test_all_py_parse_after_two_runs() -> None:
    project_dir = create_fixture_project(name="whr_t09")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_lists_imported_primitives() -> None:
    assert MCP_TOOL["entry"] == "add_webhook_receiver"
    assert "core.venous.security.SignatureVerifier" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.WebhookReceiverAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    project_dir = create_fixture_project(name="whr_t10")
    r = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert r.execution_time_ms > 0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in tests:
        try:
            fn(); passed += 1; print(f"  PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if not failed else 1)
