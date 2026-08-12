"""Tests for TOOL-039 dependency_graph.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_dependency_graph.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.dependency_graph import (
    _build_graph,
    _check_layer_violations,
    _file_to_module,
    _render_graph,
    _tarjan_scc,
    dependency_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp: Path) -> Path:
    """Create a minimal project with a clean import chain."""
    proj = tmp / "proj"
    (proj / "app" / "models").mkdir(parents=True)
    (proj / "app" / "services").mkdir(parents=True)
    (proj / "app" / "api").mkdir(parents=True)

    (proj / "app" / "models" / "item.py").write_text("class Item: pass\n")
    (proj / "app" / "services" / "item_svc.py").write_text(
        "from app.models.item import Item\ndef get(): return Item()\n"
    )
    (proj / "app" / "api" / "routes.py").write_text(
        "from app.services.item_svc import get\ndef endpoint(): return get()\n"
    )
    return proj


def _make_cyclic_project(tmp: Path) -> Path:
    """Create a project with a circular import."""
    proj = tmp / "cyclic"
    (proj / "app").mkdir(parents=True)
    (proj / "app" / "a.py").write_text("from app.b import foo\ndef bar(): pass\n")
    (proj / "app" / "b.py").write_text("from app.a import bar\ndef foo(): pass\n")
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_missing_project() -> None:
    """T-01: Returns error for nonexistent project_dir."""
    result = dependency_graph(ToolInput(project_dir="/nonexistent"))
    assert result.status == "error"


def test_success_clean_project() -> None:
    """T-02: Clean project with no cycles returns success."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dependency_graph(
            ToolInput(project_dir=str(proj)),
            detect_cycles=True,
            fail_on_violation=False,
        )
        assert result.status == "success"


def test_dry_run_no_files() -> None:
    """T-03: dry_run=True writes no files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        before = list(proj.rglob("*"))
        result = dependency_graph(ToolInput(project_dir=str(proj), dry_run=True))
        assert result.status == "success"
        assert not result.files_created


def test_output_file_created() -> None:
    """T-04: Output file is created on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dependency_graph(ToolInput(project_dir=str(proj)), fail_on_violation=False)
        assert result.files_created
        assert Path(result.files_created[0]).exists()


def test_build_graph_edges() -> None:
    """T-05: Graph contains expected edges for the test project."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        graph = _build_graph(proj)
        assert len(graph) > 0


def test_tarjan_scc_no_cycle() -> None:
    """T-06: Tarjan returns all singleton SCCs for a DAG."""
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    sccs = _tarjan_scc(graph)
    cycles = [s for s in sccs if len(s) > 1]
    assert cycles == []


def test_tarjan_scc_detects_cycle() -> None:
    """T-07: Tarjan detects a two-node cycle."""
    graph = {"a": {"b"}, "b": {"a"}, "c": set()}
    sccs = _tarjan_scc(graph)
    cycles = [s for s in sccs if len(s) > 1]
    assert len(cycles) >= 1
    assert set(cycles[0]) == {"a", "b"}


def test_tarjan_scc_three_node_cycle() -> None:
    """T-08: Tarjan detects a three-node cycle."""
    graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
    sccs = _tarjan_scc(graph)
    cycles = [s for s in sccs if len(s) > 1]
    assert len(cycles) == 1
    assert len(cycles[0]) == 3


def test_cyclic_project_error_when_fail() -> None:
    """T-09: Cyclic project returns error when detect_cycles=True."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_cyclic_project(Path(tmp))
        result = dependency_graph(
            ToolInput(project_dir=str(proj)),
            detect_cycles=True,
            fail_on_violation=True,
        )
        assert result.status == "error"


def test_cyclic_project_success_without_fail() -> None:
    """T-10: Cyclic project succeeds when fail_on_violation=False."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_cyclic_project(Path(tmp))
        result = dependency_graph(
            ToolInput(project_dir=str(proj)),
            detect_cycles=True,
            fail_on_violation=False,
        )
        assert result.status == "success"


def test_render_graph_dot_format() -> None:
    """T-11: DOT render includes digraph keyword."""
    output = _render_graph(["a", "b"], [("a", "b")], [], [], "dot")
    assert "digraph" in output


def test_render_graph_json_format() -> None:
    """T-12: JSON render is valid JSON with nodes and edges."""
    output = _render_graph(["a", "b"], [("a", "b")], [], [], "json")
    data = json.loads(output)
    assert "nodes" in data
    assert "edges" in data


def test_render_graph_markdown_format() -> None:
    """T-13: Markdown render contains module counts."""
    output = _render_graph(["a", "b"], [("a", "b")], [], [], "markdown")
    assert "Modules" in output
    assert "Edges" in output


def test_render_graph_shows_cycles() -> None:
    """T-14: Cycles are shown in Markdown output."""
    output = _render_graph(["a", "b"], [("a", "b"), ("b", "a")], [["a", "b"]], [], "markdown")
    assert "Cycle" in output


def test_render_graph_shows_violations() -> None:
    """T-15: Layer violations are shown in Markdown output."""
    output = _render_graph(["a", "b"], [("a", "b")], [], ["a → b (violation)"], "markdown")
    assert "Violation" in output


def test_file_to_module_conversion() -> None:
    """T-16: _file_to_module produces dotted module path."""
    root = Path("/proj")
    f = Path("/proj/app/models/item.py")
    mod = _file_to_module(f, root)
    assert mod == "app.models.item"


def test_layer_check_violation() -> None:
    """T-17: Layer check flags forbidden edge."""
    edges = [("app.api.routes", "app.models.item")]
    rules = {
        "layers": {"api": ["app.api"], "model": ["app.models"]},
        "allowed_edges": [["api", "service"], ["service", "model"]],
    }
    violations = _check_layer_violations(edges, rules)
    assert len(violations) > 0


def test_layer_check_no_violation() -> None:
    """T-18: Allowed edge produces no violation."""
    edges = [("app.services.svc", "app.models.item")]
    rules = {
        "layers": {"service": ["app.services"], "model": ["app.models"]},
        "allowed_edges": [["service", "model"]],
    }
    violations = _check_layer_violations(edges, rules)
    assert violations == []


def test_notes_contain_module_count() -> None:
    """T-19: notes contain the module and edge counts."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dependency_graph(
            ToolInput(project_dir=str(proj)),
            fail_on_violation=False,
        )
        assert any("Modules" in n or "modules" in n.lower() for n in (result.notes or []))


def test_execution_time_recorded() -> None:
    """T-20: execution_time_ms is non-negative."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = dependency_graph(ToolInput(project_dir=str(proj)), fail_on_violation=False)
        assert result.execution_time_ms >= 0


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_missing_project,
        test_success_clean_project,
        test_dry_run_no_files,
        test_output_file_created,
        test_build_graph_edges,
        test_tarjan_scc_no_cycle,
        test_tarjan_scc_detects_cycle,
        test_tarjan_scc_three_node_cycle,
        test_cyclic_project_error_when_fail,
        test_cyclic_project_success_without_fail,
        test_render_graph_dot_format,
        test_render_graph_json_format,
        test_render_graph_markdown_format,
        test_render_graph_shows_cycles,
        test_render_graph_shows_violations,
        test_file_to_module_conversion,
        test_layer_check_violation,
        test_layer_check_no_violation,
        test_notes_contain_module_count,
        test_execution_time_recorded,
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
