#!/usr/bin/env python3
"""Classifier: rank extraction candidates by "real primitive" likelihood.

Reads `tools_latent_primitives.json` (produced by `audit_tools.py`) and
produces `primitive_candidates_ranked.json` — the same list augmented with:

- `signals`: booleans flagging route-handler / pydantic-model / test / trivial.
- `primitive_score`: integer; higher = more likely to be a reusable primitive.

Scoring is deliberately conservative so the top N produced by this classifier
is a high-precision extraction queue (few false positives). Low-scored items
are NOT deleted — they remain in the JSON for possible manual reclassification.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

_AUDIT_PATH = Path(__file__).resolve().parent / "tools_latent_primitives.json"
_OUT_PATH = Path(__file__).resolve().parent / "primitive_candidates_ranked.json"
_EXTEND_DIR = Path(__file__).resolve().parents[2] / "adapt" / "extend"


# Decorators that scream "this is an HTTP route handler, not a primitive".
_ROUTE_DECORATORS: frozenset[str] = frozenset({
    "get", "post", "put", "patch", "delete", "options", "head",
    "route", "api_route", "websocket", "include_router",
})

# Pydantic base classes (any of these as a base makes the class a DTO, not a primitive).
_PYDANTIC_BASES: frozenset[str] = frozenset({
    "BaseModel", "GenericModel", "BaseSettings", "RootModel",
})

# Non-primitive class hints — exceptions, protocols with no body, etc.
_TRIVIAL_BASE_EXCEPTIONS: frozenset[str] = frozenset({
    "Exception", "BaseException", "ValueError", "RuntimeError", "TypeError",
    "NotImplementedError", "LookupError", "KeyError",
})

# Domain-demo markers — names that strongly suggest tool-specific example code
# rather than a reusable primitive. Partial-match substrings, case-sensitive.
_DOMAIN_DEMO_SUBSTRINGS: tuple[str, ...] = (
    "Order", "Payment", "Invoice", "Subscription", "Checkout",
    "Customer", "Product", "Cart", "Inventory",
    "Post", "Comment", "Article", "Blog",
    "Task", "Todo", "Note",
    "Predictor", "Demo", "Example", "Sample",
)

# Exact-name allowlist: these LOOK demo-ish but ARE canonical primitives.
_DEMO_OVERRIDE_ALLOWLIST: frozenset[str] = frozenset({
    "TaskManager", "TaskRegistry", "TaskScheduler",  # long-running-task primitives
    "PaymentMethod", "PaymentIntent",                 # if extracted as interfaces
    "OrderEnvelope",                                  # generic envelope shape
})


def _is_domain_demo(name: str) -> bool:
    if name in _DEMO_OVERRIDE_ALLOWLIST:
        return False
    return any(sub in name for sub in _DOMAIN_DEMO_SUBSTRINGS)


def _decorator_names(decorators: list[ast.expr]) -> list[str]:
    names: list[str] = []
    for dec in decorators:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.append(dec.attr)
        elif isinstance(dec, ast.Call):
            target = dec.func
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, ast.Attribute):
                names.append(target.attr)
    return names


def _is_route_handler(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(d in _ROUTE_DECORATORS for d in _decorator_names(node.decorator_list))


def _is_pydantic_model(node: ast.AST) -> bool:
    if not isinstance(node, ast.ClassDef):
        return False
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in _PYDANTIC_BASES:
            return True
        if isinstance(base, ast.Attribute) and base.attr in _PYDANTIC_BASES:
            return True
    return False


def _is_trivial_exception(node: ast.AST) -> bool:
    if not isinstance(node, ast.ClassDef):
        return False
    if len(node.body) > 2:  # more than docstring + pass
        return False
    bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
    return bool(bases & _TRIVIAL_BASE_EXCEPTIONS)


def _method_count(node: ast.AST) -> int:
    if not isinstance(node, ast.ClassDef):
        return 0
    return sum(
        1 for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _branching_complexity(node: ast.AST) -> int:
    """Rough cyclomatic-ish count: If/For/While/Try/With/Match nodes."""
    n = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                              ast.Try, ast.With, ast.AsyncWith, ast.Match)):
            n += 1
    return n


def _has_docstring(node: ast.AST, min_chars: int = 20) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    ds = ast.get_docstring(node) or ""
    return len(ds) >= min_chars


def _name_blacklist(name: str) -> bool:
    """Obvious wrappers that are never primitives."""
    return name.startswith("add_") or name.startswith("_")


def _reparse_candidate(tool_rel: str, cand: dict[str, Any]) -> ast.AST | None:
    """Re-parse the ENTIRE tool file to locate the candidate's AST node so we can
    inspect decorators / bases / body (the audit JSON does not persist the AST)."""
    tool_path = _EXTEND_DIR / tool_rel
    try:
        tree = ast.parse(tool_path.read_text())
    except SyntaxError:
        return None
    import textwrap as _tw
    wanted = cand["name"]
    # Walk string constants; parse each; find the first matching def/class by name.
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                payload = _tw.dedent(child.value)
                try:
                    inner = ast.parse(payload)
                except SyntaxError:
                    continue
                for node in ast.walk(inner):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name == wanted:
                            return node
        # Also the tool-level nodes.
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if parent.name == wanted:
                return parent
    return None


def score_candidate(tool_rel: str, cand: dict[str, Any]) -> dict[str, Any]:
    node = _reparse_candidate(tool_rel, cand)
    signals: dict[str, bool] = {
        "is_route_handler": False,
        "is_pydantic_model": False,
        "is_trivial_exception": False,
        "is_blacklisted_name": _name_blacklist(cand["name"]),
        "is_domain_demo": _is_domain_demo(cand["name"]),
        "has_docstring": False,
    }
    complexity = 0
    method_count = 0
    if node is not None:
        signals["is_route_handler"] = _is_route_handler(node)
        signals["is_pydantic_model"] = _is_pydantic_model(node)
        signals["is_trivial_exception"] = _is_trivial_exception(node)
        signals["has_docstring"] = _has_docstring(node)
        complexity = _branching_complexity(node)
        method_count = _method_count(node)

    disqualified = any([
        signals["is_route_handler"],
        signals["is_pydantic_model"],
        signals["is_trivial_exception"],
        signals["is_blacklisted_name"],
        signals["is_domain_demo"],
    ])

    score = 0
    if not disqualified:
        size = cand["size_bytes"]
        score = size
        if cand["kind"] == "class":
            score *= max(1, method_count)
        score *= max(1, complexity)
        if signals["has_docstring"]:
            score *= 2
        # Classes dominate when both class and function would be viable.
        if cand["kind"] == "class":
            score *= 2

    return {
        **cand,
        "tool": tool_rel,
        "signals": signals,
        "method_count": method_count,
        "complexity": complexity,
        "disqualified": disqualified,
        "primitive_score": score,
    }


def run() -> list[dict[str, Any]]:
    report = json.loads(_AUDIT_PATH.read_text())
    ranked: list[dict[str, Any]] = []
    for tool_rel, info in report.items():
        for cand in info.get("candidates", []):
            ranked.append(score_candidate(tool_rel, cand))
    ranked.sort(key=lambda r: r["primitive_score"], reverse=True)
    return ranked


def summarize(ranked: list[dict[str, Any]]) -> None:
    qualifying = [r for r in ranked if not r["disqualified"]]
    route_n = sum(1 for r in ranked if r["signals"]["is_route_handler"])
    pyd_n = sum(1 for r in ranked if r["signals"]["is_pydantic_model"])
    trivial_n = sum(1 for r in ranked if r["signals"]["is_trivial_exception"])
    blacklist_n = sum(1 for r in ranked if r["signals"]["is_blacklisted_name"])
    demo_n = sum(1 for r in ranked if r["signals"].get("is_domain_demo"))

    print(f"Total candidates:           {len(ranked)}")
    print(f"Qualifying (primitive-like): {len(qualifying)}")
    print(f"Disqualified:")
    print(f"  route handlers:           {route_n}")
    print(f"  pydantic models:          {pyd_n}")
    print(f"  trivial exceptions:       {trivial_n}")
    print(f"  name blacklist (add_*):   {blacklist_n}")
    print(f"  domain demo names:        {demo_n}")
    print()
    print("Top-25 qualifying primitives (score • kind • name • tool):")
    for r in qualifying[:25]:
        print(f"  {r['primitive_score']:>12} • {r['kind']:<8} • "
              f"{r['name']:<30} • {r['tool']}")


if __name__ == "__main__":
    ranked = run()
    _OUT_PATH.write_text(json.dumps(ranked, indent=2))
    print(f"Wrote {_OUT_PATH}\n")
    summarize(ranked)
