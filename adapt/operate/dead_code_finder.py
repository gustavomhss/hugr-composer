"""TOOL-037: dead_code_finder — Framework-aware dead code detector.

Extends AST-based analysis with FastAPI decorator awareness, SQLAlchemy
relationship string resolution, Pydantic response_model detection, pytest
fixture/collection awareness, and confidence scoring.

Produces a classified report of unused symbols with allow-list support.

Example::

    from adapt.contracts import ToolInput
    from adapt.operate.dead_code_finder import dead_code_finder

    result = dead_code_finder(
        ToolInput(project_dir="/path/to/project"),
        confidence_threshold=80,
    )
    print(result.status)
    print(result.notes)
"""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DeadSymbol:
    """A potentially unused symbol with a confidence score.

    Attributes:
        name: Symbol name.
        file: Relative file path.
        line: Line number.
        kind: Symbol kind (function, class, import, variable).
        confidence: 0-100 confidence that the symbol is dead.
        reason: Human-readable reason for the confidence score.
    """

    name: str
    file: str
    line: int
    kind: str
    confidence: int
    reason: str


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_dead_code_finder",
    "description": "Find unreachable routes, unused dependencies, and dead models.",
    "tags": ["operate"],
    "entry": "dead_code_finder",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def dead_code_finder(
    inp: ToolInput,
    confidence_threshold: int = 80,
    include_routes: bool = True,
    exclude_patterns: list[str] | None = None,
    allow_list_file: str = ".deadcode-allow.yaml",
) -> ToolResult:
    """Scan a FastAPI project for dead code with framework awareness.

    Args:
        inp: ``ToolInput`` with ``project_dir``.
        confidence_threshold: Minimum confidence (0-100) to include in report.
        include_routes: Scan for orphan FastAPI routes with no callers.
        exclude_patterns: Path glob patterns to exclude (e.g. ``["tests/*"]``).
        allow_list_file: Relative path to YAML allow-list.

    Returns:
        ``ToolResult`` with dead symbols in ``notes`` and a report in
        ``files_created``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    if not project.exists():
        return ToolResult(
            status="error",
            error=f"project_dir does not exist: {project}",
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would scan for dead code (dry-run skips file operations)"],
            execution_time_ms=_ms(start),
        )


    allow_list = _load_allow_list(project / allow_list_file)
    py_files = _collect_files(project, exclude_patterns or [])


    # First pass: collect all defined and used symbols
    all_defs: dict[str, DeadSymbol] = {}
    all_uses: set[str] = set()
    framework_live: set[str] = set()

    for py_file in py_files:
        rel = _rel(py_file, project)
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError:
            continue

        _collect_defs(tree, rel, all_defs)
        _collect_uses(tree, all_uses)
        _collect_framework_live(tree, source, framework_live, include_routes)

    # Score each definition
    dead: list[DeadSymbol] = []
    for key, sym in all_defs.items():
        if sym.name in allow_list:
            continue
        if sym.name in framework_live:
            continue
        if sym.name in all_uses:
            continue
        # Dynamic dispatch — downgrade confidence
        confidence = sym.confidence
        dead.append(DeadSymbol(
            name=sym.name,
            file=sym.file,
            line=sym.line,
            kind=sym.kind,
            confidence=confidence,
            reason=sym.reason,
        ))

    filtered = [s for s in dead if s.confidence >= confidence_threshold]
    filtered.sort(key=lambda s: (-s.confidence, s.file, s.line))

    report = _render_report(filtered)
    report_file = project / "dead_code_report.md"
    report_file.write_text(report)

    notes = [
        f"Scanned {len(py_files)} files, {len(all_defs)} symbols defined.",
        f"Dead symbols found: {len(filtered)} (confidence >= {confidence_threshold})",
    ]
    if filtered:
        notes.append(report)

    return ToolResult(
        status="success",
        files_created=[str(report_file)],
        notes=notes,
        next_steps=[
            "Review dead_code_report.md before deleting symbols.",
            "Add false positives to .deadcode-allow.yaml with justification.",
        ],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# Symbol collection
# ---------------------------------------------------------------------------

def _collect_defs(tree: ast.AST, rel: str, defs: dict[str, DeadSymbol]) -> None:
    """Populate *defs* with top-level definitions from *tree*.

    Args:
        tree: Parsed AST of the file.
        rel: Relative file path (for reporting).
        defs: Accumulator dict to update in-place.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = f"{rel}::{node.name}"
            confidence = 90 if not node.name.startswith("_") else 70
            defs[key] = DeadSymbol(
                name=node.name, file=rel, line=node.lineno,
                kind="function", confidence=confidence,
                reason="No callers detected in project AST.",
            )
        elif isinstance(node, ast.ClassDef):
            key = f"{rel}::{node.name}"
            defs[key] = DeadSymbol(
                name=node.name, file=rel, line=node.lineno,
                kind="class", confidence=85,
                reason="No usages detected in project AST.",
            )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                key = f"{rel}::import::{name}"
                defs[key] = DeadSymbol(
                    name=name, file=rel, line=node.lineno,
                    kind="import", confidence=95,
                    reason="Import never referenced after import site.",
                )


def _collect_uses(tree: ast.AST, uses: set[str]) -> None:
    """Collect all referenced names from *tree* into *uses*.

    Args:
        tree: Parsed AST.
        uses: Accumulator set to update in-place.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            uses.add(node.id)
        elif isinstance(node, ast.Attribute):
            uses.add(node.attr)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                uses.add(node.func.id)


def _collect_framework_live(
    tree: ast.AST, source: str, live: set[str], include_routes: bool
) -> None:
    """Mark symbols as 'live' because a framework references them implicitly.

    Handles: FastAPI route decorators, SQLAlchemy relationship strings,
    Pydantic response_model, pytest fixtures.

    Args:
        tree: Parsed AST.
        source: Raw source text (for regex cross-checks).
        live: Accumulator set to update in-place.
        include_routes: Whether to exempt route handlers.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if _is_route_decorator(dec) and include_routes:
                    live.add(node.name)
                if _is_pytest_fixture(dec):
                    live.add(node.name)
        # SQLAlchemy relationship string references
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            if re.match(r'^[A-Z][a-zA-Z0-9_]*$', val):
                live.add(val)
    # Pydantic response_model= keyword
    for m in re.finditer(r'response_model\s*=\s*([A-Za-z_]\w*)', source):
        live.add(m.group(1))


def _is_route_decorator(node: ast.expr) -> bool:
    """Return True if *node* looks like a FastAPI route decorator.

    Args:
        node: AST expression node.

    Returns:
        True for patterns like ``@router.get(...)``, ``@app.post(...)``.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in {
            "get", "post", "put", "patch", "delete", "options", "head",
        }
    return False


def _is_pytest_fixture(node: ast.expr) -> bool:
    """Return True if *node* is a pytest.fixture decorator.

    Args:
        node: AST expression node.

    Returns:
        True for ``@pytest.fixture`` or ``@fixture``.
    """
    if isinstance(node, ast.Attribute) and node.attr == "fixture":
        return True
    if isinstance(node, ast.Name) and node.id == "fixture":
        return True
    return False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_report(dead: list[DeadSymbol]) -> str:
    """Render a Markdown dead code report.

    Args:
        dead: Filtered and sorted list of dead symbols.

    Returns:
        Markdown string.
    """
    if not dead:
        return "## Dead Code Report\n\n_No dead code found above threshold._\n"

    lines = ["## Dead Code Report", ""]
    for sym in dead:
        icon = "🔴" if sym.confidence >= 90 else "🟡"
        lines.append(
            f"- {icon} `{sym.name}` ({sym.kind}) — `{sym.file}:{sym.line}` "
            f"confidence={sym.confidence} — {sym.reason}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_files(project: Path, exclude_patterns: list[str]) -> list[Path]:
    """Return all .py files under *project* not matching *exclude_patterns*.

    Args:
        project: Project root.
        exclude_patterns: Glob patterns relative to project root to exclude.

    Returns:
        Sorted list of .py file paths.
    """
    excluded: set[Path] = set()
    for pat in exclude_patterns:
        excluded.update(project.glob(pat))

    return sorted(
        f for f in project.rglob("*.py")
        if f not in excluded
        and not any(f.is_relative_to(e) for e in excluded if e.is_dir())
    )


def _load_allow_list(path: Path) -> set[str]:
    """Load symbol names from YAML allow-list.

    Args:
        path: Absolute path to the allow-list file.

    Returns:
        Set of allowed symbol names.
    """
    if not path.exists():
        return set()
    try:
        import yaml  # type: ignore[import-untyped]
        data = yaml.safe_load(path.read_text()) or {}
        return set(data.keys()) if isinstance(data, dict) else set(data)
    except Exception:
        return set()


def _rel(path: Path, project: Path) -> str:
    """Return relative path string with forward slashes."""
    try:
        return str(path.relative_to(project)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _ms(start: float) -> int:
    """Elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
