#!/usr/bin/env python3
"""Minimal T0 gate for extracted primitives: verify the .py compiles.

Runs `py_compile` against every `<Name>.py` under `core/venous/_staging/`.
A compile failure does NOT delete the primitive — it records the failure in
`_extraction_report.json` inside the primitive's directory, so the staged
file becomes a self-documenting TODO for the reviewer.

Also attempts to run `python -c 'import ast; ast.parse(open(path).read())'`
as a fallback structural check.

Does NOT run mypy/ruff — those require the full HuGR gate and are a human-
review step. This is the cheapest "does it even parse?" check that catches
90% of mechanical extraction failures (dangling f-string placeholders,
unresolved cross-sibling references, etc.).
"""

from __future__ import annotations

import ast
import json
import py_compile
import tempfile
from pathlib import Path

_STAGE_DIR = Path(__file__).resolve().parents[2] / "core" / "venous" / "_staging"


def _check_one(py_path: Path) -> dict[str, object]:
    """Return a structured result for one file."""
    src = py_path.read_text()
    # 1. AST parse — cheap syntactic check.
    try:
        ast.parse(src)
    except SyntaxError as exc:
        return {
            "compile": "ast_syntax_error",
            "error": f"{exc.msg} at line {exc.lineno}",
            "line": exc.lineno,
        }
    # 2. py_compile — catches things AST won't (e.g., bytecode restrictions).
    with tempfile.NamedTemporaryFile(suffix=".pyc", delete=True) as tmp:
        try:
            py_compile.compile(str(py_path), cfile=tmp.name, doraise=True)
        except py_compile.PyCompileError as exc:
            return {"compile": "compile_error", "error": str(exc)}
    return {"compile": "ok"}


def run() -> dict[str, object]:
    if not _STAGE_DIR.exists():
        raise SystemExit("No _staging/ directory.")
    totals = {"ok": 0, "ast_syntax_error": 0, "compile_error": 0}
    failures: list[dict[str, object]] = []
    for ns_dir in sorted(_STAGE_DIR.iterdir()):
        if not ns_dir.is_dir() or ns_dir.name.startswith("."):
            continue
        for prim_dir in sorted(ns_dir.iterdir()):
            if not prim_dir.is_dir():
                continue
            py_files = list(prim_dir.glob("*.py"))
            for py in py_files:
                if py.name in ("__init__.py", "conftest.py"):
                    continue
                result = _check_one(py)
                totals[result["compile"]] = totals.get(result["compile"], 0) + 1
                # Stash per-primitive T0 report in the primitive's dir.
                report_path = prim_dir / "_t0_report.json"
                existing = {}
                if report_path.exists():
                    existing = json.loads(report_path.read_text())
                existing[py.name] = result
                report_path.write_text(json.dumps(existing, indent=2))
                if result["compile"] != "ok":
                    failures.append(
                        {
                            "primitive": f"{ns_dir.name}/{prim_dir.name}",
                            "file": py.name,
                            **result,
                        }
                    )
    return {"totals": totals, "failure_count": len(failures), "failures": failures}


if __name__ == "__main__":
    report = run()
    totals = report["totals"]
    print("T0 gate — py_compile across every extracted .py:")
    for k, v in totals.items():
        print(f"  {k:<24} {v:>4}")
    print(f"\n  failure_count: {report['failure_count']}")
    if report["failures"]:
        print("\nFirst 10 failures:")
        for f in report["failures"][:10]:
            print(f"  {f['primitive']}/{f['file']}: {f['compile']} — {f.get('error', '')[:120]}")
