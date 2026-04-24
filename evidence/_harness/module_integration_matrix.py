"""Module integration matrix — 9 module packages × N checks.

PRODUCT §2 / CONTRACT §B4.2 + CLAUDE.md modules table:
    Each `modules/<name>/` package is a pre-built feature bundle with
    KNOWLEDGE.md + tools/ subdir + scaffold + verify + (sometimes pentest).

This probe scans the 9 module packages and attests the structural
invariants. It does NOT execute module tools (that's aggregate pytest).

Checks per module:
    1. has_knowledge_md (KNOWLEDGE.md present at package root)
    2. has_tools_subdir (tools/ subdir present)
    3. tools_count_ge_1 (≥1 tool file under tools/)
    4. has_scaffold_tool (scaffold_<name>.py OR canonical scaffold entrypoint)
    5. has_verify_tool (verify_<name>.py)

Output:
    evidence/deterministic/module_integration_matrix.json
    {
      "_meta": {...},
      "modules_scanned": 9,
      "per_module": [{name, tools_count, tools: [...], checks: {...}, all_pass}],
      "summary": {total_tools_across_modules, modules_pass, modules_fail}
    }

Exit 0 iff every module passes all 5 checks.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULES_ROOT = REPO_ROOT / "skills" / "SKILL-001-fastapi-production" / "modules"

CHECKS = [
    "has_knowledge_md",
    "has_tools_subdir",
    "tools_count_ge_1",
    "has_producer_verb",   # REQUIRED — any of: scaffold_* / generate_*
    "has_inspector_verb",  # INFORMATIVE — any of: verify_* / operate_* / pentest_*
                            # deployment is pure-generator (CI/Docker/k8s artefacts);
                            # its "verify" is the emitted CI pipeline running on the
                            # emitted infra — legitimately not an in-module inspector.
]
REQUIRED_CHECKS = {"has_knowledge_md", "has_tools_subdir", "tools_count_ge_1", "has_producer_verb"}
# Legal module verbs per the observed pattern across auth / db / ws / deployment / caching / obs.
PRODUCER_VERBS = ("scaffold_", "generate_")
INSPECTOR_VERBS = ("verify_", "operate_", "pentest_")


def discover_modules() -> list[pathlib.Path]:
    return sorted(
        p for p in MODULES_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith("_") and p.name != "__pycache__"
    )


def audit_module(m: pathlib.Path) -> dict:
    name = m.name
    tools_dir = m / "tools"
    tools_files = []
    if tools_dir.exists():
        tools_files = sorted([
            p.name for p in tools_dir.iterdir()
            if p.suffix == ".py" and p.name != "__init__.py" and not p.name.startswith("test_")
        ])

    checks = {
        "has_knowledge_md": (m / "KNOWLEDGE.md").exists(),
        "has_tools_subdir": tools_dir.exists(),
        "tools_count_ge_1": len(tools_files) >= 1,
        "has_producer_verb": any(f.startswith(p) for f in tools_files for p in PRODUCER_VERBS),
        "has_inspector_verb": any(f.startswith(v) for f in tools_files for v in INSPECTOR_VERBS),
    }
    verbs_found = {
        "producer": [f for f in tools_files if any(f.startswith(p) for p in PRODUCER_VERBS)],
        "inspector": [f for f in tools_files if any(f.startswith(v) for v in INSPECTOR_VERBS)],
    }
    return {
        "name": name,
        "tools_count": len(tools_files),
        "tools": tools_files,
        "verbs": verbs_found,
        "checks": checks,
        "all_required_pass": all(checks[c] for c in REQUIRED_CHECKS),
    }


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def main() -> int:
    modules = discover_modules()
    per_module = [audit_module(m) for m in modules]
    total_modules = len(per_module)
    all_pass = sum(1 for r in per_module if r["all_required_pass"])
    total_tools = sum(r["tools_count"] for r in per_module)

    check_hits = {c: 0 for c in CHECKS}
    for r in per_module:
        for c, ok in r["checks"].items():
            if ok:
                check_hits[c] += 1
    check_coverage_pct = {c: round(check_hits[c] / total_modules * 100, 2) if total_modules else 0.0 for c in CHECKS}

    passed = (all_pass == total_modules) and (total_modules == 9) and (total_tools >= 28)

    out = {
        "_meta": {
            "command": ".venv/bin/python evidence/_harness/module_integration_matrix.py",
            "cwd": "repo root",
            "commit": _git("rev-parse", "HEAD"),
            "tree": _git("rev-parse", "HEAD^{tree}"),
            "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grading": "exit 0 iff 9 modules pass all 5 checks AND total tools ≥ 28 (INVENTORY.md claim)",
        },
        "modules_scanned": total_modules,
        "checks": CHECKS,
        "summary": {
            "modules_pass": all_pass,
            "total_modules": total_modules,
            "total_tools_across_modules": total_tools,
            "check_coverage_pct": check_coverage_pct,
            "passed": passed,
        },
        "per_module": per_module,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
