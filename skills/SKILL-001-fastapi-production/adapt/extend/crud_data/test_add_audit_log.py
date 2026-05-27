"""Structural tests for the refactored TOOL-005 ``add_audit_log``.

CONTRACT §B1.3 refactor: copies AuditEvent + TamperEvidentAuditLog primitives
and the FastAPI AuditLogAdapter into the project, then writes a ≤ 20-line
``app/audit_log.py`` caller.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_audit_log import MCP_TOOL, add_audit_log
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
    project_dir = create_fixture_project(name="al_t01")
    r = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    project_dir = create_fixture_project(name="al_t02")
    assert add_audit_log(ToolInput(project_dir=str(project_dir))).status == "success"
    r2 = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"
    assert not r2.files_created


def test_dry_run_writes_nothing() -> None:
    project_dir = create_fixture_project(name="al_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    r = add_audit_log(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


def test_primitives_copied_into_project() -> None:
    project_dir = create_fixture_project(name="al_t04")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    ae = project_dir / "core" / "venous" / "compliance" / "AuditEvent" / "AuditEvent.py"
    teal = project_dir / "core" / "venous" / "compliance" / "TamperEvidentAuditLog" / "TamperEvidentAuditLog.py"
    assert ae.exists()
    assert teal.exists()


def test_adapter_copied_into_project() -> None:
    project_dir = create_fixture_project(name="al_t05")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    adapter = project_dir / "core" / "venous" / "_adapters" / "fastapi" / "AuditLogAdapter.py"
    assert adapter.exists()
    assert "def install(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    project_dir = create_fixture_project(name="al_t06")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    primitives = {p["qualified_name"] for p in manifest["primitives"]}
    adapters = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.compliance.AuditEvent" in primitives
    assert "core.venous.compliance.TamperEvidentAuditLog" in primitives
    assert "core.venous._adapters.fastapi.AuditLogAdapter" in adapters


def test_glue_imports_adapter() -> None:
    project_dir = create_fixture_project(name="al_t07")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "audit_log.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.AuditLogAdapter import install" in body
    assert "def install_audit_log" in body


def test_glue_body_under_20_loc() -> None:
    project_dir = create_fixture_project(name="al_t08")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "audit_log.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, f"glue body is {body_lines} LoC; budget 20"


def test_all_py_parse_after_two_runs() -> None:
    project_dir = create_fixture_project(name="al_t09")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_lists_imported_primitives() -> None:
    assert MCP_TOOL["entry"] == "add_audit_log"
    assert "core.venous.compliance.TamperEvidentAuditLog" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.AuditLogAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    project_dir = create_fixture_project(name="al_t10")
    r = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert r.execution_time_ms > 0


# ---------------------------------------------------------------------------
# BUG A regression tests — audit log must be wired, not just copied
# ---------------------------------------------------------------------------

def test_main_py_calls_install_audit_log() -> None:
    """Regression: app/main.py must call install_audit_log(app) after tool runs.

    Before the fix the tool returned success but never wired the audit log
    into main.py, making the feature silently inactive.
    """
    project_dir = create_fixture_project(name="al_t11")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    main = project_dir / "app" / "main.py"
    assert main.exists(), "main.py missing from fixture project"
    content = main.read_text()
    assert "install_audit_log(app)" in content, (
        "main.py must call install_audit_log(app) — audit log was not wired"
    )


def test_main_py_imports_install_audit_log() -> None:
    """Regression: main.py must import install_audit_log from app.audit_log."""
    project_dir = create_fixture_project(name="al_t12")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    main = project_dir / "app" / "main.py"
    content = main.read_text()
    assert "from app.audit_log import install_audit_log" in content, (
        "main.py must import install_audit_log"
    )


def test_glue_no_hardcoded_secret() -> None:
    """Regression: audit_log.py must NOT contain the 'change-me' placeholder secret.

    The old implementation silently fell back to a hardcoded placeholder when
    AUDIT_LOG_HMAC_SECRET was absent, undermining tamper-evidence guarantees.
    """
    project_dir = create_fixture_project(name="al_t13")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "audit_log.py"
    assert glue.exists()
    content = glue.read_text()
    assert "change-me" not in content, (
        "audit_log.py must not contain 'change-me' placeholder secret"
    )


def test_glue_fails_closed_on_missing_secret() -> None:
    """Regression: install_audit_log must raise RuntimeError when env var absent.

    The fix replaces the silent fallback to a hardcoded secret with a
    fail-closed RuntimeError so misconfigured deployments fail at startup.
    """
    project_dir = create_fixture_project(name="al_t14")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "audit_log.py"
    content = glue.read_text()
    assert "RuntimeError" in content, (
        "install_audit_log must raise RuntimeError when AUDIT_LOG_HMAC_SECRET is absent"
    )


def test_idempotent_wiring() -> None:
    """Regression: running the tool twice must not double-insert the wiring."""
    project_dir = create_fixture_project(name="al_t15")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    main = project_dir / "app" / "main.py"
    content = main.read_text()
    # install_audit_log(app) should appear exactly once
    count = content.count("install_audit_log(app)")
    assert count == 1, (
        f"install_audit_log(app) appears {count} times in main.py; expected exactly 1"
    )


def test_files_modified_lists_main_py() -> None:
    """Regression: files_modified must include main.py to report the wiring."""
    project_dir = create_fixture_project(name="al_t16")
    r = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success"
    assert r.files_modified, "files_modified should list main.py after wiring"
    modified_names = [Path(p).name for p in r.files_modified]
    assert "main.py" in modified_names, (
        f"main.py missing from files_modified; got: {modified_names}"
    )


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
