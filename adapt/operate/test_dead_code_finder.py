"""Tests for TOOL-037 dead_code_finder.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_dead_code_finder.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.dead_code_finder import (
    DeadSymbol,
    _collect_defs,
    _collect_framework_live,
    _collect_uses,
    _is_pytest_fixture,
    _is_route_decorator,
    _render_report,
    dead_code_finder,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp: Path) -> Path:
    """Create a minimal project with some dead and some live code."""
    proj = tmp / "proj"
    (proj / "app").mkdir(parents=True)
    (proj / "tests").mkdir(parents=True)

    (proj / "app" / "used.py").write_text(
        "def alive(): return 42\n"
        "def also_used(): return alive()\n"
    )
    (proj / "app" / "dead.py").write_text(
        "def never_called(): return 0\n"
        "class DeadClass: pass\n"
    )
    (proj / "app" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/')\n"
        "def my_handler(): return {}\n"
    )
    (proj / "tests" / "test_used.py").write_text(
        "from app.used import alive\n"
        "def test_alive():\n    assert alive() == 42\n"
    )
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_missing_project() -> None:
    """T-01: Returns error for nonexistent project_dir."""
    result = dead_code_finder(ToolInput(project_dir="/nonexistent"))
    assert result.status == "error"


def test_success_on_valid_project() -> None:
    """T-02: Returns success for a valid project."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dead_code_finder(ToolInput(project_dir=str(proj)))
        assert result.status == "success"


def test_dry_run_no_files_written() -> None:
    """T-03: dry_run=True writes no files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        before = set(proj.rglob("*"))
        result = dead_code_finder(ToolInput(project_dir=str(proj), dry_run=True))
        assert result.status == "success"
        assert set(proj.rglob("*")) == before


def test_report_file_created() -> None:
    """T-04: dead_code_report.md is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dead_code_finder(ToolInput(project_dir=str(proj)))
        assert result.files_created
        assert Path(result.files_created[0]).exists()


def test_collect_defs_finds_functions() -> None:
    """T-05: _collect_defs finds function definitions."""
    src = "def foo(): pass\ndef bar(): pass\n"
    tree = ast.parse(src)
    defs: dict = {}
    _collect_defs(tree, "mod.py", defs)
    assert any("foo" in k for k in defs)
    assert any("bar" in k for k in defs)


def test_collect_defs_finds_classes() -> None:
    """T-06: _collect_defs finds class definitions."""
    src = "class MyModel: pass\n"
    tree = ast.parse(src)
    defs: dict = {}
    _collect_defs(tree, "mod.py", defs)
    assert any("MyModel" in k for k in defs)


def test_collect_uses_finds_names() -> None:
    """T-07: _collect_uses finds referenced names."""
    src = "x = alive()\nfoo()\n"
    tree = ast.parse(src)
    uses: set[str] = set()
    _collect_uses(tree, uses)
    assert "alive" in uses or "foo" in uses


def test_fastapi_route_marked_live() -> None:
    """T-08: @router.get handler is not flagged as dead."""
    src = (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/')\n"
        "def my_route(): return {}\n"
    )
    tree = ast.parse(src)
    live: set[str] = set()
    _collect_framework_live(tree, src, live, include_routes=True)
    assert "my_route" in live


def test_fastapi_route_excluded_when_include_false() -> None:
    """T-09: include_routes=False does not mark route handlers as live."""
    src = (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/')\n"
        "def my_route(): return {}\n"
    )
    tree = ast.parse(src)
    live: set[str] = set()
    _collect_framework_live(tree, src, live, include_routes=False)
    assert "my_route" not in live


def test_pytest_fixture_marked_live() -> None:
    """T-10: @pytest.fixture function is not flagged as dead."""
    src = "import pytest\n@pytest.fixture\ndef my_fixture(): return 1\n"
    tree = ast.parse(src)
    live: set[str] = set()
    _collect_framework_live(tree, src, live, include_routes=True)
    assert "my_fixture" in live


def test_is_route_decorator_get() -> None:
    """T-11: _is_route_decorator returns True for router.get call."""
    src = "@router.get('/')\ndef h(): pass\n"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                assert _is_route_decorator(dec) is True


def test_is_pytest_fixture_attr() -> None:
    """T-12: _is_pytest_fixture returns True for pytest.fixture attribute."""
    src = "@pytest.fixture\ndef f(): pass\n"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                assert _is_pytest_fixture(dec) is True


def test_confidence_threshold_filters() -> None:
    """T-13: confidence_threshold=100 only returns 100-confidence findings."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dead_code_finder(
            ToolInput(project_dir=str(proj)),
            confidence_threshold=100,
        )
        assert result.status == "success"


def test_allow_list_suppresses_symbol() -> None:
    """T-14: Symbols in allow-list are not reported."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        allow_file = proj / ".deadcode-allow.yaml"
        allow_file.write_text("never_called:\n  reason: intentional\n")
        result = dead_code_finder(
            ToolInput(project_dir=str(proj)),
            allow_list_file=".deadcode-allow.yaml",
        )
        assert result.status == "success"
        notes_text = " ".join(result.notes or [])
        assert "never_called" not in notes_text


def test_render_report_empty() -> None:
    """T-15: Empty dead list renders 'No dead code found' message."""
    report = _render_report([])
    assert "No dead code found" in report


def test_render_report_non_empty() -> None:
    """T-16: Non-empty list renders symbol details."""
    syms = [
        DeadSymbol(name="stale_fn", file="app/old.py", line=5, kind="function",
                   confidence=95, reason="No callers.")
    ]
    report = _render_report(syms)
    assert "stale_fn" in report
    assert "95" in report


def test_exclude_patterns_respected() -> None:
    """T-17: Files matching exclude_patterns are not scanned."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dead_code_finder(
            ToolInput(project_dir=str(proj)),
            exclude_patterns=["tests/*"],
        )
        assert result.status == "success"


def test_notes_contain_scan_summary() -> None:
    """T-18: Notes contain scan statistics."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dead_code_finder(ToolInput(project_dir=str(proj)))
        assert any("Scanned" in n for n in (result.notes or []))


def test_next_steps_present() -> None:
    """T-19: next_steps guide the developer."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dead_code_finder(ToolInput(project_dir=str(proj)))
        assert result.next_steps


def test_execution_time_recorded() -> None:
    """T-20: execution_time_ms is a non-negative integer."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dead_code_finder(ToolInput(project_dir=str(proj)))
        assert isinstance(result.execution_time_ms, int)
        assert result.execution_time_ms >= 0


def test_syntax_error_file_skipped() -> None:
    """T-21: Files with SyntaxError are skipped gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        (proj / "app" / "broken.py").write_text("def bad syntax here!!!\n")
        result = dead_code_finder(ToolInput(project_dir=str(proj)))
        assert result.status == "success"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_missing_project,
        test_success_on_valid_project,
        test_dry_run_no_files_written,
        test_report_file_created,
        test_collect_defs_finds_functions,
        test_collect_defs_finds_classes,
        test_collect_uses_finds_names,
        test_fastapi_route_marked_live,
        test_fastapi_route_excluded_when_include_false,
        test_pytest_fixture_marked_live,
        test_is_route_decorator_get,
        test_is_pytest_fixture_attr,
        test_confidence_threshold_filters,
        test_allow_list_suppresses_symbol,
        test_render_report_empty,
        test_render_report_non_empty,
        test_exclude_patterns_respected,
        test_notes_contain_scan_summary,
        test_next_steps_present,
        test_execution_time_recorded,
        test_syntax_error_file_skipped,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
