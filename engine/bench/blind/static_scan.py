"""Layer-E static scan — automatic failure-mode detection on emitted code.

Every spec can declare a `judge/static_scan.yaml` with rules of the form:

    rules:
      - id: used_float_for_money
        description: "Transfer handler uses float instead of Decimal/int cents"
        pattern_any_of:
          - {kind: "ast_call_name", name: "float"}
          - {kind: "source_regex", regex: "amount: *float"}
        scope: "glob:**/transfers/**.py"
        severity: fail

Scanner returns `StaticScanResult` with per-rule verdicts. Rules with
severity=fail contribute a synthetic test_E_static__<rule_id> outcome.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StaticFinding:
    rule_id: str
    severity: str  # "fail" | "warn"
    verdict: str  # "triggered" (bad) | "clean"
    matches: list[str]
    description: str


def run_static_scan(workdir: Path, rules_yaml: Path | None) -> list[StaticFinding]:
    if rules_yaml is None or not rules_yaml.exists():
        return []
    import yaml as _yaml

    cfg = _yaml.safe_load(rules_yaml.read_text(encoding="utf-8")) or {}
    rules = cfg.get("rules", []) or []
    out: list[StaticFinding] = []
    for rule in rules:
        rid = rule["id"]
        desc = rule.get("description", "")
        severity = rule.get("severity", "warn")
        scope_glob = rule.get("scope", "glob:**/*.py").split(":", 1)[1]
        patterns = rule.get("pattern_any_of", []) or []
        triggered, matches = _eval_patterns(workdir, scope_glob, patterns)
        out.append(
            StaticFinding(
                rule_id=rid,
                severity=severity,
                verdict="triggered" if triggered else "clean",
                matches=matches[:5],
                description=desc,
            )
        )
    return out


def _eval_patterns(workdir: Path, scope_glob: str, patterns: list[dict]) -> tuple[bool, list[str]]:
    matches: list[str] = []
    for py in workdir.rglob(scope_glob.replace("glob:", "")):
        if not py.is_file():
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in patterns:
            kind = pat.get("kind")
            if kind == "source_regex":
                if re.search(pat["regex"], text):
                    matches.append(str(py.relative_to(workdir)))
                    break
            elif kind == "ast_call_name":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                target = pat["name"]
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        name = (
                            node.func.id
                            if isinstance(node.func, ast.Name)
                            else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                        )
                        if name == target:
                            matches.append(str(py.relative_to(workdir)))
                            break
                else:
                    continue
                break
            elif kind == "ast_attribute":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                target = pat["attr"]
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and node.attr == target:
                        matches.append(str(py.relative_to(workdir)))
                        break
                else:
                    continue
                break
    return (bool(matches), matches)
