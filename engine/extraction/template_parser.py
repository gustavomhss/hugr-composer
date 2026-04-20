#!/usr/bin/env python3
"""Single source of truth for parsing embedded code out of EXTEND-tool templates.

The three downstream modules (audit_tools, classify, extract, wrap_shell)
previously each re-implemented their own walk of AST + string-template
parsing with subtle divergences (dedent yes/no, placeholder strip yes/no,
`ast.walk` vs `body`-only). Divergences meant a candidate surfaced by one
module could be invisible to another — a correctness hazard.

This module centralises:

  - `iter_embedded_modules(source)` — walk a tool's AST, yield every parseable
    embedded `ast.Module` (one per string literal that looks like code),
    alongside the outer `ast.Constant` node so callers can compute line offsets.
  - `find_top_level_def(module, name)` — deterministic first-top-level-match
    lookup; never descends into nested defs.
  - `extract_source_segment(source, node)` — return the ORIGINAL source
    slice for a node (preserves comments + formatting). Falls back to
    `ast.unparse` when `end_lineno` / `end_col_offset` are unavailable.
  - `strip_placeholders(source)` — context-aware f-string placeholder
    removal. Handles both identifier positions (`class {Name}:`) and
    expression positions.

Every other module in this package MUST go through these helpers.
"""

from __future__ import annotations

import ast
import re
import textwrap
from typing import Iterator


def strip_placeholders(src: str) -> str:
    """Replace f-string placeholders with safe Python tokens so the string parses.

    Protects doubled braces. Uses a context-aware substitution:
    in identifier positions (after `class `, `def `, `import `, `from `) the
    placeholder becomes an identifier literal; otherwise a string literal.
    """
    src = src.replace("{{", "\x00LB").replace("}}", "\x00RB")
    ident_ctx = re.compile(
        r"(?P<prefix>(?:class|def|async\s+def|import|from)\s+)\{[^{}\n]*\}"
    )
    src = ident_ctx.sub(r"\g<prefix>PLACEHOLDER_IDENT", src)
    src = re.sub(r"\{[^{}\n]*\}", '"PLACEHOLDER"', src)
    return src.replace("\x00LB", "{").replace("\x00RB", "}")


def iter_embedded_modules(source: str) -> Iterator[tuple[ast.Module, ast.Constant]]:
    """Yield `(parsed_module, containing_constant_node)` for every code-looking
    string literal in `source`. Deterministic ordering: AST walk order.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    seen: set[int] = set()
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                continue
            payload = child.value
            if len(payload) < 80 or "\n" not in payload:
                continue
            # Must contain a code shape anchor.
            if not any(
                line.lstrip().startswith(("def ", "async def ", "class "))
                for line in payload.splitlines()
            ):
                continue
            # Dedupe by object id (same Constant can be reached via multiple parents).
            cid = id(child)
            if cid in seen:
                continue
            seen.add(cid)
            dedented = textwrap.dedent(payload)
            try:
                embedded = ast.parse(dedented)
            except SyntaxError:
                stripped = strip_placeholders(dedented)
                try:
                    embedded = ast.parse(stripped)
                except SyntaxError:
                    continue
            yield embedded, child


def find_top_level_def(
    module: ast.Module, name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None:
    """Return the TOP-LEVEL (not nested) def/class named `name`, or None.

    Nested defs (a class's method with the same name as the class, or a
    helper function defined inside another function) are deliberately
    ignored — they are not independently extractable primitives.
    """
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return node
    return None


def iter_top_level_defs(
    module: ast.Module,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Iterate every top-level def/class in a module, in source order."""
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node


def extract_source_segment(module_source: str, node: ast.AST) -> str:
    """Return the literal source slice for `node`, preserving comments +
    original formatting. Falls back to `ast.unparse` when line/col info is
    incomplete (old pickles, synthetic nodes)."""
    if (getattr(node, "lineno", None) is None
            or getattr(node, "end_lineno", None) is None):
        return ast.unparse(node)
    try:
        segment = ast.get_source_segment(module_source, node)
        if segment:
            return segment
    except (ValueError, TypeError):
        pass
    return ast.unparse(node)


def find_all_top_level_matches(
    source: str, name: str,
) -> list[tuple[ast.AST, str]]:
    """Return every top-level `name`-defined node across ALL embedded modules
    in `source`. Each entry is (node, dedented_payload_the_node_came_from).

    Used by `extract.py` so when two templates in the same tool both define
    a class with the same name (e.g. two distinct `Middleware` shells), BOTH
    are surfaced rather than the first-match winning silently.
    """
    out: list[tuple[ast.AST, str]] = []
    # Tool-file top-level.
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in iter_top_level_defs(tree):
        if node.name == name:
            out.append((node, source))
    # String-template top-levels.
    for embedded, container in iter_embedded_modules(source):
        match = find_top_level_def(embedded, name)
        if match is not None:
            # Recover the dedented payload for source-segment extraction.
            out.append((match, textwrap.dedent(container.value)))
    return out
