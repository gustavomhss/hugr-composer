#!/usr/bin/env python3
"""Audit pass: enumerate latent primitives inside every `adapt/extend/add_*.py`.

Walks the EXTEND tool corpus and emits a per-tool list of top-level classes
and functions that are candidates for extraction into `core.venous.*`. This
is the first stage of the tool-decomposition pivot (see
`docs/PIVOT_TOOL_DECOMPOSITION.md`).

Output: `engine/extraction/tools_latent_primitives.json` — a dict keyed by
tool path with a list of candidate symbols each, suitable for the next
passes:
  - dedupe: cluster candidates by signature similarity (hash of normalized
    AST body) so "idempotency check" appearing in 30 tools collapses to 1.
  - priority: sort by (cross_tool_reuse_count × candidate_size_bytes).
  - extract: lift the top-N into `core/venous/<namespace>/<Name>/` with a
    minimal HuGR shell (Protocol + invariant_bindings + T0/T1/T7 gate).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from engine.extraction.template_parser import (
    extract_source_segment,
    iter_embedded_modules,
    iter_top_level_defs,
)

_EXTEND_DIR = Path(__file__).resolve().parents[2] / "adapt" / "extend"
_OUT_PATH = Path(__file__).resolve().parent / "tools_latent_primitives.json"

# Symbols that are MCP metadata or dispatch plumbing — not extraction candidates.
_SKIP_NAMES = frozenset(
    {
        "MCP_TOOL",
        "tool",
        "main",
        "_main",
        "__all__",
    }
)


def _docstring(node: ast.AST) -> str:
    ds = ast.get_docstring(node) or ""
    return ds.split("\n", 1)[0][:160].strip()


def _normalized_body_hash(node: ast.AST) -> str:
    """A shape hash using `ast.unparse`. Preserves statement order (critical:
    sorting lines would collapse unrelated code). Two functions with identical
    logic survive minor formatting differences; functions with the same line
    multiset but different order hash DIFFERENTLY (as they should)."""
    cleaned = ast.unparse(node)
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def _candidate(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, src: str
) -> dict[str, Any]:
    start = node.lineno
    end = getattr(node, "end_lineno", start)
    segment = extract_source_segment(src, node) or "\n".join(src.splitlines()[start - 1 : end])
    return {
        "name": node.name,
        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
        "line_start": start,
        "line_end": end,
        "size_bytes": len(segment.encode()),
        "size_lines": end - start + 1,
        "docstring": _docstring(node),
        "shape_hash": _normalized_body_hash(node),
        "is_async": isinstance(node, ast.AsyncFunctionDef),
    }


def _audit_tool(tool_path: Path) -> dict[str, Any]:
    """Audit ONE tool. EXTEND tools are MCP wrappers whose real primitives live
    INSIDE the triple-quoted string templates they emit into scaffolded
    projects. We walk the AST, find every `Constant(value=<str>)`, try to
    parse it as Python, and collect embedded ClassDef/FunctionDef nodes."""
    src = tool_path.read_text()
    try:
        tree = ast.parse(src, filename=str(tool_path))
    except SyntaxError as exc:
        return {"error": f"syntax: {exc}", "candidates": []}

    candidates: list[dict[str, Any]] = []

    # 1) Top-level defs in the tool file (rare — usually only `add_*`).
    for node in iter_top_level_defs(tree):
        if node.name in _SKIP_NAMES or node.name.startswith("_"):
            continue
        cand = _candidate(node, src)
        cand["origin"] = "tool_file"
        candidates.append(cand)

    # 2) Top-level defs inside every parseable string template. The shared
    #    `template_parser` guarantees identical parsing across pipeline stages.
    import textwrap as _tw

    for embedded, container in iter_embedded_modules(src):
        payload = _tw.dedent(container.value)
        for node in iter_top_level_defs(embedded):
            if node.name in _SKIP_NAMES:
                continue
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue
            cand = _candidate(node, payload)
            cand["origin"] = "string_template"
            cand["line_start"] += container.lineno - 1
            cand["line_end"] += container.lineno - 1
            candidates.append(cand)

    return {
        "size_bytes": len(src.encode()),
        "size_lines": src.count("\n") + 1,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def run() -> dict[str, Any]:
    report: dict[str, Any] = {}
    tool_paths = sorted(_EXTEND_DIR.rglob("add_*.py"))
    for p in tool_paths:
        rel = str(p.relative_to(_EXTEND_DIR))
        report[rel] = _audit_tool(p)
    return report


def dedupe_by_shape(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Cluster candidates across tools by `shape_hash`. Returns {hash: [occurrences]}."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for tool_rel, info in report.items():
        for cand in info.get("candidates", []):
            h = cand["shape_hash"]
            buckets.setdefault(h, []).append({"tool": tool_rel, **cand})
    return buckets


def summarize(report: dict[str, Any]) -> None:
    total_tools = len(report)
    total_candidates = sum(info.get("candidate_count", 0) for info in report.values())
    dedupe = dedupe_by_shape(report)
    unique_shapes = len(dedupe)
    multi_use_shapes = [h for h, occs in dedupe.items() if len(occs) >= 2]

    print(f"Tools scanned:           {total_tools}")
    print(f"Total candidates:        {total_candidates}")
    print(f"Unique shapes:           {unique_shapes}")
    print(f"Shapes reused ≥2 tools:  {len(multi_use_shapes)}")

    # Top-15 most-reused shapes by (occurrences × avg_size).
    ranked = sorted(
        dedupe.items(),
        key=lambda kv: len(kv[1]) * (sum(o["size_bytes"] for o in kv[1]) // max(1, len(kv[1]))),
        reverse=True,
    )
    print("\nTop-15 extraction candidates (shape_hash • reuse × avg_size_bytes • name sample):")
    for h, occs in ranked[:15]:
        avg_size = sum(o["size_bytes"] for o in occs) // len(occs)
        sample = occs[0]["name"]
        print(f"  {h} • {len(occs):>3}× × {avg_size:>5}B • {sample!r} in {len(occs)} tools")


if __name__ == "__main__":
    report = run()
    _OUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"Wrote {_OUT_PATH}")
    summarize(report)
