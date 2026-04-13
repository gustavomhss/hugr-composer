"""Tests for TOOL-035 blast_radius.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_blast_radius.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.blast_radius import (
    blast_radius,
    _build_import_graph,
    _build_reverse_graph,
    _bfs,
    _collect_symbol_defs,
    _render_report,
    _rel,
    _ms,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp: Path) -> Path:
    """Create a minimal fake FastAPI project tree."""
    proj = tmp / "myapp"
    (proj / "app" / "models").mkdir(parents=True)
    (proj / "app" / "api" / "routes").mkdir(parents=True)
    (proj / "app" / "crud").mkdir(parents=True)
    (proj / "tests").mkdir(parents=True)

    (proj / "app" / "models" / "item.py").write_text(
        "from app.models.base import Base\nclass Item(Base): pass\n"
    )
    (proj / "app" / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\nclass Base(DeclarativeBase): pass\n"
    )
    (proj / "app" / "crud" / "item.py").write_text(
        "from app.models.item import Item\ndef get_item(): pass\n"
    )
    (proj / "app" / "api" / "routes" / "item.py").write_text(
        "from app.crud.item import get_item\nfrom fastapi import APIRouter\n"
        "router = APIRouter()\n@router.get('/')\ndef read_item(): return get_item()\n"
    )
    (proj / "tests" / "test_item.py").write_text(
        "from app.crud.item import get_item\ndef test_get(): get_item()\n"
    )
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_on_missing_project() -> None:
    """T-01: Returns error when project_dir does not exist."""
    result = blast_radius(ToolInput(project_dir="/nonexistent/path"), target="x.py")
    assert result.status == "error"
    assert "does not exist" in (result.error or "")


def test_error_without_target_or_diff() -> None:
    """T-02: Returns error when neither target nor diff_ref is provided."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(ToolInput(project_dir=str(proj)))
        assert result.status == "error"
        assert "target" in (result.error or "").lower() or "diff_ref" in (result.error or "").lower()


def test_success_with_target() -> None:
    """T-03: Returns success for a valid target."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(
            ToolInput(project_dir=str(proj)),
            target="app/models/item.py::Item",
        )
        assert result.status == "success"


def test_dry_run_no_files() -> None:
    """T-04: dry_run=True produces no files on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        before = list(proj.rglob("*"))
        result = blast_radius(
            ToolInput(project_dir=str(proj), dry_run=True),
            target="app/models/item.py",
        )
        assert result.status == "success"
        assert not result.files_created
        assert list(proj.rglob("*")) == before


def test_build_import_graph_non_empty() -> None:
    """T-05: Import graph has entries for a real project."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        graph = _build_import_graph(proj)
        assert len(graph) > 0


def test_reverse_graph_inversion() -> None:
    """T-06: Reverse graph correctly inverts forward edges."""
    graph = {"a.py": {"b.py"}, "b.py": {"c.py"}, "c.py": set()}
    rev = _build_reverse_graph(graph)
    assert "a.py" in rev.get("b.py", set())
    assert "b.py" in rev.get("c.py", set())


def test_bfs_depth_limit() -> None:
    """T-07: BFS respects max depth limit."""
    rev = {"a.py": {"b.py"}, "b.py": {"c.py"}, "c.py": {"d.py"}, "d.py": {"e.py"}}
    visited: dict[str, int] = {}
    _bfs("a.py", rev, max_depth=2, visited=visited)
    assert "e.py" not in visited  # depth 4 — should be cut off


def test_bfs_visits_within_depth() -> None:
    """T-08: BFS visits nodes within depth limit."""
    rev = {"a.py": {"b.py"}, "b.py": {"c.py"}}
    visited: dict[str, int] = {}
    _bfs("a.py", rev, max_depth=3, visited=visited)
    assert "b.py" in visited
    assert "c.py" in visited


def test_bfs_no_cycle_infinite_loop() -> None:
    """T-09: BFS with cycle does not loop forever."""
    rev = {"a.py": {"b.py"}, "b.py": {"a.py"}}
    visited: dict[str, int] = {}
    _bfs("a.py", rev, max_depth=5, visited=visited)
    assert len(visited) >= 1  # Terminates


def test_symbol_defs_collected() -> None:
    """T-10: Symbol defs include class names from project files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        defs = _collect_symbol_defs(proj)
        assert any("Item" in k for k in defs)


def test_report_markdown_format() -> None:
    """T-11: Markdown report contains expected sections."""
    report = _render_report(
        seeds=["app/models/item.py::Item"],
        production={"app/crud/item.py": 1},
        tests={"tests/test_item.py": 2},
        fmt="markdown",
    )
    assert "Blast Radius Report" in report
    assert "Production Impact" in report
    assert "Test Impact" in report


def test_report_json_format() -> None:
    """T-12: JSON report is valid JSON."""
    import json
    report = _render_report(
        seeds=["app/models/item.py"],
        production={"app/crud/item.py": 1},
        tests={},
        fmt="json",
    )
    data = json.loads(report)
    assert "seeds" in data
    assert "production" in data


def test_report_dot_format() -> None:
    """T-13: DOT report contains graph keywords."""
    report = _render_report(
        seeds=["app/models/item.py"],
        production={"app/crud/item.py": 1},
        tests={},
        fmt="dot",
    )
    assert "digraph" in report


def test_report_no_production_impact() -> None:
    """T-14: Empty production impact shows a notice."""
    report = _render_report(
        seeds=["app/models/isolated.py"],
        production={},
        tests={},
        fmt="markdown",
    )
    assert "No production files impacted" in report


def test_report_file_created_markdown() -> None:
    """T-15: Markdown report file is created on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(
            ToolInput(project_dir=str(proj)),
            target="app/models/item.py",
            output_format="markdown",
        )
        assert result.status == "success"
        assert result.files_created
        assert Path(result.files_created[0]).exists()


def test_report_file_created_dot() -> None:
    """T-16: DOT report file is created on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(
            ToolInput(project_dir=str(proj)),
            target="app/models/item.py",
            output_format="dot",
        )
        assert result.status == "success"
        assert result.files_created


def test_include_tests_false() -> None:
    """T-17: include_tests=False excludes test files from impact."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(
            ToolInput(project_dir=str(proj)),
            target="app/models/item.py",
            include_tests=False,
        )
        assert result.status == "success"
        assert not any("test" in n for n in (result.notes or []) if "tests/" in n)


def test_execution_time_recorded() -> None:
    """T-18: execution_time_ms is positive."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(
            ToolInput(project_dir=str(proj)),
            target="app/models/item.py",
        )
        assert result.execution_time_ms >= 0


def test_rel_helper_unix_slashes() -> None:
    """T-19: _rel returns forward-slash paths."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        child = root / "a" / "b.py"
        assert "/" in _rel(child, root)


def test_ms_helper_positive() -> None:
    """T-20: _ms returns a non-negative integer."""
    import time
    s = time.monotonic()
    result = _ms(s)
    assert isinstance(result, int)
    assert result >= 0


def test_next_steps_not_empty() -> None:
    """T-21: next_steps is populated on success."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(
            ToolInput(project_dir=str(proj)),
            target="app/models/item.py",
        )
        assert result.status == "success"
        assert result.next_steps


def test_notes_include_seed_count() -> None:
    """T-22: notes include 'Seeds analysed' information."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = blast_radius(
            ToolInput(project_dir=str(proj)),
            target="app/models/item.py",
        )
        assert any("Seeds" in n for n in (result.notes or []))


def test_depth_zero_only_seed() -> None:
    """T-23: depth=0 reports only the seed itself (no transitive hops)."""
    rev = {"a.py": {"b.py"}, "b.py": {"c.py"}}
    visited: dict[str, int] = {}
    _bfs("a.py", rev, max_depth=0, visited=visited)
    assert visited == {"a.py": 0}


def test_cycle_in_import_graph_handled() -> None:
    """T-24: Circular imports in project don't cause infinite loop."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "cyclic"
        proj.mkdir()
        (proj / "a.py").write_text("from b import foo\n")
        (proj / "b.py").write_text("from a import bar\n")
        graph = _build_import_graph(proj)
        # Should complete without hanging
        assert isinstance(graph, dict)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_on_missing_project,
        test_error_without_target_or_diff,
        test_success_with_target,
        test_dry_run_no_files,
        test_build_import_graph_non_empty,
        test_reverse_graph_inversion,
        test_bfs_depth_limit,
        test_bfs_visits_within_depth,
        test_bfs_no_cycle_infinite_loop,
        test_symbol_defs_collected,
        test_report_markdown_format,
        test_report_json_format,
        test_report_dot_format,
        test_report_no_production_impact,
        test_report_file_created_markdown,
        test_report_file_created_dot,
        test_include_tests_false,
        test_execution_time_recorded,
        test_rel_helper_unix_slashes,
        test_ms_helper_positive,
        test_next_steps_not_empty,
        test_notes_include_seed_count,
        test_depth_zero_only_seed,
        test_cycle_in_import_graph_handled,
    ]

    passed = failed = 0
    errors: list[str] = []
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            errors.append(f"{t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
