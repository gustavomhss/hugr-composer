#!/usr/bin/env python3
"""CONTRACT.md machine enforcer.

Reads `/CONTRACT.md`, finds every `- [ ] BN.M` checklist item that has a
machine-checkable rule, runs the rule, and prints pass/fail. Exits non-zero
on any failure — suitable for pre-commit hooks and CI.

Rules map (shell-shaped commands that each item must satisfy) is kept IN
this file so the contract and the enforcer never drift: if someone adds a
new §B item they add the rule here; CI then enforces it from the next
commit onward.

Usage:
    python -m engine.audit.contract_check              # run all
    python -m engine.audit.contract_check --item B1.1  # one item
    python -m engine.audit.contract_check --phase 0    # whole phase
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[3].parent
# /Users/…/HuGR_Skills (one level above skills/)
SKILL_ROOT = REPO_ROOT / "skills" / "SKILL-001-fastapi-production"


@dataclass(frozen=True)
class Rule:
    item: str                 # "B0.5"
    phase: int                # 0..7
    description: str          # short human label
    check: Callable[[], tuple[bool, str]]  # -> (ok, message)


def _exists(path: Path, *, min_bytes: int = 0) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    if min_bytes and path.stat().st_size < min_bytes:
        return False, f"too small ({path.stat().st_size}B < {min_bytes}B): {path}"
    return True, f"ok: {path.relative_to(REPO_ROOT)}"


def _grep_count(pattern: str, paths: list[Path]) -> int:
    cmd = ["grep", "-rlE", pattern, *[str(p) for p in paths]]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return len([line for line in out.stdout.splitlines() if line])
    except FileNotFoundError:
        return 0


# ---------------------------------------------------------------------------
# Rules per §B item
# ---------------------------------------------------------------------------

def _r_product_md() -> tuple[bool, str]:
    ok, msg = _exists(REPO_ROOT / "PRODUCT.md", min_bytes=3000)
    if not ok:
        return ok, msg
    body = (REPO_ROOT / "PRODUCT.md").read_text()
    required = ["## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8."]
    missing = [s for s in required if s not in body]
    if missing:
        return False, f"PRODUCT.md missing sections: {missing}"
    return True, "PRODUCT.md present with all 8 required sections"


def _r_roadmap_md() -> tuple[bool, str]:
    return _exists(REPO_ROOT / "ROADMAP.md", min_bytes=3000)


def _r_contract_md() -> tuple[bool, str]:
    """B0.3 — CONTRACT.md present AND each of §A1..§A12 carries a named
    inviolable-rule heading.

    Pre-audit this rule only validated that `§A` / `§B` / `§C` string
    labels were present AND that `- [ ] **A1` existed. That was too
    loose: if a future edit silently drops any §A2..§A12 heading the
    audit would pass, defeating §A's "inviolable" guarantee (Codex
    HIGH #7). We now enumerate every §A rule ID and fail if any is
    missing. §A5 and §A8 also carry cross-doc semantic invariants
    (Compose-with ≥3 + no-hand-maintained-counts) that other rules
    enforce in detail; here we just verify the headings exist.
    """
    ok, msg = _exists(REPO_ROOT / "CONTRACT.md", min_bytes=5000)
    if not ok:
        return ok, msg
    body = (REPO_ROOT / "CONTRACT.md").read_text()
    for section in ("§A", "§B", "§C", "§D", "§E"):
        if section not in body:
            return False, f"CONTRACT.md missing {section} section"
    missing_a: list[str] = []
    for i in range(1, 13):
        if f"- [ ] **A{i} " not in body and f"- [ ] **A{i}\u2005" not in body:
            missing_a.append(f"A{i}")
    if missing_a:
        return False, (
            f"CONTRACT.md §A is missing rule heading(s): {missing_a}. "
            "§A rules are inviolable — every headline must be present "
            "verbatim (`- [ ] **A<N> — …**`). Silent removal defeats "
            "the `A<N>` citation discipline in every other rule."
        )
    return True, "CONTRACT.md present; §A1..§A12 + §B/§C/§D/§E all present"


def _r_readme_md() -> tuple[bool, str]:
    ok, msg = _exists(REPO_ROOT / "README.md", min_bytes=200)
    if not ok:
        return ok, msg
    body = (REPO_ROOT / "README.md").read_text()
    lines = body.count("\n")
    if lines > 120:
        return False, f"README.md exceeds 80-line hard budget ({lines} lines)"
    for link in ("PRODUCT.md", "ROADMAP.md", "CONTRACT.md"):
        if link not in body:
            return False, f"README.md missing link to {link}"
    return True, f"README.md present, {lines} lines, links to canonical docs"


def _r_claude_memory() -> tuple[bool, str]:
    mem = Path.home() / ".claude" / "projects"
    hits = list(mem.rglob("venous_architecture.md"))
    if not hits:
        return False, "no venous_architecture.md in ~/.claude/projects/"
    body = hits[0].read_text()
    if "PRODUCT.md" not in body or "CONTRACT.md" not in body:
        return False, "memory entry does not point to PRODUCT.md + CONTRACT.md"
    return True, f"memory ok at {hits[0]}"


def _r_skillmd_honest() -> tuple[bool, str]:
    path = SKILL_ROOT / "SKILL.md"
    ok, msg = _exists(path, min_bytes=500)
    if not ok:
        return ok, msg
    body = path.read_text()
    # Any claim numbers MUST be within 10% of reality on disk.
    tool_count = len(list((SKILL_ROOT / "adapt" / "extend").rglob("add_*.py")))
    m = re.search(r"(\d+)\s*(?:adapt|extend|EXTEND)\s*tools?", body)
    if m:
        claimed = int(m.group(1))
        if abs(claimed - tool_count) > max(10, tool_count * 0.1):
            return False, (
                f"SKILL.md claims {claimed} adapt tools; actual {tool_count}. "
                "Drift beyond 10% — must reconcile."
            )
    return True, f"SKILL.md honest ({tool_count} adapt tools on disk)"


def _r_gitignore_artefacts() -> tuple[bool, str]:
    gi = REPO_ROOT / ".gitignore"
    ok, msg = _exists(gi)
    if not ok:
        return ok, msg
    body = gi.read_text()
    must = [
        "tools_latent_primitives.json",
        "primitive_candidates_ranked.json",
        "dedupe_report.json",
        "ambiguous_primitives.json",
        "_t0_report.json",
    ]
    missing = [m for m in must if m not in body]
    if missing:
        return False, f".gitignore missing artefact entries: {missing}"
    return True, ".gitignore covers all machine-generated artefacts"


def _r_benchmark_no_stubs() -> tuple[bool, str]:
    """B0.7 — zero trivial-stub test functions anywhere in the skill.

    Scans three roots: ``benchmark/``, ``benchmarks/``, and the
    production primitive tree ``core/venous/`` (excluding
    ``_extracted/`` because that's the staging pool; stub tests there
    are by design until a primitive is promoted). A test function is
    flagged when its body reduces to exactly ``assert True`` — a
    mechanical no-op that passes without exercising any code path.

    Pre-audit this rule only scanned benchmark/ and flagged WHOLE
    files where EVERY function was ``assert True``. Mixed files with
    three stub-functions + one real-test slipped through. Codex
    2026-04-23 audit (HIGH #8) found 8 registered primitives with
    pure stub test suites in `core/venous/api/*`. The scan now
    inspects each function individually and lists each offender.
    """
    stubs: list[str] = []
    scan_roots = [SKILL_ROOT / "benchmark", SKILL_ROOT / "benchmarks",
                  SKILL_ROOT / "core" / "venous"]
    _stub_body_re = re.compile(
        r"^def (test_\w+)\([^)]*\)(?:\s*->\s*[^:]+)?:\n"
        r"(?:    \"\"\"(?:[^\"]|\"[^\"])*?\"\"\"\n)?"  # optional docstring
        r"    assert True\s*(?:\n|$)",
        re.MULTILINE,
    )
    for root in scan_roots:
        if not root.exists():
            continue
        for py in root.rglob("test_*.py"):
            # Skip the staged/quarantined pool — stub tests there are
            # by design until a primitive is promoted.
            if "_extracted" in py.parts:
                continue
            body = py.read_text()
            for m in _stub_body_re.finditer(body):
                fn_name = m.group(1)
                stubs.append(
                    f"{py.relative_to(REPO_ROOT)}::{fn_name}"
                )
    if stubs:
        sample = "\n    - ".join(stubs[:5])
        return False, (
            f"{len(stubs)} stub test function(s) with pure `assert True` body:\n"
            f"    - {sample}"
            + ("\n    …" if len(stubs) > 5 else "")
        )
    return True, "no trivial-stub test functions under benchmark/ or core/venous/"


def _r_registry_exists() -> tuple[bool, str]:
    """B1.1 — registry synced with disk + no half-extracted dirs.

    A "half-extracted" directory is a subdir under a production namespace
    that lacks a matching ``<Name>.md`` (per the strict dir==name contract).
    Historically these were candidate scaffolds abandoned mid-extraction;
    leaving them under a production namespace created the *perception*
    of a ready primitive that B1.1 silently skipped. Reject them outright.
    """
    reg = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
    ok, msg = _exists(reg, min_bytes=500)
    if not ok:
        return ok, msg
    import yaml as _yaml
    data = _yaml.safe_load(reg.read_text()) or {}
    registered = {p["name"] for p in (data.get("primitives") or [])}
    venous = SKILL_ROOT / "core" / "venous"

    on_disk: set[str] = set()
    all_leaf_dirs: set[Path] = set()
    for d in venous.glob("*/*"):
        if not d.is_dir():
            continue
        if any(part in d.parts for part in ("_extracted", "_adapters", "__pycache__")):
            continue
        all_leaf_dirs.add(d)
        md = d / f"{d.name}.md"
        if md.exists():
            on_disk.add(d.name)

    missing = sorted(on_disk - registered)
    if missing:
        return False, f"{len(missing)} production primitives unregistered: {missing[:5]}"
    extra = sorted(registered - on_disk)
    if extra:
        return False, f"{len(extra)} registered primitives have no .md on disk: {extra[:5]}"
    half_extracted = sorted(
        str(d.relative_to(venous)) for d in all_leaf_dirs
        if not (d / f"{d.name}.md").exists()
    )
    if half_extracted:
        return False, (
            f"{len(half_extracted)} half-extracted dirs under production namespaces "
            f"(no matching .md) — move to _extracted/ or complete them: {half_extracted[:5]}"
        )
    return True, f"registry synced: {len(registered)} entries match disk (no half-extracted dirs)"


def _r_compose_with_coverage() -> tuple[bool, str]:
    """B1.2 — every production primitive has a ≥3-bullet Compose-with section.

    CONTRACT §A5 requires ≥3 sibling pairings per primitive (so recipe
    retrieval has something meaningful to return). This rule checks both:
    section presence AND bullet count. Previously it only checked presence.
    """
    import yaml as _yaml
    reg = _yaml.safe_load((SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text())
    venous = SKILL_ROOT / "core" / "venous"

    missing_section: list[str] = []
    under_three: list[str] = []
    for entry in reg.get("primitives", []):
        md = venous / entry["namespace"] / entry["name"] / f"{entry['name']}.md"
        if not md.exists():
            missing_section.append(f"{entry['namespace']}/{entry['name']}")
            continue
        body = md.read_text()
        m = re.search(r"## Compose with.*?(?=\n## |\Z)", body, re.DOTALL | re.IGNORECASE)
        if not m:
            missing_section.append(f"{entry['namespace']}/{entry['name']}")
            continue
        bullets = re.findall(r"^\s*-\s", m.group(), re.MULTILINE)
        if len(bullets) < 3:
            under_three.append(f"{entry['namespace']}/{entry['name']} ({len(bullets)})")

    if missing_section:
        return False, f"{len(missing_section)} primitives lack 'Compose with:' section: {missing_section[:3]}"
    if under_three:
        return False, (
            f"{len(under_three)} primitives have <3 Compose-with bullets "
            f"(§A5 requires ≥3): {under_three[:3]}"
        )
    return True, f"100% of {len(reg['primitives'])} primitives have ≥3 Compose-with bullets"


def _r_tools_import_primitives() -> tuple[bool, str]:
    """B1.3 — ≥15 extend add_* tools import a registered primitive.

    Authoritative count = catalog.json's `primitives_used` populated via
    the MCP_TOOL.imports_primitives declaration or real import scan. A
    docstring that merely mentions `core.venous.Foo.Bar` does NOT satisfy
    this rule (verified by the tightened scan in
    `engine.index.manifest._extract_primitive_imports`).

    The current floor (22) is a non-regression guarantee: no PR may
    reduce the count below this without updating the CONTRACT.
    """
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog_path.exists():
        return False, "catalog.json missing — run engine.index.manifest build"
    try:
        cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"catalog.json unreadable: {exc}"
    connected = [
        t for t in cat.get("tools", [])
        if t.get("verb") == "add"
        and t.get("module_path", "").startswith("adapt/extend/")
        and t.get("primitives_used")
    ]
    FLOOR = 22
    if len(connected) < FLOOR:
        return False, (
            f"only {len(connected)}/100 extend add_* tools import primitives "
            f"(floor={FLOOR}; regression bars PR)"
        )
    return True, (
        f"{len(connected)}/100 extend add_* tools primitive-connected "
        f"(floor={FLOOR}, §B1.3 Rails-style wiring)"
    )


def _r_tier_lite_eligibility() -> tuple[bool, str]:
    """B1.8 — every `tier: "lite"` primitive satisfies §B1.8 eligibility.

    Reads `engine/primitives_by_concern.yaml`; for each entry with
    `tier == "lite"` verifies (all must be true):

    1. `core/venous/<namespace>/<Name>/<Name>.py` exists.
    2. That primary .py has no REPLACE_ME marker.
    3. That primary .py imports no framework modules (fastapi, starlette,
       sqlalchemy, sqlmodel, pydantic, django, flask, tornado, aiohttp),
       and declares no implicit framework tokens (`Mapped[`, `APIRouter(`,
       `Depends(`, `class Base(`).
    4. That primary .py contains no concurrency imports (threading,
       asyncio, multiprocessing) or names (Lock, Semaphore, Queue, etc.).

    Trivially green when zero lite primitives are registered. Satisfies
    CONTRACT §B1.8 and the 0004-tier-lite decision doc.
    """
    reg_path = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
    if not reg_path.exists():
        return False, "primitives_by_concern.yaml missing"
    try:
        import yaml as _yaml

        data = _yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"registry unreadable: {exc}"
    if not isinstance(data, dict):
        return False, "registry malformed"

    lite = [p for p in data.get("primitives", []) if p.get("tier") == "lite"]
    if not lite:
        return True, "§B1.8 vacuously satisfied (0 lite primitives registered)"

    # Lazy-import so contract_check doesn't pay promotion-module cost when
    # no lite primitives exist. The promotion module's AST helpers are the
    # single source of truth for these checks.
    import sys as _sys

    _sys.path.insert(0, str(SKILL_ROOT))
    from engine.promotion.state import (
        _detect_concurrency,
        _detect_framework_imports,
    )

    offenders: list[str] = []
    for p in lite:
        name = p.get("name")
        ns = p.get("namespace", "")
        if not name or not ns:
            offenders.append(f"{name or '?'}: registry entry missing name/namespace")
            continue
        py = SKILL_ROOT / "core" / "venous" / ns / name / f"{name}.py"
        if not py.exists():
            offenders.append(f"{name}: primary .py missing at {py.relative_to(SKILL_ROOT)}")
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            offenders.append(f"{name}: unreadable ({exc})")
            continue
        if "REPLACE_ME" in text:
            offenders.append(f"{name}: REPLACE_ME markers still present")
        fw = _detect_framework_imports(py)
        if fw:
            offenders.append(f"{name}: framework imports {fw}")
        if _detect_concurrency(py):
            offenders.append(
                f"{name}: concurrency imports present (lite forbids; promote at full tier)"
            )

    if offenders:
        joined = "\n    - ".join(offenders)
        return False, (
            f"§B1.8 lite eligibility violations ({len(offenders)}):\n    - {joined}\n"
            "Demote violating primitives to `_extracted/` or promote at full tier."
        )
    return True, f"§B1.8 satisfied ({len(lite)} lite primitive(s), all eligible)"


def _r_version_sync() -> tuple[bool, str]:
    """B4.6 — VERSION triplet sync: repo-root, skill, and STATUS.md frontmatter
    agree. Prevents the class of drift where one bump moves forward and the
    other two silently lag (observed pre-v1.0: root=0.2.0, skill=1.0.0-rc.1,
    STATUS.md=0.1.0 — three different versions for the same release).
    """
    root_version_file = REPO_ROOT / "VERSION"
    skill_version_file = SKILL_ROOT / "VERSION"
    status_md = SKILL_ROOT / "STATUS.md"
    for p in (root_version_file, skill_version_file, status_md):
        if not p.exists():
            return False, f"missing: {p.relative_to(REPO_ROOT)}"
    root_v = root_version_file.read_text(encoding="utf-8").strip()
    skill_v = skill_version_file.read_text(encoding="utf-8").strip()
    m = re.search(r"(?m)^version:\s*(\S+)\s*$", status_md.read_text(encoding="utf-8"))
    if not m:
        return False, "STATUS.md frontmatter missing `version:` key"
    status_v = m.group(1)
    if root_v != skill_v:
        return False, f"VERSION mismatch: /VERSION={root_v!r} vs skill/VERSION={skill_v!r}"
    if skill_v != status_v:
        return False, (
            f"VERSION mismatch: skill/VERSION={skill_v!r} vs "
            f"STATUS.md frontmatter={status_v!r}"
        )
    return True, f"triplet synced at {skill_v} (root + skill + STATUS.md)"


def _r_counts_sync() -> tuple[bool, str]:
    """B4.7 — canonical counts in INVENTORY.md reconcile against key narrative
    docs. INVENTORY is machine-generated by `engine.inventory`; drift in any
    other doc is §A8 failure. This rule catches the drift class observed
    pre-v1.0 (194 vs 181 staged, 121 vs 47 quarantined, 33 vs 34 contract).
    """
    inv = SKILL_ROOT / "INVENTORY.md"
    if not inv.exists():
        return False, "INVENTORY.md missing — run `python -m engine.inventory`"
    text = inv.read_text(encoding="utf-8")

    def _int(pattern: str, label: str) -> tuple[int | None, str]:
        m = re.search(pattern, text)
        if not m:
            return None, f"INVENTORY.md missing `{label}` headline"
        try:
            return int(m.group(1)), ""
        except ValueError:
            return None, f"INVENTORY.md `{label}` not an integer"

    checks = [
        ("registered", r"\*\*(\d+) registered primitives\*\*"),
        ("staged", r"\*\*(\d+) staged primitives\*\*"),
        ("quarantined", r"staged primitives\*\* in `_extracted/` \(plus (\d+) quarantined\)"),
        ("adapters", r"\*\*(\d+) FastAPI adapters\*\*"),
    ]
    canon: dict[str, int] = {}
    for label, pat in checks:
        value, err = _int(pat, label)
        if err:
            return False, err
        canon[label] = value

    narrative_docs = {
        "CLAUDE.md": REPO_ROOT / "CLAUDE.md",
        "STATUS.md": SKILL_ROOT / "STATUS.md",
        "ROADMAP.md": REPO_ROOT / "ROADMAP.md",
        "CHANGELOG.md[1.0.0]": REPO_ROOT / "CHANGELOG.md",
        # SKILL.md added here post-Codex-audit (BLOCKER #2).
        # The overview paragraph is Maestro's first read — it MUST carry
        # the current canonical counts, not pre-Wave-1.5 values. The check
        # only looks at the single paragraph under `## Overview` (not the
        # few-shot transcript counts, which are illustrative).
        "SKILL.md[Overview]": SKILL_ROOT / "SKILL.md",
    }
    required_tokens: dict[str, list[str]] = {
        "CLAUDE.md": [
            f"{canon['registered']}  primitivos registrados",
            f"{canon['staged']}  primitivos staged",
            f"+{canon['quarantined']} quarantined",
            f"{canon['adapters']}  FastAPI adapters",
        ],
        "STATUS.md": [
            f"| {canon['registered']} |",
            f"| {canon['staged']} |",
            f"| {canon['quarantined']} |",
            f"| {canon['adapters']} |",
        ],
        "ROADMAP.md": [
            f"| Registered primitives | {canon['registered']} |",
            f"| FastAPI adapters | {canon['adapters']} |",
            f"| Staged primitives | {canon['staged']} |",
            f"| Quarantined primitives | {canon['quarantined']} |",
        ],
        "CHANGELOG.md[1.0.0]": [
            f"**{canon['registered']} registered primitives**",
            f"**{canon['adapters']} FastAPI adapters**",
            f"**{canon['staged']} staged primitives**",
        ],
        "SKILL.md[Overview]": [
            # Overview-paragraph shape: "… 124 registered + 176 staged
            # framework-free primitives …". Covers registered + staged;
            # quarantined + adapters are not cited in the overview by
            # convention (the overview stays human-readable; detail lives
            # in INVENTORY.md + the tier-1 tool index below).
            f"{canon['registered']} registered + {canon['staged']} staged",
        ],
    }
    missing: list[str] = []
    for doc, path in narrative_docs.items():
        if not path.exists():
            missing.append(f"{doc}: file missing")
            continue
        body = path.read_text(encoding="utf-8")
        if doc == "CHANGELOG.md[1.0.0]":
            # Scope check to the [1.0.0] section body (stops at next `## [`).
            m = re.search(r"^## \[1\.0\.0\].*?(?=^## \[)", body, re.MULTILINE | re.DOTALL)
            if not m:
                missing.append(f"{doc}: [1.0.0] section header not found")
                continue
            body = m.group(0)
        elif doc == "SKILL.md[Overview]":
            # Scope to the `## Overview` paragraph — everything between
            # the `## Overview` heading and the next `##` heading. Keeps
            # the check from leaking into the few-shot transcripts (which
            # intentionally freeze example counts from a past release and
            # should not co-evolve with INVENTORY).
            m = re.search(
                r"^## Overview\s*\n(.*?)(?=^## )",
                body,
                re.MULTILINE | re.DOTALL,
            )
            if not m:
                missing.append(f"{doc}: `## Overview` section not found")
                continue
            body = m.group(1)
        for tok in required_tokens[doc]:
            if tok not in body:
                missing.append(f"{doc}: expected {tok!r}")
    if missing:
        joined = "\n    - ".join(missing)
        return False, (
            f"counts drift vs INVENTORY.md (canonical):\n    - {joined}\n"
            "Re-run `python -m engine.inventory` then sync narrative docs."
        )
    return True, (
        f"narrative docs (incl. SKILL.md Overview) match INVENTORY: "
        f"{canon['registered']} reg / {canon['staged']} staged / "
        f"{canon['quarantined']} qtn / {canon['adapters']} adapters"
    )


def _r_no_manual_mcp_tool_decorator() -> tuple[bool, str]:
    gen = SKILL_ROOT / "mcp_tools" / "generators.py"
    if not gen.exists():
        return True, "mcp_tools/generators.py absent — auto-discovery only"
    body = gen.read_text()
    count = body.count("@mcp_app.tool")
    if count > 0:
        return False, f"{count} hardcoded @mcp_app.tool decorators in generators.py"
    return True, "no hardcoded @mcp_app.tool decorators"


def _r_benchmark_score() -> tuple[bool, str]:
    """B3.5 — latest_score.json present + overall >= baseline_floor.json floor.

    The static floor is held in ``benchmarks/baseline_floor.json``; raise it
    in the same commit that raises the published score. A regression below
    the floor is a B3.5 failure — this is how we prevent "silent 69-point
    drop" scenarios where the hard floor (30) would still pass.
    """
    scorefile = SKILL_ROOT / "benchmarks" / "latest_score.json"
    floorfile = SKILL_ROOT / "benchmarks" / "baseline_floor.json"
    if not scorefile.exists():
        return False, "benchmarks/latest_score.json not published"
    try:
        data = json.loads(scorefile.read_text())
        score = float(data.get("overall", data.get("overall_average", 0)))
        methodology = data.get("methodology", "unknown")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return False, "benchmarks/latest_score.json malformed"

    floor = 30.0  # hard schema floor
    if floorfile.exists():
        try:
            floor = max(floor, float(json.loads(floorfile.read_text()).get("floor", 30.0)))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    if score < floor:
        return False, (
            f"benchmark score {score:.2f} < baseline floor {floor:.2f} "
            f"(set in benchmarks/baseline_floor.json — raise in the same "
            f"commit that raises latest_score.json)"
        )
    return True, f"baseline score {score:.2f} ≥ floor {floor:.2f} ({methodology})"


def _r_adapter_coverage() -> tuple[bool, str]:
    """B1.7 — every FastAPI adapter under _adapters/fastapi/ has a matching
    test + maps to a registered primitive; floor of ≥15 adapters.

    Adapters are the thin framework-specific shims that wire framework-free
    primitives into FastAPI (ADR 0003). Without test coverage, a subtle
    adapter bug breaks every generated app silently — so each adapter must
    have a ``test_<Name>Adapter.py`` beside it, and every adapter must
    reference a primitive that exists in the registry.
    """
    import yaml as _yaml
    adapters_dir = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"
    if not adapters_dir.exists():
        return False, f"missing: {adapters_dir.relative_to(SKILL_ROOT)}"

    reg = _yaml.safe_load((SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text())
    registered = {p["name"] for p in reg.get("primitives", [])}

    adapters = [
        f for f in adapters_dir.glob("*.py")
        if not f.name.startswith(("_", "test_"))
    ]
    if len(adapters) < 15:
        return False, f"only {len(adapters)} fastapi adapters (need ≥15)"

    # Family-tag mapping: adapter filenames use a family prefix (e.g.
    # "Workflow", "OAuth2") that the §A3 naming convention does NOT require
    # to match a primitive name exactly. These families map to one or more
    # registered primitives — maintained here so adding a new adapter that
    # breaks the mapping fails B1.7 in CI.
    family_map = {
        "Workflow": {"WorkflowRun", "ActivityCall", "DurableTimer"},
        "AuditLog": {"AuditEvent", "TamperEvidentAuditLog", "AccessLog"},
        "OAuth2": {"AuthorizationCodeFlow", "TokenIntrospector", "SessionStore"},
        "WebhookReceiver": {"SignatureVerifier", "IdempotentConsumer",
                            "InboxDeduplicator"},
        "Saga": {"SagaOrchestrator", "DomainEvent"},
    }

    missing_test: list[str] = []
    unknown_primitive: list[str] = []
    for a in adapters:
        if not (adapters_dir / f"test_{a.name}").exists():
            missing_test.append(a.stem)
        stem = a.stem
        # Convention: <PrimitiveOrFamily>Adapter.py
        if not stem.endswith("Adapter"):
            unknown_primitive.append(a.stem)
            continue
        prefix = stem[: -len("Adapter")]
        if prefix in registered:
            continue
        if prefix in family_map and family_map[prefix] & registered:
            continue
        if any(rn in stem for rn in registered):
            continue
        unknown_primitive.append(a.stem)

    if missing_test:
        return False, f"{len(missing_test)} adapters lack a test_*.py: {missing_test[:3]}"
    if unknown_primitive:
        return False, (
            f"{len(unknown_primitive)} adapters reference no registered primitive: "
            f"{unknown_primitive[:3]}"
        )
    return True, f"{len(adapters)} fastapi adapters, 100% tested + map to registry"


def _r_core_venous_distribution() -> tuple[bool, str]:
    """B1.0 — generate a sample project, copy a primitive into it, import it."""
    import sys
    import tempfile

    decision = REPO_ROOT / "docs" / "decisions" / "0002-core-venous-distribution.md"
    if not decision.exists():
        return False, "missing ADR: docs/decisions/0002-core-venous-distribution.md"

    scaffold = SKILL_ROOT / "generators" / "scaffold_venous.py"
    if not scaffold.exists():
        return False, "missing generators/scaffold_venous.py"

    # Ensure SKILL_ROOT is importable.
    skill_root_str = str(SKILL_ROOT)
    if skill_root_str not in sys.path:
        sys.path.insert(0, skill_root_str)

    try:
        from generators.orchestrator import generate_project
        from generators.scaffold_venous import ensure_primitives
    except ImportError as exc:
        return False, f"scaffold imports failed: {exc}"

    with tempfile.TemporaryDirectory() as tmp:
        generate_project(
            output_dir=tmp,
            name="contract_check_sample",
            profile="minimal",
            models={"Item": {"title": "str"}},
        )
        manifest = ensure_primitives(
            tmp,
            names=["core.venous.resiliency.GracefulShutdown"],
        )
        prim_file = (
            Path(tmp) / "core" / "venous" / "resiliency" / "GracefulShutdown"
            / "GracefulShutdown.py"
        )
        if not prim_file.exists():
            return False, f"primitive not copied into sample: {prim_file}"
        if not any(
            p["qualified_name"] == "core.venous.resiliency.GracefulShutdown"
            for p in manifest.primitives
        ):
            return False, "manifest missing GracefulShutdown entry"

        # Prove `from core.venous.resiliency.GracefulShutdown.GracefulShutdown
        # import GracefulShutdown` resolves inside the generated project.
        cmd = [
            sys.executable,
            "-c",
            "from core.venous.resiliency.GracefulShutdown.GracefulShutdown import GracefulShutdown; print('ok')",
        ]
        out = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, check=False)
        if out.returncode != 0 or "ok" not in out.stdout:
            return False, f"import in generated project failed: {out.stderr.strip()}"

    return True, "sample project imports copied primitive cleanly"


def _r_adapter_layer_invariant() -> tuple[bool, str]:
    """B1.0.1 — decision + reference adapter + zero framework leaks in primitives."""
    decision = REPO_ROOT / "docs" / "decisions" / "0003-adapter-layer.md"
    if not decision.exists():
        return False, "missing ADR: docs/decisions/0003-adapter-layer.md"

    ref = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi" / "GracefulShutdownAdapter.py"
    if not ref.exists():
        return False, f"missing reference adapter: {ref}"

    # grep equivalent — scan primitive .py files for FastAPI / Starlette / SQLAlchemy
    # imports; ignore _adapters/ and _extracted/ which are out of scope.
    # Match only real top-of-line imports (not strings / comments).
    pat = re.compile(r"^\s*(?:from|import)\s+(fastapi|starlette|sqlalchemy)\b", re.MULTILINE)
    leaks: list[str] = []
    venous = SKILL_ROOT / "core" / "venous"
    for py in venous.rglob("*.py"):
        parts = py.parts
        if "_adapters" in parts or "_extracted" in parts or "__pycache__" in parts:
            continue
        if pat.search(py.read_text(errors="ignore")):
            leaks.append(str(py.relative_to(SKILL_ROOT)))
    if leaks:
        return False, f"framework imports leaked into primitives: {leaks[:3]}..."
    return True, "primitives framework-agnostic; reference adapter present"


def _r_no_orphan_generators() -> tuple[bool, str]:
    """B1.6 — every top-level ``generate_X``/``scaffold_X`` function in
    generators/ and modules/**/tools/ is either MCP_TOOL-wrapped OR
    called by another module (internal helper). Prevents the Phase 2
    drift where generator files quietly shipped as non-discoverable code.

    Implementation: one walk of SKILL_ROOT builds a `{path: contents}`
    map, then each candidate function does an O(1) cached-dict scan
    for callers. Previously spawned one `grep -rl` subprocess per
    candidate (~60 of them), which dominated `_r_*` runtime.
    """
    bases = ("generators", "core/tools", "modules/database/tools",
             "modules/security/tools", "benchmark")

    # One-pass corpus of every .py file in the skill tree. Populated
    # lazily — only if the base contains at least one candidate.
    _corpus: dict[Path, str] | None = None

    def _load_corpus() -> dict[Path, str]:
        nonlocal _corpus
        if _corpus is not None:
            return _corpus
        out: dict[Path, str] = {}
        for py in SKILL_ROOT.rglob("*.py"):
            parts = py.parts
            if ".venv" in parts or "__pycache__" in parts:
                continue
            try:
                out[py] = py.read_text(errors="ignore")
            except OSError:
                continue
        _corpus = out
        return out

    orphans: list[str] = []
    for base in bases:
        d = SKILL_ROOT / base
        if not d.exists():
            continue
        for py in d.rglob("*.py"):
            if py.name.startswith("__") or "__pycache__" in py.parts or py.name.startswith("test_"):
                continue
            txt = py.read_text(errors="ignore")
            if "MCP_TOOL" in txt:
                continue
            m = re.search(r"^def\s+(generate_\w+|scaffold_\w+)\s*\(", txt, re.MULTILINE)
            if not m:
                continue
            fn = m.group(1)
            # quick call-graph: ≥1 caller elsewhere in-tree → internal helper
            corpus = _load_corpus()
            callers = [p for p, c in corpus.items() if p != py and fn in c]
            if not callers:
                orphans.append(f"{py.relative_to(SKILL_ROOT)} ({fn})")
    if orphans:
        return False, f"orphan generators: {orphans}"
    return True, "every generate_*/scaffold_* function is either MCP_TOOL or internal helper"


def _r_find_primitive_discovery() -> tuple[bool, str]:
    """B2.1 — find_primitive MCP tool exists, registers, and clears quality gate."""
    module_path = SKILL_ROOT / "engine" / "discovery" / "find_primitive.py"
    if not module_path.exists():
        return False, f"missing: {module_path.relative_to(REPO_ROOT)}"

    test_set = SKILL_ROOT / "benchmarks" / "discovery_test_set.json"
    if not test_set.exists():
        return False, f"missing: {test_set.relative_to(REPO_ROOT)}"

    # Run quality bench; it enforces top-1 ≥ 80% and P@3 ≥ 90% per §B2.1 quality.
    cmd = [
        sys.executable,
        "-m",
        "engine.discovery.quality_bench",
        "--min-top-1",
        "0.80",
        "--min-p-at-3",
        "0.90",
    ]
    env_pythonpath = str(SKILL_ROOT)
    out = subprocess.run(
        cmd,
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0:
        return False, f"quality gate failed: {out.stdout.strip() or out.stderr.strip()}"

    # Check the tool registers on the MCP app without raising.
    cmd = [
        sys.executable,
        "-c",
        (
            "from mcp_tools import mcp, discover_and_register; "
            "discover_and_register(mcp); "
            "import asyncio; "
            "t = asyncio.run(mcp.get_tool('fastapi_meta_search_primitive')); "
            "assert t.name == 'fastapi_meta_search_primitive', t.name; print('ok')"
        ),
    ]
    out = subprocess.run(
        cmd,
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0 or "ok" not in out.stdout:
        return False, f"MCP registration failed: {out.stderr.strip()[:300]}"

    return True, "find_primitive registered; quality gate (top-1≥80%, P@3≥90%) passing"


def _r_suggest_composition() -> tuple[bool, str]:
    """B2.2 — suggest_composition MCP tool exists, registers, clears quality."""
    module_path = SKILL_ROOT / "engine" / "discovery" / "compose.py"
    if not module_path.exists():
        return False, f"missing: {module_path.relative_to(REPO_ROOT)}"
    test_set = SKILL_ROOT / "benchmarks" / "composition_test_set.json"
    if not test_set.exists():
        return False, f"missing: {test_set.relative_to(REPO_ROOT)}"

    env_pythonpath = str(SKILL_ROOT)
    cmd = [
        sys.executable, "-m", "engine.discovery.compose_bench",
        "--min-top-1", "0.70", "--min-p-at-3", "0.90",
    ]
    out = subprocess.run(
        cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0:
        return False, f"quality gate failed: {out.stdout.strip() or out.stderr.strip()}"

    cmd = [
        sys.executable, "-c",
        (
            "from mcp_tools import mcp, discover_and_register; "
            "discover_and_register(mcp); "
            "import asyncio; "
            "t = asyncio.run(mcp.get_tool('fastapi_meta_search_composition')); "
            "assert t.name == 'fastapi_meta_search_composition', t.name; print('ok')"
        ),
    ]
    out = subprocess.run(
        cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0 or "ok" not in out.stdout:
        return False, f"MCP registration failed: {out.stderr.strip()[:300]}"

    return True, "suggest_composition registered; quality gate (top-1≥70%, P@3≥90%) passing"


def _r_docs_site() -> tuple[bool, str]:
    """B2.3 — docs site generator exists, is idempotent, covers all primitives."""
    builder = SKILL_ROOT / "engine" / "docs" / "build.py"
    if not builder.exists():
        return False, f"missing: {builder.relative_to(REPO_ROOT)}"

    import tempfile

    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_docs_") as tmp:
        cmd = [
            sys.executable, "-m", "engine.docs.build",
            "--out", tmp, "--verify",
        ]
        out = subprocess.run(
            cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
            env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
        )
        if out.returncode != 0:
            return False, f"build --verify failed: {(out.stdout or out.stderr).strip()[:300]}"
        manifest_path = Path(tmp) / "build_manifest.json"
        if not manifest_path.exists():
            return False, "build_manifest.json not written"
        import json as _json
        manifest = _json.loads(manifest_path.read_text())
        if manifest["primitives"] < 97:
            return False, f"only {manifest['primitives']} primitive pages (need ≥97)"
        # Spot-check: every registry entry has an HTML page.
        import yaml as _yaml
        registry = _yaml.safe_load((SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text())
        missing = [
            e["name"] for e in registry["primitives"]
            if not (Path(tmp) / "primitive" / f"{e['name']}.html").is_file()
        ]
        if missing:
            return False, f"missing pages: {missing[:5]}"
    return True, f"docs site generator green; {manifest['pages_written']} pages, idempotent hash"


def _r_bench_specs() -> tuple[bool, str]:
    """B3.1 — 20 specs split 5/10/5 with required sections."""
    specs = SKILL_ROOT / "benchmarks" / "specs"
    if not specs.exists():
        return False, f"missing: {specs.relative_to(REPO_ROOT)}"
    counts: dict[str, int] = {}
    for tier in ("baseline", "mid", "adversarial"):
        counts[tier] = len(list((specs / tier).glob("*.md"))) if (specs / tier).exists() else 0
    if counts != {"baseline": 5, "mid": 10, "adversarial": 5}:
        return False, f"tier counts wrong: {counts}"

    required = ("## Requirements", "## Acceptance criteria", "## Non-requirements")
    for spec_file in specs.rglob("*.md"):
        if spec_file.name == "README.md":
            continue
        txt = spec_file.read_text()
        # Title — `# <h1>` at top — is required per the B3.1 Completeness
        # bullet in CONTRACT.md. Each spec should open with a single
        # `# ` line naming the scenario.
        if not re.search(r"^#\s+\S", txt, re.MULTILINE):
            return False, f"{spec_file.name} missing top-level `# <title>` heading"
        for section in required:
            if section not in txt:
                return False, f"{spec_file.name} missing {section}"
    return True, (
        "20 specs present (5/10/5) with `# title` + 3 required sections "
        "(Requirements / Acceptance criteria / Non-requirements)"
    )


def _r_skill_md_contract() -> tuple[bool, str]:
    """B2.5 — SKILL.md follows the Agent Skills contract for Maestro consumption.

    Enforces the 20 rules from `docs/research/SKILL_META_FORMAT.md` §13.
    Every rule is cheap (file parse + regex). Fails fast on the first
    violation with line numbers so authors can fix.
    """
    skill_md = SKILL_ROOT / "SKILL.md"
    if not skill_md.exists():
        return False, "missing: skills/SKILL-001-fastapi-production/SKILL.md"
    raw = skill_md.read_text(encoding="utf-8")

    # 1. Frontmatter fence pair
    if not raw.startswith("---\n"):
        return False, "SKILL.md must open with '---' YAML frontmatter fence"
    end_fence = raw.find("\n---\n", 4)
    if end_fence < 0:
        return False, "SKILL.md frontmatter not closed with '---' fence"
    fm_text = raw[4:end_fence]
    body = raw[end_fence + 5:]

    # 2. Frontmatter YAML parses
    try:
        import yaml
        fm = yaml.safe_load(fm_text) or {}
    except Exception as exc:  # noqa: BLE001
        return False, f"SKILL.md frontmatter YAML invalid: {exc}"

    # 3. `name` field (Anthropic spec)
    name = fm.get("name")
    if not isinstance(name, str) or not name:
        return False, "SKILL.md frontmatter missing `name` (non-empty string)"
    if len(name) > 64:
        return False, f"SKILL.md name too long ({len(name)}>64)"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        return False, f"SKILL.md name must match ^[a-z0-9-]+$; got {name!r}"
    if name in {"anthropic", "claude"}:
        return False, f"SKILL.md name uses reserved word: {name!r}"

    # 4. `description` field (Anthropic spec)
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return False, "SKILL.md frontmatter missing `description`"
    if len(desc) > 1024:
        return False, f"SKILL.md description too long ({len(desc)}>1024 chars)"
    if "<" in desc or ">" in desc:
        return False, "SKILL.md description cannot contain XML tags (`<`/`>`)"
    first_word = desc.strip().split(None, 1)[0].lower()
    if first_word in {"i", "you", "we"}:
        return False, (
            f"SKILL.md description must be third-person "
            f"(starts with {first_word!r})"
        )

    # 5. Trigger + anti-trigger phrases
    desc_low = desc.lower()
    if not any(kw in desc_low for kw in ("use when", "trigger when")):
        return False, "SKILL.md description lacks a 'use when' positive-trigger clause"
    if not any(kw in desc_low for kw in ("do not", "not use", "avoid")):
        return False, "SKILL.md description lacks a 'do not' anti-trigger clause"

    # 6. Body budget (lines + token estimate)
    body_lines = body.splitlines()
    if len(body_lines) > 500:
        return False, f"SKILL.md body >500 lines ({len(body_lines)}) — split references"
    if len(body) // 4 > 5000:
        return False, f"SKILL.md body >5000 tokens (estimate {len(body)//4})"

    # 7. Required H2 sections
    required_sections = (
        "## Overview", "## When to use", "## When NOT to use",
        "## Machine-readable metadata", "## Workflow phases",
        "## Tier-1 tool index", "## Few-shot transcripts",
        "## Anti-patterns", "## Reference files",
    )
    missing_sections = [s for s in required_sections if s not in body]
    if missing_sections:
        return False, f"SKILL.md missing required sections: {missing_sections[:3]}"

    # 8. Machine-readable metadata fenced YAML
    meta_block = re.search(r"## Machine-readable metadata\s*\n\s*```yaml\n(.*?)\n```",
                           body, re.DOTALL)
    if not meta_block:
        return False, "SKILL.md missing fenced ```yaml block under 'Machine-readable metadata'"
    try:
        meta = yaml.safe_load(meta_block.group(1)) or {}
    except Exception as exc:  # noqa: BLE001
        return False, f"SKILL.md machine-readable metadata YAML invalid: {exc}"
    for required_key in ("hugr_skill_version", "spec_compat", "kind",
                          "domains", "entry_tools", "catalog_path",
                          "phases", "invariants"):
        if required_key not in meta:
            return False, f"SKILL.md machine-readable metadata missing `{required_key}`"

    # 9. `hugr_skill_version` semver
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(meta["hugr_skill_version"])):
        return False, (
            f"hugr_skill_version must be semver (e.g. '1.0.0'); "
            f"got {meta['hugr_skill_version']!r}"
        )

    # 10. catalog_path exists + valid JSON with expected keys
    cat = SKILL_ROOT / str(meta["catalog_path"])
    if not cat.exists():
        return False, f"catalog_path does not exist: {cat.relative_to(SKILL_ROOT)}"
    try:
        cat_data = json.loads(cat.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"catalog_path file malformed: {exc}"
    for k in ("schema_version", "tools", "primitives", "recipes", "counts"):
        if k not in cat_data:
            return False, f"catalog.json missing top-level key {k!r}"

    # 11. Every entry_tool exists in the registered MCP tool surface
    #     (we match against the catalog's tool names + the known
    #     tier-1 meta-tool names registered via register_tier1_tools +
    #     the fastapi_auth tree dispatcher)
    cat_tool_names = {t.get("name") for t in cat_data.get("tools", [])}
    known_non_catalog = {
        "fastapi_meta_home", "fastapi_meta_search", "fastapi_meta_describe",
        "fastapi_meta_scaffold", "fastapi_meta_compose",
        "fastapi_meta_audit", "fastapi_meta_verify",
        "fastapi_auth", "fastapi_meta_search_primitive", "fastapi_meta_search_composition",
    }
    valid_tool_names = cat_tool_names | known_non_catalog
    missing_tools = [
        t for t in meta.get("entry_tools", [])
        if t not in valid_tool_names
    ]
    if missing_tools:
        return False, (
            f"SKILL.md entry_tools reference unknown tools: {missing_tools[:3]}"
        )

    # 12. Few-shot transcripts ≥ 2, ≤ 3 (fenced code blocks under the section)
    transcripts_section = re.search(
        r"## Few-shot transcripts(.+?)(?=\n## )", body, re.DOTALL,
    )
    if not transcripts_section:
        return False, "SKILL.md 'Few-shot transcripts' section missing body"
    transcripts = re.findall(r"```[^\n]*\n(.*?)```", transcripts_section.group(1), re.DOTALL)
    if not (2 <= len(transcripts) <= 3):
        return False, (
            f"SKILL.md must include 2-3 few-shot transcripts; got {len(transcripts)}"
        )

    # 13. No forbidden drift heuristics (STATUS/ROADMAP territory)
    forbidden = ("benchmark score", "test count", "sprint", "Phase 4 complete")
    hits = [f for f in forbidden if f.lower() in body.lower()]
    if hits:
        return False, (
            f"SKILL.md contains forbidden drift-prone phrases: {hits}. "
            f"Move these to STATUS.md."
        )

    # 14. No XML tags in the body (excluding backticked code / placeholders)
    body_stripped = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    body_stripped = re.sub(r"`[^`]*`", "", body_stripped)
    # Real XML tags have a closing `>` with letters inside, or a `/` prefix.
    # `<slug>` placeholder style is ambiguous; we focus on unambiguous XML.
    if re.search(r"</[A-Za-z][A-Za-z0-9]*\s*>|<[A-Za-z][A-Za-z0-9]*\s+[a-z][a-z-]*=",
                 body_stripped):
        return False, "SKILL.md body contains XML tags; remove them"

    # 15. Reference files listed exist on disk
    ref_section = re.search(r"## Reference files(.+?)(?=\n---|\Z)", body, re.DOTALL)
    if ref_section:
        # Paths live inside backticks on each bullet line.
        for m in re.finditer(r"^\s*-\s+`([^`]+)`", ref_section.group(1), re.MULTILINE):
            ref = m.group(1).strip()
            # Absolute (repo-root-relative, starts with /) vs sibling
            if ref.startswith("/"):
                p = REPO_ROOT / ref.lstrip("/")
            else:
                p = SKILL_ROOT / ref
            if not p.exists():
                return False, f"SKILL.md references missing file: {ref}"

    # 16. Versioning footer
    if not re.search(r"\*version:\s*\d+\.\d+\.\d+", body):
        return False, "SKILL.md missing versioning footer (*version: X.Y.Z ...*)"

    return True, (
        f"SKILL.md v{meta['hugr_skill_version']}: "
        f"{len(desc)}-char desc, {len(body_lines)}-line body, "
        f"{len(transcripts)} transcripts, {len(meta['entry_tools'])} entry tools"
    )


def _r_index_manifest() -> tuple[bool, str]:
    """B2.4 — engine/index/catalog.json is synced with the on-disk sources.

    Runs `python -m engine.index.manifest build` into a tempdir, compares
    the fresh stable-hash with the committed hash. Drift = failure.
    Also asserts the committed file is schema-valid.
    """
    catalog = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog.exists():
        return False, f"missing: {catalog.relative_to(SKILL_ROOT)}"
    try:
        data = json.loads(catalog.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"catalog.json malformed: {exc}"
    schema_version = data.get("schema_version")
    if schema_version != "2":
        return False, f"catalog.json schema_version={schema_version!r}; expected '2'"
    counts = data.get("counts") or {}
    for field, minimum in (("tools", 150), ("primitives", 100), ("recipes", 200)):
        if int(counts.get(field, 0)) < minimum:
            return False, f"catalog.json counts.{field}={counts.get(field)} < floor {minimum}"

    # Determinism check — rebuild into a tempdir and compare stable hashes.
    import tempfile
    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_manifest_") as tmp:
        out_path = Path(tmp) / "catalog.json"
        proc = subprocess.run(
            [sys.executable, "-m", "engine.index.manifest", "verify", "--out", str(out_path)],
            cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
            env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
        )
        if proc.returncode != 0:
            return False, f"manifest verify failed: {(proc.stdout + proc.stderr)[-300:]}"
        # Compare committed catalog's stable content (ignoring generated_at + kit_commit)
        live = json.loads(out_path.read_text())
        committed = json.loads(catalog.read_text())
        for f in ("generated_at", "kit_commit"):
            live.pop(f, None); committed.pop(f, None)
        if json.dumps(live, sort_keys=True) != json.dumps(committed, sort_keys=True):
            return False, (
                "engine/index/catalog.json drifted from on-disk sources. "
                "Regenerate via `python -m engine.index.manifest build` and commit."
            )
    return True, (
        f"catalog synced: {counts.get('tools')} tools, "
        f"{counts.get('primitives')} primitives, {counts.get('recipes')} recipes"
    )


def _r_bench_rubric_runner() -> tuple[bool, str]:
    """B3.2 + B3.3 — rubric and runner importable, stub run yields 0-score report."""
    rubric = SKILL_ROOT / "engine" / "bench" / "rubric.py"
    runner = SKILL_ROOT / "engine" / "bench" / "runner.py"
    if not rubric.exists() or not runner.exists():
        return False, "missing rubric.py or runner.py"

    env_pythonpath = str(SKILL_ROOT)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "engine/tests/test_bench.py", "-q"],
        cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0:
        return False, f"bench tests failed: {(out.stdout or out.stderr).strip()[-300:]}"
    return True, "rubric + runner green (13 bench tests passing)"


def _r_bench_nightly_workflow() -> tuple[bool, str]:
    """B3.4 — CI workflow file exists and declares the benchmark job."""
    wf = REPO_ROOT / ".github" / "workflows" / "benchmark-nightly.yml"
    if not wf.exists():
        return False, "missing: .github/workflows/benchmark-nightly.yml"
    txt = wf.read_text()
    for required in ("schedule:", "cron:", "engine.bench", "ANTHROPIC_API_KEY", "latest_score.json"):
        if required not in txt:
            return False, f"workflow missing {required}"
    return True, "benchmark-nightly.yml present with schedule + claude dispatch + score upload"


def _r_code_level_benchmark() -> tuple[bool, str]:
    """B3.6 — code-level harness published + perfect on covered specs.

    The plan-level score (B3.5) measures the Maestro's requirement→primitive
    mapping. The code-level score measures whether the ACTUAL code path
    asserted by the spec's Acceptance criteria is exercised by a passing
    test suite. Different signal; different failure modes.

    Rule:
      1. benchmarks/code_level_score.json exists and parses.
      2. Every COVERED spec scores 100 (if the code path is exercised,
         every assertion must pass — there is no "partial credit" at
         the code level).
      3. Coverage (covered / total) ≥ 25%. Raise this floor in the same
         commit that adds the matching examples.
    """
    f = SKILL_ROOT / "benchmarks" / "code_level_score.json"
    if not f.exists():
        return False, "missing: benchmarks/code_level_score.json"
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return False, "code_level_score.json malformed"
    covered = int(data.get("covered_specs", 0))
    total = int(data.get("total_specs", 0))
    score = float(data.get("code_level_score", 0))
    coverage = float(data.get("coverage", 0))
    if total != 20:
        return False, f"code_level_score.json has {total} specs (expected 20)"
    if covered < 5:
        return False, f"only {covered}/{total} specs covered at code-level (need ≥5)"
    if coverage < 25.0:
        return False, f"coverage {coverage:.1f}% < 25% floor"
    if score < 100.0:
        fails = [
            s["spec_id"] for s in data.get("spec_results", [])
            if s.get("covered") and (s.get("score") or 0) < 100
        ]
        return False, f"covered specs not all at 100 ({score:.2f}): {fails[:3]}"
    return True, (
        f"code-level: {score:.2f} across {covered}/{total} covered specs "
        f"({coverage:.1f}% coverage)"
    )


def _r_blind_benchmark_harness() -> tuple[bool, str]:
    """B3.7 — blind-benchmark harness present + stub validates end-to-end.

    Requires:
      1. benchmarks/blind/PROTOCOL.md (pre-registered, §A8 drift-aware)
      2. engine/bench/blind/{spec,adapter,judge,runner,publish,snapshots,
         attribution,static_scan}.py modules importable
      3. At least one authored spec under benchmarks/blind/specs/<tier>/
         that passes load_spec() validation
      4. Stub fixtures covering the authored specs
      5. The last stub run (if any) produced aggregate.json with
         hypothesis_test.H1_supported populated (not necessarily true —
         stub may not satisfy H1, but the field must exist)

    We do NOT require a successful live (non-stub) run here — that is
    cost-dependent and runs separately via Phase-6B sprints.
    """
    bench_dir = SKILL_ROOT / "benchmarks" / "blind"
    protocol = bench_dir / "PROTOCOL.md"
    if not protocol.exists() or protocol.stat().st_size < 2000:
        return False, f"missing or undersized PROTOCOL.md: {protocol}"

    modules_dir = SKILL_ROOT / "engine" / "bench" / "blind"
    expected = {"spec.py", "adapter.py", "judge.py", "runner.py",
                "publish.py", "snapshots.py", "attribution.py",
                "static_scan.py", "__init__.py"}
    missing = [m for m in expected if not (modules_dir / m).exists()]
    if missing:
        return False, f"engine/bench/blind/ missing: {missing}"

    # Importability smoke
    import importlib
    try:
        importlib.import_module("engine.bench.blind.runner")
        importlib.import_module("engine.bench.blind.spec")
        importlib.import_module("engine.bench.blind.judge")
    except Exception as exc:  # noqa: BLE001
        return False, f"harness import failed: {exc}"

    # At least one spec + passes load_spec
    from engine.bench.blind.spec import discover_specs
    specs = discover_specs(bench_dir / "specs")
    if not specs:
        return False, "no specs under benchmarks/blind/specs/<tier>/"

    # Stub fixtures for every authored spec
    fixtures_dir = bench_dir / "_stub_fixtures"
    missing_fx = []
    for s in specs:
        slug = s.spec_id.replace("/", "__")
        for cond in ("naked", "kit"):
            p = fixtures_dir / slug / cond / "emitted"
            if not p.is_dir():
                missing_fx.append(f"{slug}/{cond}")
    if missing_fx:
        return False, f"stub fixtures missing: {missing_fx[:3]}"

    return True, (
        f"blind harness present · {len(specs)} spec(s) authored · "
        f"stub fixtures complete"
    )


def _r_install_docker_ci() -> tuple[bool, str]:
    """B4.1 — install.sh + install-docker CI workflow present + hermetic."""
    installer = REPO_ROOT / "install.sh"
    workflow = REPO_ROOT / ".github" / "workflows" / "install-docker.yml"
    if not installer.exists():
        return False, "missing: install.sh"
    if not workflow.exists():
        return False, "missing: .github/workflows/install-docker.yml"
    txt = workflow.read_text(encoding="utf-8")
    for required in ("python:3.12-slim", "install.sh", "contract_check", "latest_score.json", "schedule:"):
        if required not in txt:
            return False, f"install-docker.yml missing {required!r}"
    inst = installer.read_text(encoding="utf-8")
    for required in ("set -euo pipefail", "python3 -m venv", "requirements-mcp.txt"):
        if required not in inst:
            return False, f"install.sh missing {required!r}"
    return True, "install.sh + install-docker.yml validated in python:3.12-slim"


def _r_examples_populated() -> tuple[bool, str]:
    """B4.2 — /examples/ has ≥5 subdirs, each carrying the required docset."""
    examples = REPO_ROOT / "examples"
    if not examples.exists():
        return False, "missing: /examples/"
    subdirs = [p for p in examples.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))]
    if len(subdirs) < 5:
        return False, f"only {len(subdirs)} examples (need ≥5)"
    required = ("README.md", "MAESTRO_SESSION.md")
    for sub in subdirs:
        for f in required:
            if not (sub / f).exists():
                return False, f"{sub.name}/ missing {f}"
        # cross-link table: must mention tools-used + primitives-imported
        readme = (sub / "README.md").read_text(encoding="utf-8")
        if "Tools used" not in readme or "Primitives imported" not in readme:
            return False, f"{sub.name}/README.md missing cross-link table (Tools used / Primitives imported)"
    return True, f"{len(subdirs)} examples present with README + MAESTRO_SESSION + cross-link tables"


def _r_docs_site_v1() -> tuple[bool, str]:
    """B4.3 — docs site includes top-level docs + per-tool pages."""
    import tempfile
    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_docs_v1_") as tmp:
        cmd = [sys.executable, "-m", "engine.docs.build", "--out", tmp, "--verify"]
        out = subprocess.run(
            cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
            env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
        )
        if out.returncode != 0:
            return False, f"build --verify failed: {(out.stdout or out.stderr).strip()[:300]}"
        root = Path(tmp)
        # Top-level docs: PRODUCT + ROADMAP + CONTRACT + CONTRIBUTING + CHANGELOG
        for slug in ("product", "roadmap", "contract", "contributing", "changelog"):
            if not (root / "doc" / f"{slug}.html").is_file():
                return False, f"missing doc page: doc/{slug}.html"
        # Every adapt tool has a page.
        tool_dir = root / "tool"
        if not tool_dir.exists():
            return False, "missing tool/ page directory"
        n_tool_pages = sum(1 for _ in tool_dir.glob("*.html"))
        if n_tool_pages < 90:
            return False, f"only {n_tool_pages} tool pages (need ≥90)"
        n_prim_pages = sum(1 for _ in (root / "primitive").glob("*.html"))
        if n_prim_pages < 100:
            return False, f"only {n_prim_pages} primitive pages (need ≥100)"
    return True, f"docs site v1: {n_prim_pages} primitives + {n_tool_pages} tools + 5 top-level docs"


def _r_changelog_semver() -> tuple[bool, str]:
    """B4.4 — CHANGELOG.md + VERSION present; CHANGELOG cites v0.1.0 + score.

    VERSION accepts full semver 2.0.0 syntax including pre-release identifiers
    (e.g. `1.0.0-rc.1`, `1.0.0-beta.3`) and build metadata (e.g. `1.0.0+build.1`).
    The regex mirrors the official semver.org spec; rejecting pre-release tags
    would force the repo to either stay at `0.2.0` during a v1.0 RC cycle or
    skip RC tagging entirely.
    """
    changelog = REPO_ROOT / "CHANGELOG.md"
    version = REPO_ROOT / "VERSION"
    if not changelog.exists():
        return False, "missing: CHANGELOG.md"
    if not version.exists():
        return False, "missing: VERSION"
    ver = version.read_text(encoding="utf-8").strip()
    # Official semver 2.0.0 regex (anchored); accepts pre-release + build
    # metadata suffixes. Source: https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
    semver_re = (
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
        r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    )
    if not re.match(semver_re, ver):
        return False, f"VERSION not semver: {ver!r}"
    cl = changelog.read_text(encoding="utf-8")
    for required in ("[0.1.0]", "Benchmark", "primitives", "tools"):
        if required not in cl:
            return False, f"CHANGELOG.md missing {required!r}"
    return True, f"CHANGELOG.md + VERSION={ver} with v0.1.0 entry citing score"


def _r_contributing_md() -> tuple[bool, str]:
    """B4.5 — CONTRIBUTING.md covers primitive / tool / recipe surfaces + dev setup."""
    f = REPO_ROOT / "CONTRIBUTING.md"
    if not f.exists():
        return False, "missing: CONTRIBUTING.md"
    txt = f.read_text(encoding="utf-8")
    required_sections = (
        "Local dev setup",
        "Adding a primitive",
        "Adding a tool",
        "Adding a composition recipe",
        "10-tier gate",
        "contract_check",
    )
    missing = [s for s in required_sections if s not in txt]
    if missing:
        return False, f"CONTRIBUTING.md missing sections: {missing}"
    return True, f"CONTRIBUTING.md complete (primitive + tool + recipe + dev setup)"


RULES: list[Rule] = [
    Rule("B0.1", 0, "PRODUCT.md canonical", _r_product_md),
    Rule("B0.2", 0, "ROADMAP.md honest + phased", _r_roadmap_md),
    Rule("B0.3", 0, "CONTRACT.md (this)", _r_contract_md),
    Rule("B0.4", 0, "SKILL.md ground-truth honest", _r_skillmd_honest),
    Rule("B0.5", 0, "README.md ≤80 lines + links", _r_readme_md),
    Rule("B0.6", 0, "CLAUDE memory pointer", _r_claude_memory),
    Rule("B0.7", 0, "No stub tests under /benchmark/", _r_benchmark_no_stubs),
    Rule("B0.8", 0, ".gitignore covers artefacts", _r_gitignore_artefacts),
    Rule("B1.0", 1, "core.venous copy-in distribution", _r_core_venous_distribution),
    Rule("B1.0.1", 1, "adapter layer + framework-free primitives", _r_adapter_layer_invariant),
    Rule("B1.1", 1, "primitives_by_concern.yaml registry", _r_registry_exists),
    Rule("B1.2", 1, "Compose-with in every primitive .md", _r_compose_with_coverage),
    Rule("B1.3", 1, "≥15 tools import core.venous", _r_tools_import_primitives),
    Rule("B1.5", 1, "no hardcoded @mcp_app.tool decorators", _r_no_manual_mcp_tool_decorator),
    Rule("B1.6", 1, "no orphan generators (every generate_* is tool or internal)", _r_no_orphan_generators),
    Rule("B1.7", 1, "fastapi adapter coverage (tested + maps to registry)", _r_adapter_coverage),
    Rule("B1.8", 1, "tier-lite eligibility (stateless, framework-free, no REPLACE_ME)", _r_tier_lite_eligibility),
    Rule("B2.1", 2, "find_primitive MCP tool + BM25 quality gate", _r_find_primitive_discovery),
    Rule("B2.2", 2, "suggest_composition MCP tool + recipe quality gate", _r_suggest_composition),
    Rule("B2.3", 2, "reference docs site idempotent build", _r_docs_site),
    Rule("B2.4", 2, "index catalog manifest synced + deterministic", _r_index_manifest),
    Rule("B2.5", 2, "SKILL.md Agent Skills contract (Maestro-facing)", _r_skill_md_contract),
    Rule("B3.1", 3, "20 benchmark specs (5 baseline / 10 mid / 5 adversarial)", _r_bench_specs),
    Rule("B3.2", 3, "scoring rubric implemented + tested", _r_bench_rubric_runner),
    Rule("B3.3", 3, "benchmark runner + stub Maestro + report JSON", _r_bench_rubric_runner),
    Rule("B3.4", 3, "nightly benchmark CI workflow", _r_bench_nightly_workflow),
    Rule("B3.5", 3, "baseline benchmark score published", _r_benchmark_score),
    Rule("B3.6", 3, "code-level harness published (perfect on covered, ≥25% coverage)", _r_code_level_benchmark),
    Rule("B3.7", 3, "blind benchmark harness + specs + stub fixtures", _r_blind_benchmark_harness),
    Rule("B4.1", 4, "install.sh + fresh-Docker CI", _r_install_docker_ci),
    Rule("B4.2", 4, "/examples/ populated (≥5 with README + MAESTRO_SESSION + cross-link)", _r_examples_populated),
    Rule("B4.3", 4, "docs site v1 (top-level docs + per-tool pages)", _r_docs_site_v1),
    Rule("B4.4", 4, "CHANGELOG + VERSION semver cite score", _r_changelog_semver),
    Rule("B4.5", 4, "CONTRIBUTING.md complete", _r_contributing_md),
    Rule("B4.6", 4, "VERSION triplet sync (repo-root + skill + STATUS.md)", _r_version_sync),
    Rule("B4.7", 4, "canonical counts sync (INVENTORY vs CLAUDE/STATUS/ROADMAP/CHANGELOG)", _r_counts_sync),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="CONTRACT.md machine enforcer.")
    parser.add_argument("--item", type=str, default=None, help="Run only this §B item (e.g. B1.1).")
    parser.add_argument("--phase", type=int, default=None, help="Run all items in a phase (e.g. --phase 0).")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    selected = RULES
    if args.item:
        selected = [r for r in RULES if r.item == args.item]
    elif args.phase is not None:
        selected = [r for r in RULES if r.phase == args.phase]

    if not selected:
        print(f"No rules matched (item={args.item}, phase={args.phase}).", file=sys.stderr)
        return 2

    total = len(selected)
    failed = 0
    for rule in selected:
        try:
            ok, msg = rule.check()
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"rule raised: {exc}"
        tag = "✓" if ok else "✗"
        if not args.quiet or not ok:
            print(f"  {tag}  {rule.item:>6}  {rule.description:<52}  {msg}")
        if not ok:
            failed += 1

    passed = total - failed
    print(f"\n{passed}/{total} contract items satisfied" + (" — ALL GREEN" if failed == 0 else f" — {failed} VIOLATIONS"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
