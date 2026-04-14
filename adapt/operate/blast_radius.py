"""TOOL-035: blast_radius — AST reverse-dependency graph for FastAPI projects.

Walks the project's import/call graph to answer: "what else breaks if this
change ships?"  Supports git-diff mode, depth-limited traversal, FK-aware
model relationships, and DOT/JSON/Markdown output.

Example::

    from adapt.contracts import ToolInput
    from adapt.operate.blast_radius import blast_radius

    result = blast_radius(
        ToolInput(project_dir="/path/to/project"),
        target="app/models/item.py::Item",
        output_format="markdown",
        depth=3,
    )
    print(result.status)
    print(result.notes)
"""

from __future__ import annotations

import ast
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from adapt.contracts import ToolInput, ToolResult


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def blast_radius(
    inp: ToolInput,
    target: str = "",
    diff_ref: str | None = None,
    depth: int = 3,
    include_tests: bool = True,
    output_format: str = "markdown",
) -> ToolResult:
    """Compute the blast radius of a change target in a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        target: Symbol to analyse, e.g. ``app/models/item.py::Item`` or a
            file path.  When empty and ``diff_ref`` is set the diff targets
            are discovered automatically.
        diff_ref: Git ref to diff HEAD against (e.g. ``"origin/main"``).
            When provided, ``target`` is ignored and all changed symbols are
            used as seeds.
        depth: Maximum transitive depth to traverse (default 3).
        include_tests: Include test files in the impact report.
        output_format: ``"markdown"``, ``"json"``, or ``"dot"``.

    Returns:
        ``ToolResult`` with ``notes`` containing the formatted report and
        ``files_created`` listing any written report file.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    if not project.exists():
        return ToolResult(
            status="error",
            error=f"project_dir does not exist: {project}",
            execution_time_ms=_ms(start),
        )

    # Build import graph (with on-disk cache for speed — INV-BR-03)
    # Skip cache writes during dry_run to avoid modifying the project dir
    graph = _build_import_graph(project) if inp.dry_run else _build_import_graph_cached(project)
    reverse = _build_reverse_graph(graph)
    symbol_defs = _collect_symbol_defs(project)

    # Augment graph with route → handler edges (INV-BR-05)
    route_edges = _map_routes(project)
    for route_file, handler_file in route_edges:
        graph.setdefault(route_file, set()).add(handler_file)
        reverse.setdefault(handler_file, set()).add(route_file)

    # Resolve seeds
    if diff_ref:
        seeds = _symbols_from_diff(project, diff_ref, symbol_defs)
    elif target:
        seeds = [target]
    else:
        return ToolResult(
            status="error",
            error="Provide 'target' or 'diff_ref'.",
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[f"[dry_run] Would analyse seeds: {seeds}"],
            execution_time_ms=_ms(start),
        )

    # Walk reverse graph up to depth
    all_impacted: dict[str, int] = {}
    for seed in seeds:
        _bfs(seed, reverse, depth, all_impacted)

    # Separate tests from production
    tests = {k: v for k, v in all_impacted.items() if "test" in k}
    production = {k: v for k, v in all_impacted.items() if "test" not in k}
    if not include_tests:
        tests = {}

    report = _render_report(seeds, production, tests, output_format)
    files_created: list[str] = []

    if output_format in ("markdown", "dot", "json"):
        ext = {"markdown": "md", "dot": "dot", "json": "json"}[output_format]
        report_file = project / f"blast_radius_report.{ext}"
        report_file.write_text(report)
        files_created.append(str(report_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            f"Seeds analysed: {len(seeds)}",
            f"Production impacted: {len(production)} files",
            f"Tests impacted: {len(tests)} files",
            report,
        ],
        next_steps=["Review the report before merging the change."],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

_GRAPH_CACHE_FILE = ".blast_radius_cache.json"


def _build_import_graph_cached(project: Path) -> dict[str, set[str]]:
    """Build import graph, reusing an on-disk cache when no file has changed.

    Cache is stored in ``<project>/.blast_radius_cache.json`` as a JSON
    object with ``mtimes`` (file → mtime float) and ``graph`` (file →
    list of imported files).  When all mtimes match the cache is returned
    directly without re-parsing any AST.  (INV-BR-03)

    Args:
        project: Root of the FastAPI project.

    Returns:
        Dict mapping relative file paths to the set of relative paths they
        import within the project.
    """
    cache_path = project / _GRAPH_CACHE_FILE
    py_files = sorted(project.rglob("*.py"))

    # Compute current mtimes
    current_mtimes: dict[str, float] = {
        _rel(f, project): f.stat().st_mtime for f in py_files
    }

    # Try to load existing cache
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("mtimes") == current_mtimes:
                return {k: set(v) for k, v in cached["graph"].items()}
        except Exception:
            pass  # Cache unreadable — rebuild

    # Build fresh graph
    graph = _build_import_graph(project)

    # Persist to cache
    try:
        cache_path.write_text(
            json.dumps(
                {
                    "mtimes": current_mtimes,
                    "graph": {k: sorted(v) for k, v in graph.items()},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass  # Non-fatal: cache write failure just means next run rebuilds

    return graph


def _map_routes(project: Path) -> list[tuple[str, str]]:
    """Map URL routes to their handler source files via subprocess inspection.

    Imports ``app.main:app`` in a subprocess to list ``app.routes``, then
    maps each route's endpoint function back to its source file using
    ``inspect.getfile``.  Returns a list of ``(route_file, handler_file)``
    relative-path pairs so callers can add them as graph edges.  (INV-BR-05)

    Args:
        project: Root of the FastAPI project.

    Returns:
        List of ``(route_relative_path, handler_relative_path)`` tuples.
        Returns an empty list if the import fails or the app cannot be loaded.
    """
    script = (
        "import json, inspect, sys\n"
        "sys.path.insert(0, '.')\n"
        "try:\n"
        "    from app.main import app\n"
        "    edges = []\n"
        "    for route in getattr(app, 'routes', []):\n"
        "        ep = getattr(route, 'endpoint', None)\n"
        "        if ep is None:\n"
        "            continue\n"
        "        try:\n"
        "            src = inspect.getfile(ep)\n"
        "            edges.append(src)\n"
        "        except (TypeError, OSError):\n"
        "            pass\n"
        "    print(json.dumps(edges))\n"
        "except Exception as exc:\n"
        "    print(json.dumps([]))\n"
    )
    try:
        out = subprocess.check_output(
            ["python", "-c", script],
            cwd=str(project),
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).decode().strip()
        handler_abs_paths: list[str] = json.loads(out)
    except Exception:
        return []

    edges: list[tuple[str, str]] = []
    # Use a synthetic "routes" node for route-level edges
    routes_rel = "app/api/routes/__init__.py"
    for abs_path in handler_abs_paths:
        try:
            handler_rel = _rel(Path(abs_path), project)
        except Exception:
            continue
        edges.append((routes_rel, handler_rel))
    return edges


def _build_import_graph(project: Path) -> dict[str, set[str]]:
    """Return mapping file -> set of files it imports (project-internal only).

    Args:
        project: Root of the FastAPI project.

    Returns:
        Dict mapping relative file paths to the set of relative paths they
        import within the project.
    """
    graph: dict[str, set[str]] = {}
    py_files = list(project.rglob("*.py"))
    rel_stems = {_rel(f, project): f for f in py_files}

    for py_file in py_files:
        rel = _rel(py_file, project)
        graph.setdefault(rel, set())
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod_path = node.module.replace(".", "/") + ".py"
                if mod_path in rel_stems:
                    graph[rel].add(mod_path)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod_path = alias.name.replace(".", "/") + ".py"
                    if mod_path in rel_stems:
                        graph[rel].add(mod_path)
    return graph


def _build_reverse_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    """Invert the import graph to get reverse dependencies.

    Args:
        graph: Forward import graph (file -> files it imports).

    Returns:
        Reverse graph (file -> files that import it).
    """
    reverse: dict[str, set[str]] = {}
    for importer, imports in graph.items():
        for imported in imports:
            reverse.setdefault(imported, set()).add(importer)
    return reverse


def _collect_symbol_defs(project: Path) -> dict[str, str]:
    """Map ``file::ClassName`` to relative file path.

    Args:
        project: Project root.

    Returns:
        Dict of ``"relative/path.py::Symbol"`` to ``"relative/path.py"``.
    """
    defs: dict[str, str] = {}
    for py_file in project.rglob("*.py"):
        rel = _rel(py_file, project)
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs[f"{rel}::{node.name}"] = rel
    return defs


def _symbols_from_diff(
    project: Path, diff_ref: str, symbol_defs: dict[str, str]
) -> list[str]:
    """Return changed symbols from ``git diff diff_ref``.

    Args:
        project: Project root.
        diff_ref: Git ref to compare HEAD against.
        symbol_defs: Known symbol locations.

    Returns:
        List of changed file paths (or symbol keys if determinable).
    """
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", diff_ref, "HEAD"],
            cwd=str(project),
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode()
    except Exception:
        return []
    changed: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if line.endswith(".py"):
            changed.append(line)
    return changed


# ---------------------------------------------------------------------------
# BFS traversal
# ---------------------------------------------------------------------------

def _bfs(
    seed: str,
    reverse: dict[str, set[str]],
    max_depth: int,
    visited: dict[str, int],
) -> None:
    """BFS from *seed* up to *max_depth* hops in the reverse graph.

    Args:
        seed: Starting node (relative file path or symbol key).
        reverse: Reverse import graph.
        max_depth: Maximum hops.
        visited: Accumulator mapping node -> depth reached.
    """
    # Normalize: strip ::Symbol suffix for graph lookup
    file_seed = seed.split("::")[0] if "::" in seed else seed
    queue: list[tuple[str, int]] = [(file_seed, 0)]
    seen: set[str] = {file_seed}
    while queue:
        node, depth = queue.pop(0)
        if depth > max_depth:
            continue
        visited[node] = min(visited.get(node, max_depth + 1), depth)
        if depth < max_depth:
            for neighbor in reverse.get(node, set()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, depth + 1))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_report(
    seeds: list[str],
    production: dict[str, int],
    tests: dict[str, int],
    fmt: str,
) -> str:
    """Render the impact report in the requested format.

    Args:
        seeds: Change seeds.
        production: Production files and their traversal depth.
        tests: Test files and their traversal depth.
        fmt: Output format (``"markdown"``, ``"json"``, ``"dot"``).

    Returns:
        Formatted string report.
    """
    if fmt == "json":
        import json
        return json.dumps(
            {"seeds": seeds, "production": production, "tests": tests}, indent=2
        )
    if fmt == "dot":
        lines = ["digraph blast_radius {"]
        for node in {**production, **tests}:
            label = node.replace("/", "\\n")
            lines.append(f'  "{node}" [label="{label}"];')
        for seed in seeds:
            for node in production:
                lines.append(f'  "{seed}" -> "{node}";')
        lines.append("}")
        return "\n".join(lines)
    # Default: Markdown
    lines = [
        "## Blast Radius Report",
        "",
        f"**Seeds**: {', '.join(seeds)}",
        "",
        "### Production Impact",
    ]
    if production:
        for f, d in sorted(production.items(), key=lambda x: x[1]):
            lines.append(f"- `{f}` (depth {d})")
    else:
        lines.append("_No production files impacted._")
    lines += ["", "### Test Impact"]
    if tests:
        for f, d in sorted(tests.items(), key=lambda x: x[1]):
            lines.append(f"- `{f}` (depth {d})")
    else:
        lines.append("_No test files impacted._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _rel(path: Path, project: Path) -> str:
    """Return path relative to project as a string, with forward slashes."""
    try:
        return str(path.relative_to(project)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _ms(start: float) -> int:
    """Elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
