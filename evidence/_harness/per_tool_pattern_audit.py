"""Static audit: every `adapt/` tool follows the patterns required for its category.

PRODUCT §2 / CONTRACT §A / CLAUDE.md "Padrões obrigatórios para novas tools":

Core patterns (all tools):
    1. MCP_TOOL dict at module level
    2. entry function matching MCP_TOOL["entry"]
    8. elapsed_ms / execution_time_ms on return paths
    9. lazy imports (no fastapi/starlette at module top)

Write-path patterns (extend/ + evolve/ tools):
    3. validate_project_dir() — project boundary check
    4. ensure_prerequisites() — prereq scaffolding check
    5. dry_run path
    6. fingerprint / no_op short-circuit (idempotency)
    7. ast.parse() validation before success return (when emitting code)

Read-only patterns (operate/ + verify/ + proactive/):
    Only #1, #2, #8, #9 required. #3–#7 are irrelevant because the tool
    analyses a project, it does not mutate one.

This probe is STATIC — pure AST scan. Runtime idempotence is covered
by `generator_idempotence_matrix.json`. This probe attests the
STRUCTURAL invariants every tool is required to carry, per its
category.

Output (JSON to stdout):
    {
      "_meta": {...},
      "tools_scanned": <int>,
      "patterns": [...9 names...],
      "per_category_requirements": {...which patterns matter per category...},
      "per_tool": [
        {"tool": "adapt/.../add_X.py", "category": "extend", "patterns": {...bool...}, "missing_required": [...]}
      ],
      "summary": {
        "per_category": {category: {total, compliant, noncompliant, ...}}
        "overall_passed": <bool>
      }
    }

Exit 0 iff every tool matches its category's REQUIRED patterns.
"""
from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ADAPT_ROOT = REPO_ROOT / "skills" / "SKILL-001-fastapi-production" / "adapt"

PATTERN_NAMES = [
    "mcp_tool_dict",
    "entry_function",
    "validate_project_dir",
    "ensure_prerequisites",
    "dry_run_path",
    "fingerprint_noop",
    "ast_parse_validation",
    "elapsed_ms",
    "lazy_imports",
]

CORE_PATTERNS = {"mcp_tool_dict", "entry_function", "elapsed_ms", "lazy_imports"}
WRITE_PATTERNS = {"validate_project_dir", "ensure_prerequisites", "dry_run_path", "fingerprint_noop", "ast_parse_validation"}

CATEGORY_REQUIRED = {
    # extend/ emits Python code → full write stack including ast.parse validation
    "extend": CORE_PATTERNS | WRITE_PATTERNS,
    # evolve/ tools split: those that emit Python (`add_event_driven`, `add_i18n`,
    # `add_migration_data`, `generate_admin_panel`) require ast_parse_validation;
    # those that emit non-Python (TS SDKs in `generate_sdk`) drop it. The split
    # is per-tool via EVOLVE_NON_PYTHON_EMITTERS below; the category default
    # therefore includes ast_parse_validation as the strict baseline.
    # Codex v8 HIGH: prior global exemption was too broad.
    "evolve": CORE_PATTERNS | WRITE_PATTERNS,
    "operate": CORE_PATTERNS,   # read-only project analysers
    "verify":  CORE_PATTERNS,   # project verifiers
    "proactive": CORE_PATTERNS, # suggests; does not mutate
}

# Tools in evolve/ that emit non-Python output are exempt from ast_parse_validation.
# The exemption is per-tool, NOT per-category, so newcomers in evolve/ that DO
# emit Python are still held to the strict bar (ast_parse_validation required).
EVOLVE_NON_PYTHON_EMITTERS = {
    "generate_sdk",          # emits TypeScript / Go SDKs
    "generate_admin_panel",  # emits HTML/JS admin
}


def discover_tools() -> list[pathlib.Path]:
    """Return every `.py` file directly under adapt/ subdomains, excluding tests + __init__."""
    tools: list[pathlib.Path] = []
    for domain_dir in sorted(p for p in ADAPT_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if domain_dir.name in ("contracts",):
            # contracts/ is helper-code, not tools
            continue
        for sub in sorted(domain_dir.rglob("*.py")):
            if sub.name.startswith("test_") or sub.name == "__init__.py":
                continue
            if "__pycache__" in sub.parts:
                continue
            tools.append(sub)
    return tools


def _get_mcp_tool_dict(tree: ast.AST) -> dict | None:
    """Return the MCP_TOOL literal dict if present at module level, else None."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MCP_TOOL":
                    if isinstance(node.value, ast.Dict):
                        # Convert literal dict
                        out = {}
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant):
                                if isinstance(v, ast.Constant):
                                    out[k.value] = v.value
                                else:
                                    out[k.value] = "<expr>"
                        return out
    return None


def _function_names(tree: ast.AST) -> set[str]:
    return {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _calls_name(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == name:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == name:
                return True
    return False


def _references_text(tree: ast.AST, needle: str) -> bool:
    """Substring search on the unparsed source."""
    try:
        src = ast.unparse(tree)
    except Exception:
        return False
    return needle in src


def _has_fastapi_module_import(tree: ast.AST) -> bool:
    """True IF fastapi is imported at module top-level (bad — should be lazy)."""
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("fastapi") or alias.name.startswith("starlette"):
                    return True
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("fastapi") or mod.startswith("starlette"):
                return True
    return False


def _category_of(py: pathlib.Path) -> str:
    """adapt/<category>/... — the first path segment under adapt/ is the category."""
    rel = py.relative_to(ADAPT_ROOT)
    return rel.parts[0]


def audit_tool(py: pathlib.Path) -> dict:
    src = py.read_text()
    rel = str(py.relative_to(ADAPT_ROOT.parent))
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {"tool": rel, "category": _category_of(py), "parse_error": str(e), "patterns": {}, "missing_required": PATTERN_NAMES}

    mcp = _get_mcp_tool_dict(tree)
    entry_name = (mcp or {}).get("entry") if mcp else None
    fn_names = _function_names(tree)

    patterns: dict[str, bool] = {
        "mcp_tool_dict": mcp is not None,
        "entry_function": bool(entry_name) and entry_name in fn_names,
        "validate_project_dir": _calls_name(tree, "validate_project_dir"),
        "ensure_prerequisites": _calls_name(tree, "ensure_prerequisites"),
        "dry_run_path": _references_text(tree, "dry_run"),
        "fingerprint_noop": _references_text(tree, "no_op") or _references_text(tree, "fingerprint"),
        "ast_parse_validation": _calls_name(tree, "parse") and ("ast" in src),
        "elapsed_ms": _references_text(tree, "elapsed_ms") or _references_text(tree, "execution_time_ms"),
        "lazy_imports": not _has_fastapi_module_import(tree),
    }
    category = _category_of(py)
    required = set(CATEGORY_REQUIRED.get(category, CORE_PATTERNS))
    # Per-tool refinement: evolve/ non-Python emitters drop ast_parse_validation
    if category == "evolve" and py.stem in EVOLVE_NON_PYTHON_EMITTERS:
        required = required - {"ast_parse_validation"}
    missing_required = [n for n in sorted(required) if not patterns.get(n)]
    return {
        "tool": rel,
        "category": category,
        "patterns": patterns,
        "missing_required": missing_required,
    }


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def main() -> int:
    tools = discover_tools()
    per_tool = [audit_tool(p) for p in tools]

    per_category: dict[str, dict] = {}
    for t in per_tool:
        cat = t["category"]
        bucket = per_category.setdefault(cat, {
            "total": 0, "compliant": 0, "noncompliant_tools": [],
            "pattern_hits": {p: 0 for p in PATTERN_NAMES},
        })
        bucket["total"] += 1
        if not t.get("missing_required"):
            bucket["compliant"] += 1
        else:
            bucket["noncompliant_tools"].append({
                "tool": t["tool"],
                "missing_required": t["missing_required"],
            })
        for p, ok in t.get("patterns", {}).items():
            if ok:
                bucket["pattern_hits"][p] += 1

    for cat, bucket in per_category.items():
        bucket["compliance_rate_pct"] = round(bucket["compliant"] / bucket["total"] * 100, 2) if bucket["total"] else 0.0
        bucket["required_patterns"] = sorted(CATEGORY_REQUIRED.get(cat, CORE_PATTERNS))

    overall_passed = all(b["compliant"] == b["total"] for b in per_category.values())

    import datetime
    out = {
        "_meta": {
            "command": ".venv/bin/python evidence/_harness/per_tool_pattern_audit.py",
            "cwd": "repo root",
            "commit": _git("rev-parse", "HEAD"),
            "tree": _git("rev-parse", "HEAD^{tree}"),
            "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grading": "exit 0 iff every tool satisfies its category's REQUIRED patterns",
        },
        "tools_scanned": len(per_tool),
        "patterns": PATTERN_NAMES,
        "per_category_requirements": {cat: sorted(reqs) for cat, reqs in CATEGORY_REQUIRED.items()},
        "summary": {
            "overall_passed": overall_passed,
            "per_category": per_category,
        },
        "per_tool": per_tool,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
