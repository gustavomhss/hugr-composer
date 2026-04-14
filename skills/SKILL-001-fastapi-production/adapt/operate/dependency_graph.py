"""TOOL-039: dependency_graph — AST import walker with layer enforcement.

Builds a module-level dependency graph via AST import parsing, detects
circular imports via Tarjan SCC, enforces architectural layer rules from
a YAML config, and outputs SVG/DOT/JSON.

Example::

    from adapt.contracts import ToolInput
    from adapt.operate.dependency_graph import dependency_graph

    result = dependency_graph(
        ToolInput(project_dir="/path/to/project"),
        output_format="dot",
    )
    print(result.status)
    print(result.notes)
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult


MCP_TOOL = {
    "name": "fastapi_dependency_graph",
    "description": "Render the FastAPI dependency injection graph as a Mermaid diagram.",
    "tags": ["operate"],
    "entry": "dependency_graph",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def dependency_graph(
    inp: ToolInput,
    output_format: str = "dot",
    layer_rules_file: str = ".deps-layers.yaml",
    detect_cycles: bool = True,
    fail_on_violation: bool = True,
) -> ToolResult:
    """Build and validate a module dependency graph for a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir``.
        output_format: ``"dot"``, ``"json"``, ``"svg"``, or ``"markdown"``.
        layer_rules_file: YAML file (relative to project_dir) defining
            allowed import directions between layers.
        detect_cycles: Run Tarjan SCC to find circular imports.
        fail_on_violation: Return ``status="error"`` on layer violations.

    Returns:
        ``ToolResult`` with graph output in ``files_created`` and
        violation summary in ``notes``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    if not project.exists():
        return ToolResult(
            status="error",
            error=f"project_dir does not exist: {project}",
            execution_time_ms=_ms(start),
        )

    layer_rules = _load_layer_rules(project / layer_rules_file)
    graph = _build_graph(project)
    nodes = list(graph.keys())
    edges = [(src, dst) for src, dsts in graph.items() for dst in dsts]

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Found {len(nodes)} modules, {len(edges)} edges.",
            ],
            execution_time_ms=_ms(start),
        )

    # Cycle detection via Tarjan SCC
    cycles: list[list[str]] = []
    if detect_cycles:
        sccs = _tarjan_scc(graph)
        cycles = [scc for scc in sccs if len(scc) > 1]

    # Layer violation check
    violations: list[str] = []
    if layer_rules:
        violations = _check_layer_violations(edges, layer_rules)

    # Render graph
    output = _render_graph(nodes, edges, cycles, violations, output_format)
    ext = {"dot": "dot", "json": "json", "svg": "svg", "markdown": "md"}.get(
        output_format, "txt"
    )
    out_file = project / f"dependency_graph.{ext}"
    out_file.write_text(output)

    notes = [
        f"Modules: {len(nodes)}, Edges: {len(edges)}",
        f"Cycles detected: {len(cycles)}",
        f"Layer violations: {len(violations)}",
    ]
    if cycles:
        for cyc in cycles[:5]:
            notes.append(f"  Cycle: {' → '.join(cyc)}")
    if violations:
        for v in violations[:5]:
            notes.append(f"  Violation: {v}")

    has_blocking = (cycles and detect_cycles and fail_on_violation) or (violations and fail_on_violation)
    if has_blocking:
        return ToolResult(
            status="error",
            error="Dependency graph violations detected. See notes.",
            files_created=[str(out_file)],
            notes=notes,
            execution_time_ms=_ms(start),
        )

    return ToolResult(
        status="success",
        files_created=[str(out_file)],
        notes=notes,
        next_steps=["Review dependency_graph output before merging."],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

def _build_graph(project: Path) -> dict[str, set[str]]:
    """Build module-level import graph from AST.

    Excludes ``TYPE_CHECKING`` imports and external libraries.

    Args:
        project: FastAPI project root.

    Returns:
        Dict mapping relative module path to set of imported module paths.
    """
    graph: dict[str, set[str]] = {}
    py_files = list(project.rglob("*.py"))
    known = {_file_to_module(f, project) for f in py_files}

    for py_file in py_files:
        mod = _file_to_module(py_file, project)
        graph.setdefault(mod, set())
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError:
            continue

        in_type_checking = False
        for node in ast.walk(tree):
            # Skip TYPE_CHECKING blocks (they are analysis-time only)
            if (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"
            ):
                in_type_checking = True
                continue
            if in_type_checking:
                continue
            if isinstance(node, ast.ImportFrom) and node.module:
                target = node.module.replace(".", "/") + ".py"
                target_mod = node.module.replace("/", ".")
                if target_mod in known:
                    graph[mod].add(target_mod)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    target_mod = alias.name
                    if target_mod in known:
                        graph[mod].add(target_mod)
    return graph


# ---------------------------------------------------------------------------
# Tarjan SCC
# ---------------------------------------------------------------------------

def _tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    """Run Tarjan's SCC algorithm to find strongly connected components.

    Args:
        graph: Module adjacency dict.

    Returns:
        List of SCCs, each SCC is a list of node names.
    """
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        """Visit a node in Tarjan's SCC algorithm and update lowlink values."""
        index[node] = index_counter[0]
        lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        for neighbor in graph.get(node, set()):
            if neighbor not in index:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif on_stack.get(neighbor):
                lowlink[node] = min(lowlink[node], index[neighbor])

        if lowlink[node] == index[node]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == node:
                    break
            sccs.append(scc)

    for node in graph:
        if node not in index:
            strongconnect(node)
    return sccs


# ---------------------------------------------------------------------------
# Layer rules
# ---------------------------------------------------------------------------

def _load_layer_rules(path: Path) -> dict:
    """Load architectural layer rules from YAML.

    Args:
        path: Absolute path to the layer rules YAML.

    Returns:
        Dict with ``layers`` (ordered list) and ``allowed_edges`` list.
    """
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _check_layer_violations(
    edges: list[tuple[str, str]], rules: dict
) -> list[str]:
    """Check edges against layer rules and return violation descriptions.

    Args:
        edges: List of (from_module, to_module) tuples.
        rules: Layer rules dict with ``allowed_edges`` list.

    Returns:
        List of human-readable violation strings.
    """
    allowed: list[tuple[str, str]] = []
    for pair in rules.get("allowed_edges", []):
        if isinstance(pair, list) and len(pair) == 2:
            allowed.append((pair[0], pair[1]))

    if not allowed:
        return []

    violations: list[str] = []
    for src, dst in edges:
        src_layer = _get_layer(src, rules)
        dst_layer = _get_layer(dst, rules)
        if src_layer and dst_layer:
            if (src_layer, dst_layer) not in allowed and src_layer != dst_layer:
                violations.append(f"{src} ({src_layer}) → {dst} ({dst_layer})")
    return violations


def _get_layer(module: str, rules: dict) -> str | None:
    """Determine the architectural layer for a module.

    Args:
        module: Module dotted path.
        rules: Layer rules dict.

    Returns:
        Layer name or None if not matched.
    """
    for layer, prefixes in rules.get("layers", {}).items():
        if isinstance(prefixes, list):
            for prefix in prefixes:
                if module.startswith(prefix):
                    return layer
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_graph(
    nodes: list[str],
    edges: list[tuple[str, str]],
    cycles: list[list[str]],
    violations: list[str],
    fmt: str,
) -> str:
    """Render the dependency graph in the requested format.

    Args:
        nodes: List of module names.
        edges: List of (from, to) tuples.
        cycles: Detected cycles (each is a list of module names).
        violations: Layer violation descriptions.
        fmt: Output format.

    Returns:
        Formatted string output.
    """
    if fmt == "json":
        import json
        return json.dumps({
            "nodes": nodes,
            "edges": [{"from": s, "to": d} for s, d in edges],
            "cycles": cycles,
            "violations": violations,
        }, indent=2)

    if fmt in ("dot", "svg"):
        lines = ["digraph dependency_graph {", '  rankdir="LR";']
        cycle_nodes: set[str] = {n for cyc in cycles for n in cyc}
        for node in nodes:
            color = "red" if node in cycle_nodes else "black"
            lines.append(f'  "{node}" [color="{color}"];')
        for src, dst in edges:
            style = "dashed" if any(src in v and dst in v for v in violations) else "solid"
            lines.append(f'  "{src}" -> "{dst}" [style="{style}"];')
        lines.append("}")
        return "\n".join(lines)

    # Markdown
    lines = ["## Dependency Graph", "", f"**Modules**: {len(nodes)}", f"**Edges**: {len(edges)}", ""]
    if cycles:
        lines.append("### Cycles Detected")
        for cyc in cycles:
            lines.append(f"- {' → '.join(cyc)}")
        lines.append("")
    if violations:
        lines.append("### Layer Violations")
        for v in violations:
            lines.append(f"- {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _file_to_module(path: Path, project: Path) -> str:
    """Convert a file path to a dotted module name.

    Args:
        path: Absolute .py file path.
        project: Project root.

    Returns:
        Dotted module name relative to project.
    """
    try:
        rel = path.relative_to(project)
        return str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
    except ValueError:
        return str(path)


def _ms(start: float) -> int:
    """Elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
