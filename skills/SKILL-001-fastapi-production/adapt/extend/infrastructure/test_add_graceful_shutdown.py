"""Structural tests for the refactored TOOL-100 ``add_graceful_shutdown``.

The refactor (CONTRACT §B1.0 + §B1.0.1) replaces the old 500-line inline
boilerplate with a three-step flow:

1. Copy the primitive `core.venous.resiliency.GracefulShutdown` into the
   generated project (via `generators/scaffold_venous.ensure_primitives`).
2. Copy the FastAPI adapter
   `core.venous._adapters.fastapi.GracefulShutdownAdapter` alongside it.
3. Write a ≤ 20-line `app/shutdown.py` that imports the adapter and
   calls `install(app, ...)`.

Tests below assert the new delivery contract.  Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_graceful_shutdown.py -q
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_graceful_shutdown import (
    MCP_TOOL,
    add_graceful_shutdown,
)
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:  # pragma: no cover
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Status + idempotency
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """Fresh project → status='success'."""
    project_dir = create_fixture_project(name="gs_t01")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run → no_op, no new files."""
    project_dir = create_fixture_project(name="gs_t02")
    r1 = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"
    assert not r2.files_created
    assert not r2.files_modified


def test_dry_run_writes_nothing() -> None:
    """dry_run=True returns success but does not modify disk."""
    project_dir = create_fixture_project(name="gs_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


# ---------------------------------------------------------------------------
# Primitive + adapter copied in, manifest tracks provenance
# ---------------------------------------------------------------------------


def test_primitive_copied_into_project() -> None:
    """The primitive must land at core/venous/resiliency/GracefulShutdown/."""
    project_dir = create_fixture_project(name="gs_t04")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    copied = project_dir / "core" / "venous" / "resiliency" / "GracefulShutdown" / "GracefulShutdown.py"
    assert copied.exists(), f"primitive not copied: {copied}"
    body = copied.read_text()
    assert "class GracefulShutdown" in body
    assert "Copied from HuGR Smith" in body  # attribution footer present


def test_adapter_copied_into_project() -> None:
    """The FastAPI adapter must land at core/venous/_adapters/fastapi/."""
    project_dir = create_fixture_project(name="gs_t05")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    adapter = (
        project_dir / "core" / "venous" / "_adapters" / "fastapi"
        / "GracefulShutdownAdapter.py"
    )
    assert adapter.exists(), f"adapter not copied: {adapter}"
    body = adapter.read_text()
    assert "def install(" in body
    assert "Copied from HuGR Smith" in body


def test_venous_manifest_records_provenance() -> None:
    """.venous_manifest.json must list both the primitive and the adapter."""
    project_dir = create_fixture_project(name="gs_t06")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    manifest_path = project_dir / ".venous_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    prim_names = {p["qualified_name"] for p in manifest["primitives"]}
    adapter_names = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.resiliency.GracefulShutdown" in prim_names
    assert "core.venous._adapters.fastapi.GracefulShutdownAdapter" in adapter_names


# ---------------------------------------------------------------------------
# Glue is thin + correct
# ---------------------------------------------------------------------------


def test_glue_file_imports_adapter() -> None:
    """app/shutdown.py must import the adapter's install() function."""
    project_dir = create_fixture_project(name="gs_t07")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "shutdown.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.GracefulShutdownAdapter import install" in body
    assert "def install_graceful_shutdown" in body


def test_glue_file_under_20_loc_body() -> None:
    """The glue file's executable body must be ≤ 20 LoC (excluding imports/docstrings)."""
    project_dir = create_fixture_project(name="gs_t08")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "shutdown.py"
    tree = ast.parse(glue.read_text())
    # Only count function bodies as "glue".
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, f"glue body is {body_lines} LoC; budget is 20"


# ---------------------------------------------------------------------------
# Config patch (unchanged behaviour vs original)
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """SHUTDOWN_* fields must appear in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="gs_t09")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    config = project_dir / "app" / "core" / "config.py"
    body = config.read_text()
    assert "SHUTDOWN_DRAIN_SECONDS" in body
    assert "SHUTDOWN_TIMEOUT_SECONDS" in body
    for line in body.splitlines():
        if "SHUTDOWN_" in line and ":" in line and "#" not in line:
            assert line.startswith("    "), f"config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# Whole project still parses after tool runs (twice)
# ---------------------------------------------------------------------------


def test_all_py_parse_after_two_runs() -> None:
    """All generated .py files parse after back-to-back invocations."""
    project_dir = create_fixture_project(name="gs_t10")
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# MCP_TOOL metadata correctness
# ---------------------------------------------------------------------------


def test_mcp_tool_lists_imported_primitives() -> None:
    """MCP_TOOL must advertise the primitive + adapter it ships."""
    assert MCP_TOOL["entry"] == "add_graceful_shutdown"
    assert "core.venous.resiliency.GracefulShutdown" in MCP_TOOL["imports_primitives"]
    assert (
        "core.venous._adapters.fastapi.GracefulShutdownAdapter"
        in MCP_TOOL["imports_adapters"]
    )


def test_mcp_tool_has_required_keys() -> None:
    """MCP_TOOL must carry the canonical schema keys."""
    for key in ("name", "description", "tags", "entry"):
        assert key in MCP_TOOL, f"MCP_TOOL missing key: {key}"


# ---------------------------------------------------------------------------
# Timing + next_steps
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer on every return."""
    project_dir = create_fixture_project(name="gs_t11")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_shutdown() -> None:
    """next_steps must reference SHUTDOWN_* env vars or drain semantics."""
    project_dir = create_fixture_project(name="gs_t12")
    result = add_graceful_shutdown(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps).lower()
    assert "shutdown" in combined or "drain" in combined


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run_writes_nothing,
        test_primitive_copied_into_project,
        test_adapter_copied_into_project,
        test_venous_manifest_records_provenance,
        test_glue_file_imports_adapter,
        test_glue_file_under_20_loc_body,
        test_config_fields_patched,
        test_all_py_parse_after_two_runs,
        test_mcp_tool_lists_imported_primitives,
        test_mcp_tool_has_required_keys,
        test_execution_time_recorded,
        test_next_steps_mention_shutdown,
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
