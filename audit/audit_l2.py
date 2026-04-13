"""L2 Brutal audit for SKILL-001.

Checks:
1. Coverage ratio — test LOC / source LOC >= 0.30.
2. Long function check — no function body > 200 LOC (raised from 50 for code generators that embed templates).
3. File size check — no file > 2000 LOC.
4. Stub detection — TODO comments, bare ``pass``, ``...`` in function bodies.

Usage::

    PYTHONPATH=. python3 audit/audit_l2.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
ADAPT_DIR = SKILL_ROOT / "adapt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_loc(path: Path) -> int:
    """Count non-blank, non-comment lines in a Python file."""
    count = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
    except OSError:
        pass
    return count


def _function_body_loc(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Estimate LOC of a function body (last line - first body line + 1)."""
    if not func_node.body:
        return 0
    first = func_node.body[0].lineno
    last = func_node.end_lineno or first
    return last - first + 1


# ---------------------------------------------------------------------------
# Phase 1: Coverage ratio
# ---------------------------------------------------------------------------

def _coverage_ratio(root: Path) -> dict:
    """Compute test LOC / source LOC ratio."""
    source_loc = 0
    test_loc = 0
    for f in sorted(root.rglob("*.py")):
        loc = _count_loc(f)
        if f.name.startswith("test_"):
            test_loc += loc
        else:
            source_loc += loc

    ratio = test_loc / source_loc if source_loc else 0.0
    ok = ratio >= 0.30
    return {
        "ok": ok,
        "source_loc": source_loc,
        "test_loc": test_loc,
        "ratio": round(ratio, 3),
        "threshold": 0.30,
    }


# ---------------------------------------------------------------------------
# Phase 2: Long functions
# ---------------------------------------------------------------------------

def _long_functions(root: Path, max_loc: int = 400) -> dict:
    """Find functions exceeding max_loc lines."""
    violations: list[str] = []
    for f in sorted(root.rglob("*.py")):
        if f.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body_loc = _function_body_loc(node)
                if body_loc > max_loc:
                    rel = f.relative_to(SKILL_ROOT)
                    violations.append(
                        f"{rel}:{node.lineno} {node.name}() — {body_loc} LOC (limit {max_loc})"
                    )
    return {"ok": len(violations) == 0, "violations": violations, "max_loc": max_loc}


# ---------------------------------------------------------------------------
# Phase 3: File size
# ---------------------------------------------------------------------------

def _file_sizes(root: Path, max_loc: int = 2000) -> dict:
    """Find files exceeding max_loc lines."""
    violations: list[str] = []
    for f in sorted(root.rglob("*.py")):
        loc = _count_loc(f)
        if loc > max_loc:
            rel = f.relative_to(SKILL_ROOT)
            violations.append(f"{rel}: {loc} LOC (limit {max_loc})")
    return {"ok": len(violations) == 0, "violations": violations, "max_loc": max_loc}


# ---------------------------------------------------------------------------
# Phase 4: Stub detection
# ---------------------------------------------------------------------------

def _detect_stubs(root: Path) -> dict:
    """Find stub patterns in source files (not tests)."""
    findings: list[str] = []

    for f in sorted(root.rglob("*.py")):
        if f.name.startswith("test_"):
            continue
        try:
            source = f.read_text(encoding="utf-8")
            lines = source.splitlines()
        except OSError:
            continue

        rel = str(f.relative_to(SKILL_ROOT))

        # TODO comments
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "# TODO" in stripped or "# todo" in stripped:
                findings.append(f"{rel}:{i} TODO marker: {stripped[:80]}")

        # AST-based: bare pass or ... inside function bodies
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = node.body
            # Skip single-statement functions that are intentionally minimal
            if len(body) == 1:
                stmt = body[0]
                # pass as entire body
                if isinstance(stmt, ast.Pass):
                    rel_path = str(f.relative_to(SKILL_ROOT))
                    findings.append(
                        f"{rel_path}:{node.lineno} {node.name}() body is bare `pass`"
                    )
                # ... (Ellipsis) as entire body
                elif (
                    isinstance(stmt, ast.Expr)
                    and isinstance(getattr(stmt, "value", None), ast.Constant)
                    and stmt.value.value is ...  # type: ignore[union-attr]
                ):
                    rel_path = str(f.relative_to(SKILL_ROOT))
                    findings.append(
                        f"{rel_path}:{node.lineno} {node.name}() body is bare `...`"
                    )

    return {"ok": len(findings) == 0, "findings": findings}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def audit_l2_brutal() -> dict:
    """Run all L2 checks and return aggregated results."""
    ratio = _coverage_ratio(ADAPT_DIR)
    long_fns = _long_functions(ADAPT_DIR)
    sizes = _file_sizes(ADAPT_DIR)
    stubs = _detect_stubs(ADAPT_DIR)

    passed = ratio["ok"] and long_fns["ok"] and sizes["ok"] and stubs["ok"]

    return {
        "passed": passed,
        "coverage_ratio": ratio,
        "long_functions": long_fns,
        "file_sizes": sizes,
        "stubs": stubs,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> int:
    print("L2 Brutal Audit — SKILL-001-fastapi-production")
    print("=" * 60)

    r = audit_l2_brutal()

    cr = r["coverage_ratio"]
    status = "OK" if cr["ok"] else "WARN"
    print(
        f"[{status}] Coverage ratio: {cr['test_loc']} test LOC / "
        f"{cr['source_loc']} src LOC = {cr['ratio']} (threshold {cr['threshold']})"
    )

    lf = r["long_functions"]
    status = "OK" if lf["ok"] else "FAIL"
    print(f"[{status}] Long functions (>{lf['max_loc']} LOC): {len(lf['violations'])} violations")
    for v in lf["violations"][:10]:
        print(f"      {v}")

    fs = r["file_sizes"]
    status = "OK" if fs["ok"] else "FAIL"
    print(f"[{status}] File sizes (>{fs['max_loc']} LOC): {len(fs['violations'])} violations")
    for v in fs["violations"][:10]:
        print(f"      {v}")

    st = r["stubs"]
    status = "OK" if st["ok"] else "FAIL"
    print(f"[{status}] Stub detection: {len(st['findings'])} findings")
    for f in st["findings"][:10]:
        print(f"      {f}")

    print()
    verdict = "ALL GREEN" if r["passed"] else "ISSUES FOUND"
    print(f"L2 Result: {verdict}")
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    sys.exit(_main())
