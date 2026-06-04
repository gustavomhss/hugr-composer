"""Structural tests for the refactored TOOL-016 ``add_webhook_receiver``.

CONTRACT §B1.3 refactor: copies SignatureVerifier + IdempotentConsumer +
AuditEvent primitives and the FastAPI WebhookReceiverAdapter into the
project, then writes a ≤ 20-line ``app/webhook_receiver.py`` caller.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_webhook_receiver import MCP_TOOL, add_webhook_receiver
from tests.common.fixture_factory import create_fixture_project


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _bare_project() -> Path:
    """A valid (existing) dir MISSING the config/requirements prereqs, so the
    auto-scaffold and prerequisite-error code paths get exercised."""
    d = Path(tempfile.mkdtemp()) / "bare"
    d.mkdir()
    return d


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
    adapter = (
        project_dir / "core" / "venous" / "_adapters" / "fastapi" / "WebhookReceiverAdapter.py"
    )
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


def test_execution_time_within_sane_bound() -> None:
    """elapsed_ms is a small positive number, not a monotonic-sum blow-up.

    Guards ``_elapsed_ms`` (L162) against ``monotonic() - start`` -> ``+``,
    which would yield a multi-billion-ms value while still being > 0.
    """
    project_dir = create_fixture_project(name="whr_t11")
    ms = add_webhook_receiver(ToolInput(project_dir=str(project_dir))).execution_time_ms
    assert 0 < ms < 60_000, f"implausible execution_time_ms={ms}"


def test_auto_scaffolds_missing_prereqs() -> None:
    """A bare project (no config/requirements) is auto-scaffolded on a real run.

    Guards ``auto_scaffold=not inp.dry_run`` (L76: drop the ``not`` -> no
    scaffold -> error) and ``files_created = list(scaffolded or [])`` (L85:
    ``or`` -> ``and`` -> scaffolded files silently dropped from the report).
    """
    p = _bare_project()
    r = add_webhook_receiver(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    created = set(r.files_created)
    # The scaffolded config.py must be reported in files_created (guards the
    # ``scaffolded or []`` -> ``and`` mutation, which would drop it).
    assert any(c.endswith("config.py") for c in created), created
    # Physically scaffolded (without auto_scaffold these would never exist).
    assert (p / "app" / "core" / "config.py").exists()
    assert (p / "requirements.txt").exists()


def test_missing_prereqs_dry_run_reports_error() -> None:
    """dry_run on a bare project: auto_scaffold is OFF, so prereqs are missing.

    Guards the error-message ``+`` concat path (L81: a ``+`` -> ``-`` mutation
    makes ``str - str`` raise ``TypeError`` instead of returning the error
    result).
    """
    p = _bare_project()
    r = add_webhook_receiver(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "error"
    assert "Prerequisites not met" in (r.error or "")


def test_only_python_files_are_ast_validated() -> None:
    """The scaffolded ``requirements.txt`` (non-.py text) must be skipped by the
    post-write ast.parse loop.

    Guards ``p.suffix == ".py" and p.is_file()`` (L124): both an ``and`` ->
    ``or`` and an ``==`` -> ``!=`` mutation would ast.parse requirements.txt,
    raising a SyntaxError and flipping the result to ``error``.
    """
    p = _bare_project()
    r = add_webhook_receiver(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    assert (p / "requirements.txt").exists()  # the non-.py file was present...
    # ...and the run still wired the glue module successfully.
    assert "WebhookReceiverAdapter" in (p / "app" / "webhook_receiver.py").read_text()


def test_succeeds_when_app_dir_already_exists() -> None:
    """The fixture project already ships an ``app/`` package, so the real run
    must tolerate a pre-existing target dir.

    Guards ``app_dir.mkdir(parents=True, exist_ok=True)`` (L116): flipping the
    ``exist_ok`` flag to ``False`` raises ``FileExistsError`` on the
    already-present ``app/`` dir, turning success into an uncaught crash.
    """
    project_dir = create_fixture_project(name="whr_t12")
    assert (project_dir / "app").is_dir()  # pre-existing target
    r = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    assert (project_dir / "app" / "webhook_receiver.py").exists()


def test_succeeds_when_tests_dir_already_exists() -> None:
    """The fixture project already ships a ``tests/`` dir, so ``_emit_project_test``
    must tolerate a pre-existing target dir.

    Guards ``tests_dir.mkdir(parents=True, exist_ok=True)`` (L153): flipping the
    ``exist_ok`` flag to ``False`` raises ``FileExistsError`` on the
    already-present ``tests/`` dir, turning success into an uncaught crash.
    """
    project_dir = create_fixture_project(name="whr_t13")
    assert (project_dir / "tests").is_dir()  # pre-existing target
    r = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    assert (project_dir / "tests" / "test_add_webhook_receiver_emitted.py").exists()


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
