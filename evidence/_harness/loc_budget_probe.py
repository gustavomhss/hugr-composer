"""Measure LoC budget + primitive-import ratio across the 20 canonical examples.

PRODUCT §2 / §6.1 — "tools emit ≤20 LOC glue; logic lives in primitives."

This probe takes the PEDAGOGICAL examples under `/examples/` as the
reference for what idiomatic HuGR-style emitted code looks like. It is
NOT a direct measurement of "what tool X emitted in a specific fresh
scaffold" — that form of measurement lives in
`external-eval/single_shot_benchmark/` because it requires live LLM
invocation of the full tool chain.

What this probe reports per example:
- `app_loc`: source-lines-of-code in `app.py` (excludes blanks + comment-only lines).
- `test_loc`: same for `test_app.py`.
- `handlers`: count of `def` functions in `app.py`.
- `app_loc_per_handler`: `app_loc / max(handlers, 1)`.
- `venous_imports`: count of `from core.venous` imports in `app.py`.
  (High ratio = logic lives in primitives. Zero = stand-alone
  pedagogical implementation; examples are intentionally self-
  contained for readability.)

Aggregate statistics reported:
- p50 / p95 / max of `app_loc_per_handler` across all 20 examples.

Exit 0 always — the probe publishes the distribution as a dashboard
input. Binding-or-not judgement is Gustavo's in EVIDENCE.md §2.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES_ROOT = REPO_ROOT / "examples"


def count_sloc(py: pathlib.Path) -> int:
    """Source lines: non-blank and not purely comment. Rough but stable."""
    sloc = 0
    for raw in py.read_text().splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        sloc += 1
    return sloc


def count_handlers(py: pathlib.Path) -> int:
    tree = ast.parse(py.read_text())
    return sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


def count_venous_imports(py: pathlib.Path) -> int:
    tree = ast.parse(py.read_text())
    hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("core.venous") or mod.startswith("venous"):
                hits += 1
    return hits


def main() -> int:
    per_example: list[dict] = []
    for ex_dir in sorted(p for p in EXAMPLES_ROOT.iterdir() if p.is_dir() and p.name[0:2].isdigit()):
        app_py = ex_dir / "app.py"
        test_py = ex_dir / "test_app.py"
        if not app_py.exists():
            continue
        app_loc = count_sloc(app_py)
        test_loc = count_sloc(test_py) if test_py.exists() else 0
        handlers = count_handlers(app_py)
        venous = count_venous_imports(app_py)
        per_example.append({
            "name": ex_dir.name,
            "app_loc": app_loc,
            "test_loc": test_loc,
            "handlers": handlers,
            "app_loc_per_handler": round(app_loc / max(handlers, 1), 2),
            "venous_imports": venous,
        })

    per_handler = sorted(e["app_loc_per_handler"] for e in per_example)
    n = len(per_handler)
    def pct(q: float) -> float:
        if n == 0:
            return 0.0
        idx = max(0, min(n - 1, int(round((n - 1) * q))))
        return per_handler[idx]

    summary = {
        "examples_scanned": n,
        "app_loc_per_handler": {
            "p50": pct(0.50),
            "p95": pct(0.95),
            "max": max(per_handler) if per_handler else 0.0,
            "min": min(per_handler) if per_handler else 0.0,
        },
        "total_handlers": sum(e["handlers"] for e in per_example),
        "total_app_loc": sum(e["app_loc"] for e in per_example),
        "total_venous_imports": sum(e["venous_imports"] for e in per_example),
        "note": (
            "Examples are PEDAGOGICAL reference implementations — "
            "self-contained for readability, not direct proof of "
            "generator-emitted glue. Fresh-emit LoC is measured in "
            "external-eval/single_shot_benchmark/ per LAUNCH.md §2.0."
        ),
    }

    out = {"summary": summary, "per_example": per_example}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
