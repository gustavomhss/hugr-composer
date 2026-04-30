"""Structural tests for the refactored TOOL-057 ``add_rate_limiting``.

Refactor (CONTRACT §B1.0 + §B1.0.1):

1. Copy primitive ``core.venous.resiliency.RateLimiter``.
2. Copy adapter ``core.venous._adapters.fastapi.RateLimiterAdapter``.
3. Emit a ≤ 20-line ``app/rate_limit.py`` calling the adapter's install().

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_rate_limiting.py -q
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_rate_limiting import MCP_TOOL, add_rate_limiting
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
    d = create_fixture_project(name="rl_t01")
    r = add_rate_limiting(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    d = create_fixture_project(name="rl_t02")
    r1 = add_rate_limiting(ToolInput(project_dir=str(d)))
    assert r1.status == "success"
    r2 = add_rate_limiting(ToolInput(project_dir=str(d)))
    assert r2.status == "no_op"
    assert not r2.files_created and not r2.files_modified


def test_dry_run_writes_nothing() -> None:
    d = create_fixture_project(name="rl_t03")
    before = {f: f.read_text() for f in _all_py(d)}
    r = add_rate_limiting(ToolInput(project_dir=str(d), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py(d)}
    assert before == after


def test_primitive_copied() -> None:
    d = create_fixture_project(name="rl_t04")
    add_rate_limiting(ToolInput(project_dir=str(d)))
    p = d / "core" / "venous" / "resiliency" / "RateLimiter" / "RateLimiter.py"
    assert p.exists(), p
    body = p.read_text()
    assert "InMemoryRateLimiter" in body
    assert "Copied from HuGR Smith" in body


def test_adapter_copied() -> None:
    d = create_fixture_project(name="rl_t05")
    add_rate_limiting(ToolInput(project_dir=str(d)))
    a = d / "core" / "venous" / "_adapters" / "fastapi" / "RateLimiterAdapter.py"
    assert a.exists()
    assert "def install(" in a.read_text()


def test_manifest_records_provenance() -> None:
    d = create_fixture_project(name="rl_t06")
    add_rate_limiting(ToolInput(project_dir=str(d)))
    manifest = json.loads((d / ".venous_manifest.json").read_text())
    assert "core.venous.resiliency.RateLimiter" in {p["qualified_name"] for p in manifest["primitives"]}
    assert "core.venous._adapters.fastapi.RateLimiterAdapter" in {a["qualified_name"] for a in manifest["adapters"]}


def test_glue_imports_adapter() -> None:
    d = create_fixture_project(name="rl_t07")
    add_rate_limiting(ToolInput(project_dir=str(d)))
    glue = d / "app" / "rate_limit.py"
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.RateLimiterAdapter import install" in body
    assert "def install_rate_limiting" in body


def test_glue_body_under_20_loc() -> None:
    d = create_fixture_project(name="rl_t08")
    add_rate_limiting(ToolInput(project_dir=str(d)))
    tree = ast.parse((d / "app" / "rate_limit.py").read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, body_lines


def test_config_patched() -> None:
    d = create_fixture_project(name="rl_t09")
    add_rate_limiting(ToolInput(project_dir=str(d)))
    body = (d / "app" / "core" / "config.py").read_text()
    assert "RATE_LIMIT_PER_SECOND" in body
    assert "RATE_LIMIT_BURST" in body


def test_parses_after_two_runs() -> None:
    d = create_fixture_project(name="rl_t10")
    add_rate_limiting(ToolInput(project_dir=str(d)))
    add_rate_limiting(ToolInput(project_dir=str(d)))
    _assert_parse(d)


def test_mcp_tool_metadata() -> None:
    assert MCP_TOOL["entry"] == "add_rate_limiting"
    assert "core.venous.resiliency.RateLimiter" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.RateLimiterAdapter" in MCP_TOOL["imports_adapters"]
    for key in ("name", "description", "tags", "entry"):
        assert key in MCP_TOOL


def test_execution_time_recorded() -> None:
    d = create_fixture_project(name="rl_t11")
    r = add_rate_limiting(ToolInput(project_dir=str(d)))
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
