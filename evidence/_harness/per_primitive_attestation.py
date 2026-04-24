"""Per-primitive attestation — 124 registered primitives × 6 structural checks.

PRODUCT §2 / §6.2 / CONTRACT §B1.1 / §B1.2:
    - Primitives are framework-free motors.
    - Registry in engine/primitives_by_concern.yaml references every primitive.
    - Every primitive has ≥3 "Compose with" recipes.
    - No REPLACE_ME residue (not still-staged).
    - Has a unit test file.

This probe scans each of the 124 registered primitives under
`core/venous/<ns>/<Name>/` and attests the 6 structural invariants.
It does NOT run tests (aggregate pytest does that). It attests the
STRUCTURAL shape every primitive is required to carry so a consumer
can verify per-primitive presence + registry alignment.

Checks per primitive:
    1. NAME.py present (motor file)
    2. NAME.md present (spec file)
    3. test_NAME.py present (unit test file)
    4. "## Compose with" section present in NAME.md
    5. ≥3 bullet entries in Compose-with section
    6. No REPLACE_ME placeholder in NAME.py

Cross-cutting:
    - Registry (primitives_by_concern.yaml) references every primitive.

Output JSON:
    {
      "_meta": {...},
      "primitives_scanned": 124,
      "per_primitive": [ {namespace, name, checks: {...bool...}, compose_bullets: N}... ],
      "registry_coverage": {scanned: 124, missing: [...], extra: [...]},
      "summary": {
        "all_6_checks_pass": N,
        "any_check_fail": M,
        "check_coverage": {check_name: pct},
        "registry_aligned": bool,
        "passed": bool
      }
    }

Exit 0 iff every primitive satisfies all 6 checks AND registry is aligned.
"""
from __future__ import annotations

import ast
import datetime
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "SKILL-001-fastapi-production"
VENOUS_ROOT = SKILL_DIR / "core" / "venous"
REGISTRY_PATH = SKILL_DIR / "engine" / "primitives_by_concern.yaml"

CHECKS = [
    "motor_py_present",
    "spec_md_present",
    "test_file_present",
    "compose_section_present",
    "compose_bullets_ge_3",
    "no_replace_me",
]


def discover_primitives() -> list[dict]:
    """Return [{namespace, name, primitive_dir, motor_path, spec_path}]."""
    out: list[dict] = []
    for ns_dir in sorted(p for p in VENOUS_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for prim_dir in sorted(p for p in ns_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
            motor = prim_dir / f"{prim_dir.name}.py"
            if motor.exists():
                out.append({
                    "namespace": ns_dir.name,
                    "name": prim_dir.name,
                    "primitive_dir": prim_dir,
                    "motor_path": motor,
                    "spec_path": prim_dir / f"{prim_dir.name}.md",
                    "test_path": prim_dir / f"test_{prim_dir.name}.py",
                })
    return out


def _count_compose_bullets(md_text: str) -> tuple[bool, int]:
    """Return (section_present, bullet_count)."""
    m = re.search(r"^## Compose with:?\s*$", md_text, re.MULTILINE)
    if not m:
        return (False, 0)
    # Section found: count top-level "-" bullets until next "## " heading
    tail = md_text[m.end():]
    next_heading = re.search(r"^##\s+", tail, re.MULTILINE)
    section = tail[:next_heading.start()] if next_heading else tail
    bullets = re.findall(r"^\s*-\s+\*\*", section, re.MULTILINE)
    # Accept also plain "- " bullets as fallback
    if not bullets:
        bullets = re.findall(r"^-\s+", section, re.MULTILINE)
    return (True, len(bullets))


def audit_primitive(p: dict) -> dict:
    motor = p["motor_path"]
    spec = p["spec_path"]
    test = p["test_path"]

    motor_present = motor.exists()
    spec_present = spec.exists()
    test_present = test.exists()

    compose_section = False
    compose_bullets = 0
    if spec_present:
        md = spec.read_text()
        compose_section, compose_bullets = _count_compose_bullets(md)

    no_replace_me = True
    parse_error = None
    if motor_present:
        try:
            src = motor.read_text()
            if "REPLACE_ME" in src:
                no_replace_me = False
            ast.parse(src)  # sanity: parses cleanly
        except SyntaxError as e:
            parse_error = str(e)

    checks = {
        "motor_py_present": motor_present,
        "spec_md_present": spec_present,
        "test_file_present": test_present,
        "compose_section_present": compose_section,
        "compose_bullets_ge_3": compose_bullets >= 3,
        "no_replace_me": no_replace_me,
    }
    record = {
        "namespace": p["namespace"],
        "name": p["name"],
        "checks": checks,
        "compose_bullets": compose_bullets,
        "all_pass": all(checks.values()),
    }
    if parse_error:
        record["parse_error"] = parse_error
    return record


def load_registry_names() -> set[str]:
    """Walk the YAML registry and collect every PascalCase primitive name."""
    try:
        import yaml
    except Exception:
        # Fallback: regex scan
        txt = REGISTRY_PATH.read_text()
        return set(re.findall(r"\b([A-Z][a-zA-Z0-9_]+)\b", txt))
    data = yaml.safe_load(REGISTRY_PATH.read_text())
    names: set[str] = set()

    def walk(x):
        if isinstance(x, str):
            if re.fullmatch(r"[A-Z][a-zA-Z0-9_]+", x):
                names.add(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    return names


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def main() -> int:
    primitives = discover_primitives()
    per_primitive = [audit_primitive(p) for p in primitives]

    on_disk = {p["name"] for p in primitives}
    registered = load_registry_names()
    missing_from_registry = sorted(on_disk - registered)
    extra_in_registry = sorted(registered - on_disk)

    check_hits = {c: 0 for c in CHECKS}
    all_pass = 0
    for record in per_primitive:
        for c, ok in record["checks"].items():
            if ok:
                check_hits[c] += 1
        if record["all_pass"]:
            all_pass += 1
    total = len(per_primitive)
    check_coverage = {c: round(check_hits[c] / total * 100, 2) if total else 0.0 for c in CHECKS}
    registry_aligned = not missing_from_registry  # every on-disk primitive found in registry

    passed = (all_pass == total) and registry_aligned

    out = {
        "_meta": {
            "command": ".venv/bin/python evidence/_harness/per_primitive_attestation.py",
            "cwd": "repo root",
            "commit": _git("rev-parse", "HEAD"),
            "tree": _git("rev-parse", "HEAD^{tree}"),
            "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grading": "exit 0 iff every primitive passes all 6 checks AND registry aligned",
        },
        "primitives_scanned": total,
        "checks": CHECKS,
        "summary": {
            "all_pass": all_pass,
            "any_check_fail": total - all_pass,
            "check_coverage_pct": check_coverage,
            "registry_aligned": registry_aligned,
            "passed": passed,
        },
        "registry_coverage": {
            "on_disk": total,
            "in_registry": len(registered),
            "missing_from_registry": missing_from_registry,
            "extra_in_registry_unused": extra_in_registry[:50],  # truncate noise
        },
        "per_primitive": per_primitive,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
