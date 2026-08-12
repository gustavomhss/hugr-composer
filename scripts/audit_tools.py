#!/usr/bin/env python3
"""Comprehensive audit of all adapt tools against 8 quality criteria.

Criteria:
1. MCP_TOOL dict at module level with required fields (name, description, tags, entry, imports_primitives, imports_adapters)
2. ToolInput/ToolResult usage (Pydantic contracts)
3. ensure_prerequisites() call
4. dry_run support (returns before write)
5. elapsed_ms on EVERY return path
6. ast.parse validation loop before success return
7. Idempotency fingerprint check
8. Has test_add_X.py AND test_add_X_behavior.py

Discovery rules:
- Only modules that DEFINE MCP_TOOL are tools (excludes library modules like contracts/*.py)
- Test files (test_*.py) are never tools
- contracts/, _base/, conftest.py are infrastructure, not tools
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ADAPT_DIR = Path(__file__).parent.parent / "adapt"

# ---------------------------------------------------------------------------
# Discovery: find every module that defines MCP_TOOL (this is the definition of "tool")
# ---------------------------------------------------------------------------

def defines_mcp_tool(path: Path) -> bool:
    """Return True if the module assigns to a module-level MCP_TOOL name."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MCP_TOOL":
                    return True
    return False


def discover_tools():
    """Return list of (tool_path, category, name, sub_category) for every real tool."""
    tools = []

    # --- extend/<sub_category>/<add_*>/__init__.py ---
    for init in sorted(ADAPT_DIR.glob("extend/*/add_*/__init__.py")):
        sub_cat = init.parent.parent.name  # e.g. api_design
        name = init.parent.name            # e.g. add_api_versioning
        if defines_mcp_tool(init):
            tools.append((init, "extend", name, sub_cat))

    # --- evolve/<name>/__init__.py ---
    for init in sorted(ADAPT_DIR.glob("evolve/*/__init__.py")):
        name = init.parent.name
        if name != "__init__" and defines_mcp_tool(init):
            tools.append((init, "evolve", name, "evolve"))

    # --- verify/<name>/__init__.py ---
    for init in sorted(ADAPT_DIR.glob("verify/*/__init__.py")):
        name = init.parent.name
        if name != "__init__" and defines_mcp_tool(init):
            tools.append((init, "verify", name, "verify"))

    # --- operate/<name>.py (single-file tools, NOT test_*.py) ---
    for py in sorted(ADAPT_DIR.glob("operate/*.py")):
        if py.name == "__init__.py" or py.name.startswith("test_"):
            continue
        if defines_mcp_tool(py):
            tools.append((py, "operate", py.stem, "operate"))

    # --- proactive/<name>.py (NOT test_*.py, NOT __impl*) ---
    for py in sorted(ADAPT_DIR.glob("proactive/*.py")):
        if py.name == "__init__.py" or py.name.startswith("test_") or "__impl" in py.name:
            continue
        if defines_mcp_tool(py):
            tools.append((py, "proactive", py.stem, "proactive"))

    return tools


# ---------------------------------------------------------------------------
# Criterion checks
# ---------------------------------------------------------------------------

def get_mcp_tool_dict(tree: ast.AST) -> set[str]:
    """Return the set of keys in the MCP_TOOL dict (if any)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MCP_TOOL":
                    if isinstance(node.value, ast.Dict):
                        keys = set()
                        for k in node.value.keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                keys.add(k.value)
                        return keys
    return set()


def check_mcp_tool_fields(tree: ast.AST) -> tuple[bool, bool, list[str]]:
    """Check MCP_TOOL has required fields. Returns (has_all_6, has_base_4, issues)."""
    all_required = {"name", "description", "tags", "entry", "imports_primitives", "imports_adapters"}
    base_required = {"name", "description", "tags", "entry"}
    keys = get_mcp_tool_dict(tree)

    if not keys:
        return False, False, ["MCP_TOOL not found or not a dict"]

    missing_all = all_required - keys
    missing_base = base_required - keys

    issues = []
    if missing_base:
        issues.append(f"Missing base fields: {', '.join(sorted(missing_base))}")
    if missing_all - missing_base:
        issues.append(f"Missing extended fields: {', '.join(sorted(missing_all - missing_base))}")

    return (len(missing_all) == 0, len(missing_base) == 0, issues)


def check_toolinput_toolresult(tree: ast.AST) -> tuple[bool, bool, bool]:
    """Check ToolInput/ToolResult import and usage in signatures."""
    imports_input = False
    imports_result = False
    used_in_signature = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "ToolInput":
                    imports_input = True
                if alias.name == "ToolResult":
                    imports_result = True
        if isinstance(node, ast.FunctionDef):
            if node.returns and "ToolResult" in ast.dump(node.returns):
                used_in_signature = True
            for arg in node.args.args:
                if arg.annotation and "ToolInput" in ast.dump(arg.annotation):
                    used_in_signature = True

    return imports_input, imports_result, used_in_signature


def check_ensure_prerequisites(tree: ast.AST) -> bool:
    """Check if ensure_prerequisites is called anywhere."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "ensure_prerequisites":
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == "ensure_prerequisites":
                return True
    return False


def check_dry_run(tree: ast.AST, source: str) -> tuple[bool, str]:
    """Check for dry_run guard with early return (before any write)."""
    has_dry_run_ref = "dry_run" in source
    has_early_return = False

    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_str = ast.dump(node.test)
            if "dry_run" in test_str:
                for child in ast.walk(node):
                    if isinstance(child, ast.Return):
                        has_early_return = True
                        break

    if has_dry_run_ref and has_early_return:
        return True, "dry_run guard + early return"
    elif has_dry_run_ref:
        return True, "dry_run referenced (no early return detected)"
    return False, "no dry_run"


def get_entry_function_name(tree: ast.AST) -> str | None:
    """Get the entry function name from MCP_TOOL['entry']."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MCP_TOOL":
                    if isinstance(node.value, ast.Dict):
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and k.value == "entry":
                                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                                    return v.value
    return None


def check_elapsed_ms_all_returns(tree: ast.AST, source: str) -> tuple[bool, int, int]:
    """Check that EVERY return in the MAIN entry function sets execution_time_ms.

    Helper functions (prefixed with _) are excluded — only the tool's public
    entry point must cover all its return paths with elapsed time.
    """
    lines = source.split('\n')
    entry_name = get_entry_function_name(tree)

    # Find the entry function
    entry_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == entry_name:
            entry_func = node
            break

    if entry_func is None:
        # Fallback: check all non-helper functions
        return _check_all_funcs_returns(tree, source)

    # Collect direct returns in the entry function (not nested defs)
    returns = []
    for child in entry_func.body:
        _collect_returns(child, returns, skip_nested=True)

    total_returns = len(returns)
    ms_returns = 0

    for ret in returns:
        if ret.value is None:
            ms_returns += 1  # bare return doesn't need ms
            continue
        ret_str = ast.dump(ret.value)
        if "execution_time_ms" in ret_str or "_ms(" in ret_str:
            ms_returns += 1
        elif ret.lineno:
            start = max(0, ret.lineno - 8)
            end = min(len(lines), ret.lineno + 2)
            context = '\n'.join(lines[start:end])
            if "execution_time_ms" in context or "_ms(" in context or "_elapsed_ms(" in context:
                ms_returns += 1

    if total_returns == 0:
        return True, 0, 0
    return ms_returns >= total_returns, ms_returns, total_returns


def _collect_returns(node: ast.AST, returns: list, skip_nested: bool = False):
    """Collect Return nodes, optionally skipping nested function bodies."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Return):
            returns.append(child)
        elif skip_nested and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        else:
            _collect_returns(child, returns, skip_nested)


def _check_all_funcs_returns(tree: ast.AST, source: str) -> tuple[bool, int, int]:
    """Fallback: check all non-helper functions."""
    lines = source.split('\n')
    helper_funcs = {"_ms", "_elapsed_ms", "validate_project_dir"}
    total_returns = 0
    ms_returns = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name not in helper_funcs:
            for child in _iter_direct_returns(node):
                if child.value is not None:
                    total_returns += 1
                    ret_str = ast.dump(child.value)
                    if "execution_time_ms" in ret_str or "_ms(" in ret_str:
                        ms_returns += 1
                    elif child.lineno:
                        start = max(0, child.lineno - 8)
                        end = min(len(lines), child.lineno + 2)
                        context = '\n'.join(lines[start:end])
                        if "execution_time_ms" in context or "_ms(" in context:
                            ms_returns += 1

    if total_returns == 0:
        return True, 0, 0
    return ms_returns >= total_returns, ms_returns, total_returns


def _iter_direct_returns(func: ast.FunctionDef):
    """Yield direct return statements in a function body (not nested defs)."""
    for child in func.body:
        yield from _collect_returns_gen(child, skip_nested=True)


def _collect_returns_gen(node: ast.AST, skip_nested: bool = False):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Return):
            yield child
        elif skip_nested and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        else:
            yield from _collect_returns_gen(child, skip_nested)


def check_ast_validation(tree: ast.AST) -> bool:
    """Check if ast.parse is used for validation."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "parse":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "ast":
                    return True
            if isinstance(node.func, ast.Name) and node.func.id == "parse":
                return True
    return False


def check_idempotency(tree: ast.AST, source: str) -> tuple[bool, bool, str]:
    """Check for idempotency: no_op return + fingerprint/existence guard."""
    has_no_op = False
    has_guard = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            if "no_op" in ast.dump(node.value):
                has_no_op = True
            # Also check string in the return
            if isinstance(node.value, ast.Call):
                for kw in node.value.keywords:
                    if kw.arg == "status" and isinstance(kw.value, ast.Constant):
                        if kw.value.value == "no_op":
                            has_no_op = True

    patterns = [
        r"fingerprint", r"already_present", r"already_exist", r"already_enabled",
        r"already_added", r"already_configured", r"already installed",
        r"idempoten", r"no_op",
        r"\.exists\(\)", r"is_file\(\)", r"is_dir\(\)",
    ]
    for pat in patterns:
        if re.search(pat, source, re.IGNORECASE):
            has_guard = True
            break

    return has_no_op, has_guard, f"no_op={has_no_op}, guard={has_guard}"


def check_tests(name: str, sub_cat: str, category: str) -> tuple[bool, bool]:
    """Check for unit test and behavior test files."""
    if category == "extend":
        # Tests live in extend/<sub_cat>/test_add_*.py
        cat_dir = ADAPT_DIR / "extend" / sub_cat
        unit = (cat_dir / f"test_{name}.py").exists()
        behavior = (cat_dir / f"test_{name}_behavior.py").exists()
        return unit, behavior
    else:
        cat_dir = ADAPT_DIR / category
        unit = (cat_dir / f"test_{name}.py").exists()
        behavior = (cat_dir / f"test_{name}_behavior.py").exists()
        return unit, behavior


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------

def audit_tool(path: Path, category: str, name: str, sub_cat: str) -> dict:
    """Audit a single tool against all 8 criteria."""
    result = {
        "path": str(path),
        "category": category,
        "name": name,
        "sub_category": sub_cat,
        "criteria": {},
        "score": 0,
        "issues": [],
    }

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as e:
        result["issues"].append(f"Parse error: {e}")
        return result

    # 1. MCP_TOOL with all 6 fields
    has_all_6, has_base_4, mcp_issues = check_mcp_tool_fields(tree)
    result["criteria"]["mcp_tool_all6"] = has_all_6
    result["criteria"]["mcp_tool_base4"] = has_base_4
    if not has_all_6:
        result["issues"].append(f"MCP_TOOL: {'; '.join(mcp_issues)}")
    result["score"] += int(has_all_6)

    # 2. ToolInput/ToolResult usage
    imp_in, imp_ret, used_sig = check_toolinput_toolresult(tree)
    uses_contracts = imp_in or imp_ret or used_sig
    result["criteria"]["toolinput_toolresult"] = uses_contracts
    if not uses_contracts:
        result["issues"].append("No ToolInput/ToolResult usage")
    result["score"] += int(uses_contracts)

    # 3. ensure_prerequisites
    has_prereq = check_ensure_prerequisites(tree)
    result["criteria"]["ensure_prerequisites"] = has_prereq
    if not has_prereq:
        result["issues"].append("No ensure_prerequisites() call")
    result["score"] += int(has_prereq)

    # 4. dry_run support
    has_dry_run, dry_run_note = check_dry_run(tree, source)
    result["criteria"]["dry_run"] = has_dry_run
    if not has_dry_run:
        result["issues"].append(f"No dry_run support ({dry_run_note})")
    result["score"] += int(has_dry_run)

    # 5. elapsed_ms on every return
    ms_ok, ms_count, total_ret = check_elapsed_ms_all_returns(tree, source)
    result["criteria"]["elapsed_ms_all_returns"] = ms_ok
    result["criteria"]["_ms_detail"] = f"{ms_count}/{total_ret}"
    if not ms_ok:
        result["issues"].append(f"elapsed_ms incomplete ({ms_count}/{total_ret} returns)")
    result["score"] += int(ms_ok)

    # 6. ast.parse validation
    has_ast = check_ast_validation(tree)
    result["criteria"]["ast_parse"] = has_ast
    if not has_ast:
        result["issues"].append("No ast.parse validation loop")
    result["score"] += int(has_ast)

    # 7. Idempotency
    has_no_op, has_guard, idem_note = check_idempotency(tree, source)
    is_idempotent = has_no_op and has_guard
    result["criteria"]["idempotency"] = is_idempotent
    result["criteria"]["idempotency_no_op"] = has_no_op
    result["criteria"]["idempotency_guard"] = has_guard
    if not is_idempotent:
        result["issues"].append(f"No idempotency ({idem_note})")
    result["score"] += int(is_idempotent)

    # 8. Tests
    unit_test, behavior_test = check_tests(name, sub_cat, category)
    has_both = unit_test and behavior_test
    result["criteria"]["unit_test"] = unit_test
    result["criteria"]["behavior_test"] = behavior_test
    result["criteria"]["both_tests"] = has_both
    if not has_both:
        missing = []
        if not unit_test:
            missing.append("unit test")
        if not behavior_test:
            missing.append("behavior test")
        result["issues"].append(f"Missing: {', '.join(missing)}")
    result["score"] += int(has_both)

    return result


def short_path(path_str: str) -> str:
    return path_str.replace(str(ADAPT_DIR) + "/", "")


def main():
    tools = discover_tools()

    print(f"Discovered {len(tools)} tools (modules that define MCP_TOOL)")
    print()

    # Audit each tool
    results = []
    for path, cat, name, sub_cat in tools:
        r = audit_tool(path, cat, name, sub_cat)
        results.append(r)

    # Classify
    sota = [r for r in results if r["score"] == 8]
    ok = [r for r in results if 6 <= r["score"] <= 7]
    gap = [r for r in results if r["score"] < 6]

    print("=" * 72)
    print("AUDIT SUMMARY")
    print("=" * 72)
    print(f"Total tools audited:    {len(results)}")
    print(f"SOTA (8/8):             {len(sota)}")
    print(f"OK (6-7/8):             {len(ok)}")
    print(f"GAP (<6/8):             {len(gap)}")
    print()

    # Score distribution
    print("Score distribution:")
    for score in range(9):
        count = sum(1 for r in results if r["score"] == score)
        if count > 0:
            print(f"  {score}/8: {count:3d} tool(s)")
    print()

    # By sub-domain
    print("Score by sub-domain:")
    by_domain = {}
    for r in results:
        key = f"{r['category']}/{r['sub_category']}" if r['category'] == "extend" else r['category']
        by_domain.setdefault(key, []).append(r["score"])

    for domain in sorted(by_domain):
        scores = by_domain[domain]
        avg = sum(scores) / len(scores)
        sota_c = sum(1 for s in scores if s == 8)
        gap_c = sum(1 for s in scores if s < 6)
        bar = "▓" * int(avg) + "░" * (8 - int(avg))
        print(f"  {domain:40s}  n={len(scores):3d}  avg={avg:.1f}/8  {bar}  sota={sota_c}  gap={gap_c}")
    print()

    # Criterion-level stats
    print("=" * 72)
    print("CRITERION-LEVEL STATS")
    print("=" * 72)
    criteria_names = [
        ("mcp_tool_all6", "MCP_TOOL dict (all 6 fields)"),
        ("mcp_tool_base4", "MCP_TOOL dict (base 4 fields)"),
        ("toolinput_toolresult", "ToolInput/ToolResult usage"),
        ("ensure_prerequisites", "ensure_prerequisites() call"),
        ("dry_run", "dry_run support"),
        ("elapsed_ms_all_returns", "elapsed_ms on ALL returns"),
        ("ast_parse", "ast.parse validation loop"),
        ("idempotency", "Idempotency (no_op + guard)"),
        ("both_tests", "Unit + behavior tests"),
    ]
    for key, label in criteria_names:
        passing = sum(1 for r in results if r["criteria"].get(key, False))
        pct = 100 * passing / len(results) if results else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  {label:40s} {passing:3d}/{len(results):3d} {bar} {pct:5.1f}%")
    print()

    # Top 10 tools needing work
    print("=" * 72)
    print("TOP 10 TOOLS NEEDING WORK (lowest scores)")
    print("=" * 72)
    gap_sorted = sorted(results, key=lambda r: (r["score"], r["name"]))
    for i, r in enumerate(gap_sorted[:10], 1):
        sp = short_path(r["path"])
        print(f"  {i:2d}. [{r['score']}/8] {r['name']:45s}  {sp}")
        for issue in r["issues"]:
            print(f"       ✗ {issue}")
        print()

    # SOTA list
    if sota:
        print("=" * 72)
        print(f"SOTA TOOLS ({len(sota)} total)")
        print("=" * 72)
        for r in sota:
            print(f"  ✓ {r['name']:45s}  {short_path(r['path'])}")
        print()

    # OK list summary
    if ok:
        print(f"OK TOOLS ({len(ok)} total — scores 6-7)")
        print("-" * 72)
        for r in sorted(ok, key=lambda x: -x["score"]):
            sp = short_path(r["path"])
            missing = [k for k, v in r["criteria"].items()
                       if k.startswith("mcp_tool") or k in (
                           "toolinput_toolresult", "ensure_prerequisites", "dry_run",
                           "elapsed_ms_all_returns", "ast_parse", "idempotency", "both_tests")
                       and not v and k not in ("mcp_tool_all6", "idempotency_no_op", "idempotency_guard",
                                                "unit_test", "behavior_test", "mcp_tool_base4")]
            detail = f"(missing: {', '.join(missing[:3])})" if missing else ""
            print(f"  [{r['score']}/8] {r['name']:45s}  {detail}")
        print()

    # ALL GAP TOOLS
    if gap:
        print("=" * 72)
        print(f"ALL GAP TOOLS ({len(gap)} total — scores <6)")
        print("=" * 72)
        for r in sorted(gap, key=lambda x: (x["score"], x["name"])):
            sp = short_path(r["path"])
            print(f"  [{r['score']}/8] {r['name']:45s}  {sp}")
        print()

    # Detailed breakdown for worst tools
    print("=" * 72)
    print("DETAILED BREAKDOWN — WORST 15 GAP TOOLS")
    print("=" * 72)
    detail_keys = [
        ("mcp_tool_all6", "MCP_TOOL all 6"),
        ("toolinput_toolresult", "ToolInput/ToolResult"),
        ("ensure_prerequisites", "ensure_prerequisites"),
        ("dry_run", "dry_run"),
        ("elapsed_ms_all_returns", "elapsed_ms all"),
        ("ast_parse", "ast.parse"),
        ("idempotency", "idempotency"),
        ("both_tests", "tests"),
    ]
    for r in sorted(gap, key=lambda x: x["score"])[:15]:
        sp = short_path(r["path"])
        print(f"\n  {r['name']} [{r['score']}/8] — {sp}")
        for key, label in detail_keys:
            status = "✓" if r["criteria"].get(key, False) else "✗"
            print(f"    {status} {label}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
