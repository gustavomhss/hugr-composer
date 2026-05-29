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
import contextlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent
# /Users/…/HuGR_Arsenal (one level above skills/)
SKILL_ROOT = REPO_ROOT / "skills" / "SKILL-001-fastapi-production"

# Official semver 2.0.0 regex body (no anchors).
# Source: https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
# Rejects leading zeros (01.0.0), trailing dots (1.0.0-rc..1), empty
# identifiers (1.0.0-), and other malformed shapes that the looser
# Wave-E pattern admitted. Accepts pre-release suffixes (1.0.0-rc.1)
# AND build metadata (1.0.0+build.1). Module-level so every rule
# that touches a version string consumes the same definition —
# Codex v5 M2 flagged the drift between the canonical regex here and
# a looser per-rule copy.
_SEMVER_RE = (
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?"
)


@dataclass(frozen=True)
class Rule:
    item: str  # "B0.5"
    phase: int  # 0..7
    description: str  # short human label
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
    # CONTRACT §B0.5 hard limit. Pre-v1.0 was 80; Wave-F M3 raised to
    # 100 because Wave-E added 5 machine-asserted surface-count lines
    # to the Current-status block, leaving the README sitting at 79/80
    # with no headroom (Sonnet parallel audit). The rule and the
    # contract move together — 100 matches CONTRACT §B0.5 Quality note.
    if lines > 100:
        return False, f"README.md exceeds 100-line hard budget ({lines} lines)"
    for link in ("PRODUCT.md", "ROADMAP.md", "CONTRACT.md"):
        if link not in body:
            return False, f"README.md missing link to {link}"

    # Surface-count guards (post-Codex-v4 M1). The README is the entry
    # doc — Codex v4 flagged it carrying `generators/ # 60 macro
    # scaffold helpers` while INVENTORY said 56. The §B4.7 counts-sync
    # rule scopes its checks to the seven narrative docs it owns; the
    # repo-root README was not among them, so drift here was invisible.
    # We parse INVENTORY for the canonical primitive / adapter / staged
    # / quarantined / generators totals, then assert each appears in
    # README at the specific drift-prone shape.
    inv_path = SKILL_ROOT / "INVENTORY.md"
    if not inv_path.exists():
        return False, "INVENTORY.md missing — run `python -m engine.inventory`"
    inv = inv_path.read_text(encoding="utf-8")
    patterns = {
        "registered": r"\*\*(\d+) registered primitives\*\*",
        "staged": r"\*\*(\d+) staged primitives\*\*",
        "quarantined": r"staged primitives\*\* in `_staging/` \(plus (\d+) quarantined\)",
        "adapters": r"\*\*(\d+) FastAPI adapters\*\*",
        # Section numbering shifted in WAVE-0-F2 (catalog schema v2 /
        # ADR-0003): `## 2. Skills × Bundles` was inserted between
        # `## 1. adapt/` and the former `## 2. generators/`, pushing
        # generators to `## 3.`. Same content, new offset.
        "generators": r"## \d+\. generators/ — (\d+) tools",
        "adapt_total": r"## \d+\. adapt/ — (\d+) tools",
    }
    canon: dict[str, int] = {}
    for label, pat in patterns.items():
        m = re.search(pat, inv)
        if not m:
            return False, (
                f"INVENTORY.md missing `{label}` headline "
                f"(pattern `{pat}`) — regenerate via `python -m engine.inventory`"
            )
        canon[label] = int(m.group(1))

    # Sonnet parallel audit (Wave-F L1) flagged earlier tokens that
    # depended on trailing whitespace (`"# 127 tools "`, `"Primitives:
    # 124 "`) — a single reformat that collapses a space would
    # silently fail the check. Every token is now a regex tolerating
    # whitespace variation; the user-facing `expected` message is
    # built from a shape hint rather than the raw pattern, so
    # maintenance stays readable.
    required_tokens: list[tuple[str, str, str]] = [
        # (regex, shape-hint-for-error-message, label)
        # `├── generators/           # 56 macro scaffold helpers`
        (
            rf"#\s+{canon['generators']}\s+macro\s+scaffold\s+helpers",
            f"# {canon['generators']} macro scaffold helpers",
            "architecture-tree `generators/` comment",
        ),
        # `├── adapt/                # 127 tools (100 extend + 27 other)`
        (
            rf"#\s+{canon['adapt_total']}\s+tools(?:[\s(]|$)",
            f"# {canon['adapt_total']} tools (…)",
            "architecture-tree `adapt/` comment",
        ),
        # Status-block line: `Primitives: 124  (…)`
        (
            rf"Primitives:\s+{canon['registered']}(?:[\s(]|$)",
            f"Primitives: {canon['registered']} (…)",
            "'Current status' `Primitives:` line",
        ),
        # Status-block line: `Staged:    176   (…, +42 quarantined, …)`
        (
            rf"Staged:\s+{canon['staged']}(?:[\s(]|$)",
            f"Staged: {canon['staged']} (…)",
            "'Current status' `Staged:` line",
        ),
        (
            rf"\+{canon['quarantined']}\s+quarantined",
            f"+{canon['quarantined']} quarantined",
            "'Current status' quarantined subtotal",
        ),
        # Architecture tree summary:
        # `core/venous/          # 124 primitives + 17 FastAPI adapters (…) + 176 staged`
        (
            rf"#\s+{canon['registered']}\s+primitives\s+\+\s+{canon['adapters']}\s+FastAPI\s+adapters",
            f"# {canon['registered']} primitives + {canon['adapters']} FastAPI adapters",
            "architecture-tree `core/venous/` comment",
        ),
    ]
    missing: list[str] = []
    for pattern, hint, label in required_tokens:
        if not re.search(pattern, body):
            missing.append(f"expected `{hint}`  ({label})")
    if missing:
        return False, (
            "README.md surface counts do not match INVENTORY.md:\n  " + "\n  ".join(missing)
        )

    # Install stub must be present — B0.5 requires README to point at
    # the fresh-clone path; regression would land people in a
    # doc that lists canonical-doc links but no way to actually install.
    if "install.sh" not in body:
        return False, "README.md missing reference to `install.sh` (fresh-clone path)"

    return True, (
        f"README.md present, {lines} lines, links to canonical docs, "
        f"surface counts match INVENTORY "
        f"(generators={canon['generators']}, adapt={canon['adapt_total']}, "
        f"primitives={canon['registered']}, staged={canon['staged']})"
    )


def _r_agent_memory_pointer() -> tuple[bool, str]:
    """B0.6 — repo-local agent-memory pointer is committed + canonical.

    The acceptance-gate contract (``docs/wp/WP-CONTRACT-TEMPLATE.md``)
    requires every ``B*`` item to be a deterministic function of the
    working tree. The pre-C2 version of this rule read
    ``~/.claude/projects/.../venous_architecture.md`` — a per-developer
    artefact that lives **outside** the repo. A fresh clone or a CI
    runner therefore failed B0.6 for reasons unrelated to repository
    state, which broke the "37/37 deterministic gate" promise the WPs
    make to builders.

    The repo-local replacement is ``engine/audit/AGENT_MEMORY_POINTER.md``
    — a small committed file that names the canonical contract surface
    (PRODUCT.md + CONTRACT.md). This rule passes iff that file exists
    AND mentions both, so the pointer cannot silently drift away from
    the two documents the rest of the §B0 gate hinges on.
    """
    pointer = SKILL_ROOT / "engine" / "audit" / "AGENT_MEMORY_POINTER.md"
    ok, msg = _exists(pointer, min_bytes=200)
    if not ok:
        return ok, msg
    body = pointer.read_text(encoding="utf-8")
    missing = [s for s in ("PRODUCT.md", "CONTRACT.md") if s not in body]
    if missing:
        return False, f"AGENT_MEMORY_POINTER.md missing pointer to: {missing}"
    return True, f"agent memory pointer ok: {pointer.relative_to(REPO_ROOT)}"


def _r_skillmd_honest() -> tuple[bool, str]:
    """§B0.4 — SKILL.md body-prose counts reconcile against disk.

    Scope (post-Codex-v3 B1 rewrite): this rule is a narrow drift-
    detector on body-prose count claims — specifically, the
    "N adapt tools" pattern that has historically drifted across
    sprints. The full SKILL.md shape (Anthropic frontmatter,
    body-metadata YAML, transcripts, entry_tools validity) is
    enforced by `_r_skill_md_contract` (§B2.5). Overview-paragraph
    counts are enforced by `_r_counts_sync` (§B4.7, SKILL.md[Overview]
    scope). §B0.4 sits alongside those two — cheap sanity check, not
    a schema validator.
    """
    path = SKILL_ROOT / "SKILL.md"
    ok, msg = _exists(path, min_bytes=500)
    if not ok:
        return ok, msg
    body = path.read_text()
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


# Exemption patterns for B0.9 — discontinued-terminology audit.
# These paths are HISTORICAL audit records (analogous to ``docs/legacy/``):
# committed transcripts, staged stubs, blind-benchmark fixtures + results.
# A future contributor MUST be able to read the original wording in these
# paths verbatim — rewriting them silently would erase the audit trail.
# PRODUCT.md §8 is also exempt: the canonical terminology lock explicitly
# documents the discontinued ``Maestro`` term as a historical note (see
# the 2026-05-26 pivot in ``memory/product_business_model.md``).
_B09_LEGACY_TERM_EXEMPTIONS = (
    ".git/",
    ".claude/",
    "docs/legacy/",
    "core/venous/_staging/",
    "core/venous/_extracted/",
    "benchmarks/blind/_stub_fixtures/",
    "benchmarks/blind/results/",
    "evidence/external-eval/reviewer_signoffs/transcripts/wave-i-1__",
    # PRODUCT.md carries the canonical historical-note (see §8).
    "PRODUCT.md",
    # This rule's own source file MUST mention the discontinued term to
    # define + document the audit; exempting the file avoids a
    # self-referential false positive.
    "skills/SKILL-001-fastapi-production/engine/audit/contract_check.py",
)


def _r_no_legacy_terminology() -> tuple[bool, str]:
    """B0.9 — no live-tree references to discontinued ``Maestro`` term.

    The "Maestro" project (a custom HuGR-authored harness) was
    discontinued on 2026-05-26 (see
    ``memory/product_business_model.md``). The product pivot makes the
    user's own first-party agent (Claude Code / Cursor / Cline / Zed /
    any compliant MCP client) the consumer of the skill — HuGR does NOT
    ship a custom harness. From the pivot onward, the canonical noun is
    ``agent``.

    This rule fails CI if any LIVE doc/code/yaml file under the repo
    reintroduces ``\\bmaestro\\b`` (case-insensitive). Historical
    audit records (transcripts, staging pools, blind-benchmark fixtures
    + results, PRODUCT.md §8 terminology-lock historical note,
    ``docs/legacy/`` archive) are exempted via
    ``_B09_LEGACY_TERM_EXEMPTIONS`` — silently rewriting them would
    erase the audit trail.
    """
    pattern = re.compile(r"\bmaestro\b", re.IGNORECASE)
    suffixes = (".md", ".py", ".yaml", ".yml")
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in suffixes:
            continue
        try:
            rel = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            continue
        if any(ex in rel for ex in _B09_LEGACY_TERM_EXEMPTIONS):
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pattern.search(body):
            hits.append(rel)
    if hits:
        sample = sorted(hits)[:3]
        return (
            False,
            f"{len(hits)} live-doc/code references to discontinued 'Maestro' term: {sample}",
        )
    return True, "no legacy 'Maestro' refs in live tree"


def _r_benchmark_no_stubs() -> tuple[bool, str]:
    """B0.7 — zero trivial-stub test functions anywhere in the skill.

    Scans three roots: ``benchmark/``, ``benchmarks/``, and the
    production primitive tree ``core/venous/`` (excluding
    ``_staging/`` because that's the staging pool; stub tests there
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
    scan_roots = [
        SKILL_ROOT / "benchmark",
        SKILL_ROOT / "benchmarks",
        SKILL_ROOT / "core" / "venous",
    ]
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
            if "_staging" in py.parts:
                continue
            body = py.read_text()
            for m in _stub_body_re.finditer(body):
                fn_name = m.group(1)
                stubs.append(f"{py.relative_to(REPO_ROOT)}::{fn_name}")
    if stubs:
        sample = "\n    - ".join(stubs[:5])
        return False, (
            f"{len(stubs)} stub test function(s) with pure `assert True` body:\n"
            f"    - {sample}" + ("\n    …" if len(stubs) > 5 else "")
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
        if any(part in d.parts for part in ("_staging", "_adapters", "__pycache__")):
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
        str(d.relative_to(venous)) for d in all_leaf_dirs if not (d / f"{d.name}.md").exists()
    )
    if half_extracted:
        return False, (
            f"{len(half_extracted)} half-extracted dirs under production namespaces "
            f"(no matching .md) — move to _staging/ or complete them: {half_extracted[:5]}"
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
        return (
            False,
            f"{len(missing_section)} primitives lack 'Compose with:' section: {missing_section[:3]}",
        )
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
        t
        for t in cat.get("tools", [])
        if t.get("verb") == "add"
        and t.get("module_path", "").startswith("adapt/extend/")
        and t.get("primitives_used")
    ]
    floor = 22
    if len(connected) < floor:
        return False, (
            f"only {len(connected)}/100 extend add_* tools import primitives "
            f"(floor={floor}; regression bars PR)"
        )
    return True, (
        f"{len(connected)}/100 extend add_* tools primitive-connected "
        f"(floor={floor}, §B1.3 Rails-style wiring)"
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
            "Demote violating primitives to `_staging/` or promote at full tier."
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
            f"VERSION mismatch: skill/VERSION={skill_v!r} vs STATUS.md frontmatter={status_v!r}"
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
        ("quarantined", r"staged primitives\*\* in `_staging/` \(plus (\d+) quarantined\)"),
        ("adapters", r"\*\*(\d+) FastAPI adapters\*\*"),
        # Schema v2 hierarchical headline shape (ADR-0003):
        #   **Catalog:** 1 skill, 6 bundles, 201 tools (201 local + 0
        #   federated), 299 primitives, 392 recipes.
        # Each field is captured independently so future federation
        # handoff (tools_federated > 0) doesn't require this rule to
        # move again.
        ("cat_skills", r"\*\*Catalog:\*\* (\d+) skill"),
        ("cat_bundles", r"\*\*Catalog:\*\* \d+ skills?, (\d+) bundle"),
        ("cat_tools", r"\*\*Catalog:\*\* \d+ skills?, \d+ bundles?, (\d+) tools"),
        ("cat_primitives", r"\(\d+ local \+ \d+ federated\), (\d+) primitives"),
        ("recipes", r"\(\d+ local \+ \d+ federated\), \d+ primitives, (\d+) recipes"),
    ]
    canon: dict[str, int] = {}
    for label, pat in checks:
        value, err = _int(pat, label)
        if err:
            return False, err
        canon[label] = value

    # Cross-check: the INVENTORY.md `**Catalog:**` headline MUST match
    # engine/index/catalog.json exactly. Drift between these was the failure
    # mode the WAVE-0-F0 rename surfaced: catalog.json was regenerated against
    # an incomplete path-string update and reported 124 primitives, while
    # INVENTORY.md's headline read 299. Both passed their existing rules in
    # isolation (B2.4 only checks the catalog hash; this rule only reads
    # INVENTORY against itself), so a half-truth green was possible. Holding
    # the two against each other closes the gap.
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog_path.exists():
        return (
            False,
            "engine/index/catalog.json missing — run `python -m engine.index.manifest build`",
        )
    try:
        _cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"catalog.json malformed: {exc}"
    _cat_counts = _cat.get("counts", {})
    # Schema v2 (ADR-0003): the headline now carries skills + bundles +
    # tools_total alongside primitives + recipes. Each field is checked
    # against catalog.json's hierarchical counts. The skill array length
    # is also asserted against counts.skills, and the sum of bundle
    # entries against counts.bundles — closing the I3 invariant that
    # catalog.json's flat counts cannot drift from its own structure.
    skills_array_len = len(_cat.get("skills", []))
    bundles_array_len = sum(len(s.get("bundles", [])) for s in _cat.get("skills", []))
    if int(_cat_counts.get("skills", -1)) != skills_array_len:
        return False, (
            f"catalog.json counts.skills={_cat_counts.get('skills')} "
            f"!= len(catalog.skills)={skills_array_len} — manifest "
            "build emitted inconsistent counts; regenerate."
        )
    if int(_cat_counts.get("bundles", -1)) != bundles_array_len:
        return False, (
            f"catalog.json counts.bundles={_cat_counts.get('bundles')} "
            f"!= sum(len(s.bundles))={bundles_array_len} — manifest "
            "build emitted inconsistent counts; regenerate."
        )
    for inv_key, cat_key in (
        ("cat_skills", "skills"),
        ("cat_bundles", "bundles"),
        ("cat_tools", "tools_total"),
        ("cat_primitives", "primitives"),
        ("recipes", "recipes"),
    ):
        inv_value = canon[inv_key]
        cat_value = int(_cat_counts.get(cat_key, -1))
        if inv_value != cat_value:
            return False, (
                f"INVENTORY.md `**Catalog:**` headline {cat_key}={inv_value} "
                f"contradicts catalog.json counts.{cat_key}={cat_value} — "
                "regenerate INVENTORY.md AFTER catalog.json: "
                "`python -m engine.index.manifest build && python -m engine.inventory`"
            )

    # Ledger total is machine-verified from LEDGER.md, not INVENTORY.md
    # (the ledger is generated by engine.promotion.ledger, not the inventory
    # scanner). Ledger count drifts have shipped past INVENTORY-only checks
    # before — e.g. FREEZE.md saying "229-entry" while LEDGER.md was at 219.
    ledger_md = SKILL_ROOT / "engine" / "promotion" / "LEDGER.md"
    if not ledger_md.exists():
        return False, "engine/promotion/LEDGER.md missing — run `python -m engine.promotion.ledger`"
    m = re.search(r"\*\*Total:\*\* (\d+)", ledger_md.read_text(encoding="utf-8"))
    if not m:
        return False, "LEDGER.md first line missing `**Total:** N` headline"
    canon["ledger"] = int(m.group(1))

    # Verdict subtotals come from engine/promotion/ledger.json so narrative
    # docs citing e.g. "104 NEEDS_CALLER" are held to the classifier's
    # own count, not a frozen pre-freeze number. Codex v3 H5 flagged the
    # drift — FREEZE §2.5 said 104, reality was 101 after Wave 1.5.
    ledger_json = SKILL_ROOT / "engine" / "promotion" / "ledger.json"
    if not ledger_json.exists():
        return (
            False,
            "engine/promotion/ledger.json missing — run `python -m engine.promotion.classify`",
        )
    try:
        _data = json.loads(ledger_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"ledger.json malformed: {exc}"
    _verdicts: dict[str, int] = {}
    for _e in _data.get("entries", []):
        _v = _e.get("verdict", "")
        _verdicts[_v] = _verdicts.get(_v, 0) + 1
    canon["needs_caller"] = _verdicts.get("needs_caller", 0)
    canon["extract_motor_pair"] = _verdicts.get("extract_motor_pair", 0)

    narrative_docs = {
        "CLAUDE.md": REPO_ROOT / "CLAUDE.md",
        "STATUS.md": SKILL_ROOT / "STATUS.md",
        "ROADMAP.md": REPO_ROOT / "ROADMAP.md",
        "CHANGELOG.md[1.0.0]": REPO_ROOT / "CHANGELOG.md",
        # SKILL.md added here post-Codex-audit (BLOCKER #2).
        # The overview paragraph is the agent's first read — it MUST carry
        # the current canonical counts, not pre-Wave-1.5 values. The check
        # only looks at the single paragraph under `## Overview` (not the
        # few-shot transcript counts, which are illustrative).
        "SKILL.md[Overview]": SKILL_ROOT / "SKILL.md",
        # FREEZE.md §1.3 documents the ledger size as part of the frozen
        # release-surface claim. A count drift here means the freeze
        # artefact disagrees with what LEDGER.md actually ships. §2.5
        # cites the NEEDS_CALLER verdict subtotal — held to ledger.json.
        "FREEZE.md": REPO_ROOT / "FREEZE.md",
        # INTERFACES.md §2.3 cites the recipe count in the Forge/agent
        # consumer contract. Codex v3 H5 caught this drifting to 385
        # while catalog + ROADMAP were at 392 — a host impl against the
        # doc would mis-size its search index.
        "INTERFACES.md": REPO_ROOT / "INTERFACES.md",
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
            f"| Recipes | {canon['recipes']} |",
            f"| Ledger entries | {canon['ledger']} |",
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
        "FREEZE.md": [
            # Shape: "LEDGER.md — 219-entry triage ledger …".
            f"{canon['ledger']}-entry triage ledger",
            # Shape: "### §2.5 — 101 NEEDS_CALLER items". Subtotal must
            # match the classifier's own ledger.json output (Codex v3 H5).
            f"{canon['needs_caller']} NEEDS_CALLER items",
        ],
        "INTERFACES.md": [
            # Shape: "**392 recipes** parsed from primitive `.md` …".
            f"**{canon['recipes']} recipes**",
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
        f"narrative docs (incl. SKILL.md Overview + FREEZE.md + "
        f"INTERFACES.md) match INVENTORY + LEDGER + catalog v2: "
        f"{canon['cat_skills']} skill / {canon['cat_bundles']} bundles / "
        f"{canon['cat_tools']} tools / "
        f"{canon['registered']} reg / {canon['staged']} staged / "
        f"{canon['quarantined']} qtn / {canon['adapters']} adapters / "
        f"{canon['recipes']} recipes / {canon['ledger']} ledger "
        f"({canon['needs_caller']} needs_caller, "
        f"{canon['extract_motor_pair']} extract_motor_pair)"
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
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            floor = max(floor, float(json.loads(floorfile.read_text()).get("floor", 30.0)))

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

    adapters = [f for f in adapters_dir.glob("*.py") if not f.name.startswith(("_", "test_"))]
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
        "WebhookReceiver": {"SignatureVerifier", "IdempotentConsumer", "InboxDeduplicator"},
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
            Path(tmp)
            / "core"
            / "venous"
            / "resiliency"
            / "GracefulShutdown"
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
    # imports; ignore _adapters/ and _staging/ which are out of scope.
    # Match only real top-of-line imports (not strings / comments).
    pat = re.compile(r"^\s*(?:from|import)\s+(fastapi|starlette|sqlalchemy)\b", re.MULTILINE)
    leaks: list[str] = []
    venous = SKILL_ROOT / "core" / "venous"
    for py in venous.rglob("*.py"):
        parts = py.parts
        if "_adapters" in parts or "_staging" in parts or "__pycache__" in parts:
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
    bases = (
        "generators",
        "core/tools",
        "modules/database/tools",
        "modules/security/tools",
        "benchmark",
    )

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
        sys.executable,
        "-m",
        "engine.discovery.compose_bench",
        "--min-top-1",
        "0.70",
        "--min-p-at-3",
        "0.90",
    ]
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

    cmd = [
        sys.executable,
        "-c",
        (
            "from mcp_tools import mcp, discover_and_register; "
            "discover_and_register(mcp); "
            "import asyncio; "
            "t = asyncio.run(mcp.get_tool('fastapi_meta_search_composition')); "
            "assert t.name == 'fastapi_meta_search_composition', t.name; print('ok')"
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
            sys.executable,
            "-m",
            "engine.docs.build",
            "--out",
            tmp,
            "--verify",
        ]
        out = subprocess.run(
            cmd,
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
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

        registry = _yaml.safe_load(
            (SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text()
        )
        missing = [
            e["name"]
            for e in registry["primitives"]
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
    """B2.5 — SKILL.md follows the Agent Skills contract for agent consumption.

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
    body = raw[end_fence + 5 :]

    # 2. Frontmatter YAML parses
    try:
        import yaml

        fm = yaml.safe_load(fm_text) or {}
    except Exception as exc:  # noqa: BLE001
        return False, f"SKILL.md frontmatter YAML invalid: {exc}"

    # 2a. Frontmatter key-set is EXACTLY the Anthropic Agent Skills
    #     shape. INTERFACES §3.1 promises "exactly three keys — `name`,
    #     `description`, `license` — nothing else" and says the check
    #     is machine-verified here. `license` is optional; `name` +
    #     `description` are required. Any unknown key (e.g. legacy
    #     `version`, `tools_count`) must be rejected — those belong in
    #     the body `## Machine-readable metadata` YAML block, not the
    #     frontmatter. Codex v3 H6 flagged the claim/impl gap.
    _allowed_fm_keys = {"name", "description", "license"}
    _actual_fm_keys = set(fm.keys())
    _unknown = _actual_fm_keys - _allowed_fm_keys
    if _unknown:
        return False, (
            f"SKILL.md frontmatter has unexpected keys {sorted(_unknown)}; "
            "only {name, description, license} allowed per INTERFACES §3.1. "
            "HuGR metadata (version, entry_tools, etc.) belongs in the body "
            "`## Machine-readable metadata` YAML block."
        )

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

    # 3a. `license` MUST be a valid SPDX identifier when present
    #     (CONTRACT §B2.5 DoD). Supporting the common-case set below
    #     covers >95% of real usage; if a skill needs something exotic,
    #     it can be added here rather than silently accepted. Codex v3
    #     H6 flagged the missing check.
    _spdx_known = frozenset(
        {
            "Apache-2.0",
            "MIT",
            "BSD-2-Clause",
            "BSD-3-Clause",
            "ISC",
            "MPL-2.0",
            "Unlicense",
            "CC0-1.0",
            "GPL-2.0-only",
            "GPL-2.0-or-later",
            "GPL-3.0-only",
            "GPL-3.0-or-later",
            "LGPL-2.1-only",
            "LGPL-2.1-or-later",
            "LGPL-3.0-only",
            "LGPL-3.0-or-later",
            "AGPL-3.0-only",
            "AGPL-3.0-or-later",
            "Proprietary",
        }
    )
    license_val = fm.get("license")
    if license_val is not None:
        if not isinstance(license_val, str) or not license_val.strip():
            return False, "SKILL.md frontmatter `license` must be a non-empty string when present"
        if license_val not in _spdx_known:
            return False, (
                f"SKILL.md license {license_val!r} is not in the supported "
                f"SPDX identifier set. Use one of {sorted(_spdx_known)}, or "
                "extend `_spdx_known` in contract_check.py if the target "
                "is genuinely new."
            )
        # 3b. License MUST be consistent with the repo-root LICENSE file.
        #     Codex v5 B1 caught the agent-facing SKILL.md advertising
        #     `Apache-2.0` while the shipped LICENSE is proprietary —
        #     a legal/compliance drift, not a cosmetic one. This map
        #     links each SPDX identifier to a signature we can detect in
        #     the LICENSE file header. Sonnet v6 parallel audit (L1)
        #     flagged that the initial Wave-F coverage only handled 9
        #     of the 19 SPDX identifiers — the 10 GPL/LGPL/AGPL
        #     variants silently passed the signature check. Wave G
        #     closes the coverage gap below. Unknown licenses (any SPDX
        #     identifier NOT in this map) still fail the SPDX-set gate
        #     above; they never reach the signature check.

        def _gnu_sig(family: str, version: str, or_later: bool):
            """Build a signature lambda for GPL/LGPL/AGPL variants.

            `family` is the license family header text (e.g.
            "gnu general public license"). `version` is the version
            string ("version 2", "version 3", "version 2.1"). The
            `or_later` flag distinguishes `-only` from `-or-later` —
            "or-later" LICENSE headers cite "(at your option) any
            later version"; "only" variants do not.
            """

            def check(t: str) -> bool:
                tl = t.lower()
                if family not in tl:
                    return False
                if version not in tl[:800]:
                    return False
                has_or_later = "any later version" in tl[:2000]
                return has_or_later if or_later else not has_or_later

            return check

        _license_signatures: dict[str, callable] = {
            "Proprietary": lambda t: "proprietary" in t.lower()[:400],
            "Apache-2.0": lambda t: (
                "apache license" in t.lower() and "version 2.0" in t.lower()[:500]
            ),
            "MIT": lambda t: "mit license" in t.lower()[:400],
            "BSD-2-Clause": lambda t: (
                "redistribution and use" in t.lower() and "bsd" in t.lower()[:400]
            ),
            "BSD-3-Clause": lambda t: (
                "redistribution and use" in t.lower() and "bsd" in t.lower()[:400]
            ),
            "ISC": lambda t: "isc license" in t.lower()[:400],
            "MPL-2.0": lambda t: "mozilla public license" in t.lower()[:400],
            "Unlicense": lambda t: "unlicense" in t.lower()[:400],
            "CC0-1.0": lambda t: "cc0" in t.lower()[:400],
            # GPL family (4 variants)
            "GPL-2.0-only": _gnu_sig("gnu general public license", "version 2", or_later=False),
            "GPL-2.0-or-later": _gnu_sig("gnu general public license", "version 2", or_later=True),
            "GPL-3.0-only": _gnu_sig("gnu general public license", "version 3", or_later=False),
            "GPL-3.0-or-later": _gnu_sig("gnu general public license", "version 3", or_later=True),
            # LGPL family (4 variants)
            "LGPL-2.1-only": _gnu_sig(
                "gnu lesser general public license", "version 2.1", or_later=False
            ),
            "LGPL-2.1-or-later": _gnu_sig(
                "gnu lesser general public license", "version 2.1", or_later=True
            ),
            "LGPL-3.0-only": _gnu_sig(
                "gnu lesser general public license", "version 3", or_later=False
            ),
            "LGPL-3.0-or-later": _gnu_sig(
                "gnu lesser general public license", "version 3", or_later=True
            ),
            # AGPL family (2 variants)
            "AGPL-3.0-only": _gnu_sig(
                "gnu affero general public license", "version 3", or_later=False
            ),
            "AGPL-3.0-or-later": _gnu_sig(
                "gnu affero general public license", "version 3", or_later=True
            ),
        }
        # Invariant: every SPDX identifier in _spdx_known MUST have a
        # signature lambda. Skipping coverage would let a future
        # SKILL.md carry `license: GPL-3.0-only` against a proprietary
        # LICENSE with no detection — the exact B1 class we closed.
        _uncovered_spdx = _spdx_known - _license_signatures.keys()
        if _uncovered_spdx:
            return False, (
                f"_license_signatures missing coverage for SPDX "
                f"identifier(s) {sorted(_uncovered_spdx)} — every "
                f"identifier in _spdx_known must have a signature "
                f"lambda, otherwise the LICENSE-match gate silently "
                f"skips for those licenses."
            )
        license_file = REPO_ROOT / "LICENSE"
        if not license_file.exists():
            return False, (
                "repo-root LICENSE file missing — cannot validate SKILL.md "
                "`license` field against the real license text"
            )
        license_text = license_file.read_text(encoding="utf-8")
        # Post-Wave-G: coverage gate above guarantees sig is not None
        # for any `license_val` that passed the SPDX-set check. We
        # still defensively default-check to handle the hypothetical
        # case of someone adding to `_spdx_known` without updating the
        # signatures — though the coverage gate should fire first.
        sig = _license_signatures[license_val]
        if not sig(license_text):
            return False, (
                f"SKILL.md license {license_val!r} does not match the repo-root "
                f"LICENSE file header; the entry doc is advertising a license "
                f"the repo does not ship. Align SKILL.md with LICENSE or update "
                f"both together."
            )

    # 4. `description` field (Anthropic spec + CONTRACT §B2.5 DoD)
    #    DoD says 800-1200 chars. Lower floor matters: a too-short
    #    description ends up as a bare tagline without the "use when"
    #    triggers + "do not" anti-triggers the agent needs to route.
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return False, "SKILL.md frontmatter missing `description`"
    if not (800 <= len(desc) <= 1200):
        return False, (
            f"SKILL.md description length {len(desc)} outside "
            "CONTRACT §B2.5 DoD range (800-1200 chars)"
        )
    if "<" in desc or ">" in desc:
        return False, "SKILL.md description cannot contain XML tags (`<`/`>`)"
    first_word = desc.strip().split(None, 1)[0].lower()
    if first_word in {"i", "you", "we"}:
        return False, (f"SKILL.md description must be third-person (starts with {first_word!r})")

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
        return False, f"SKILL.md body >5000 tokens (estimate {len(body) // 4})"

    # 7. Required H2 sections
    required_sections = (
        "## Overview",
        "## When to use",
        "## When NOT to use",
        "## Machine-readable metadata",
        "## Workflow phases",
        "## Tier-1 tool index",
        "## Few-shot transcripts",
        "## Anti-patterns",
        "## Reference files",
    )
    missing_sections = [s for s in required_sections if s not in body]
    if missing_sections:
        return False, f"SKILL.md missing required sections: {missing_sections[:3]}"

    # 8. Machine-readable metadata fenced YAML
    meta_block = re.search(
        r"## Machine-readable metadata\s*\n\s*```yaml\n(.*?)\n```", body, re.DOTALL
    )
    if not meta_block:
        return False, "SKILL.md missing fenced ```yaml block under 'Machine-readable metadata'"
    try:
        meta = yaml.safe_load(meta_block.group(1)) or {}
    except Exception as exc:  # noqa: BLE001
        return False, f"SKILL.md machine-readable metadata YAML invalid: {exc}"
    for required_key in (
        "hugr_skill_version",
        "spec_compat",
        "kind",
        "domains",
        "entry_tools",
        "catalog_path",
        "phases",
        "invariants",
    ):
        if required_key not in meta:
            return False, f"SKILL.md machine-readable metadata missing `{required_key}`"

    # 9. `hugr_skill_version` semver + equality with VERSION file.
    #    VERSION is the canonical pin (§B4.6 triplet). SKILL.md is the
    #    agent-facing entry doc — if they diverge, the entry doc is
    #    lying about what shipped. Accepts pre-release suffixes
    #    (e.g. `1.0.0-rc.1`) + build metadata (`+build.1`). Uses the
    #    module-level _SEMVER_RE (official semver.org spec) so Wave-E's
    #    looser pattern that accepted invalid strings like `01.0.0` and
    #    `1.0.0-rc..1` (Codex v5 M2) cannot recur.
    meta_version = str(meta["hugr_skill_version"])
    if not re.fullmatch(_SEMVER_RE, meta_version):
        return False, (
            f"hugr_skill_version must be semver per semver.org "
            f"(e.g. '1.0.0' or '1.0.0-rc.1'); got {meta_version!r}"
        )
    version_file = SKILL_ROOT / "VERSION"
    if not version_file.exists():
        return False, "VERSION file missing at skill root"
    canonical_version = version_file.read_text().strip()
    if meta_version != canonical_version:
        return False, (
            f"SKILL.md hugr_skill_version ({meta_version!r}) does not match "
            f"VERSION file ({canonical_version!r}); the entry doc is "
            f"advertising a version that has not been cut"
        )

    # 10. catalog_path exists + valid JSON with expected keys
    cat = SKILL_ROOT / str(meta["catalog_path"])
    if not cat.exists():
        return False, f"catalog_path does not exist: {cat.relative_to(SKILL_ROOT)}"
    try:
        cat_data = json.loads(cat.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"catalog_path file malformed: {exc}"
    # Schema v2 adds `skills` as a required top-level key (ADR-0003).
    for k in ("schema_version", "skills", "tools", "primitives", "recipes", "counts"):
        if k not in cat_data:
            return False, f"catalog.json missing top-level key {k!r}"

    # 11. Every entry_tool exists in the registered MCP tool surface.
    #     The non-catalog tool surface = tier-1 meta tools +
    #     domain-tree dispatchers. Codex v5 H1 caught the earlier
    #     hardcoded set missing 8 of the 9 dispatchers — transcripts
    #     or entry_tools using e.g. `fastapi_data` / `fastapi_resiliency`
    #     would have been rejected as "unknown". We now derive the
    #     dispatcher surface from `mcp_tools/tree/*.py` at check time
    #     so adding a new tree module auto-extends the allowlist.
    cat_tool_names = {t.get("name") for t in cat_data.get("tools", [])}
    tier1_meta = {
        "fastapi_meta_home",
        "fastapi_meta_search",
        "fastapi_meta_describe",
        "fastapi_meta_scaffold",
        "fastapi_meta_compose",
        "fastapi_meta_audit",
        "fastapi_meta_verify",
        "fastapi_meta_search_primitive",
        "fastapi_meta_search_composition",
    }
    tree_dir = SKILL_ROOT / "mcp_tools" / "tree"
    tree_dispatcher_names: set[str] = set()
    if tree_dir.is_dir():
        _name_re = re.compile(r"""['"]name['"]\s*:\s*['"]([A-Za-z0-9_]+)['"]""")
        # Sonnet parallel audit (Wave-F M1) flagged that the raw-text
        # scan would over-include: a Python comment containing
        # `'name': 'fastapi_fake'` would seed the allowlist with a
        # phantom tool. Strip line comments (# ...) before scanning so
        # commented-out examples / doctest fixtures can't leak in.
        # Docstrings are not stripped — we rely on the fact that
        # MCP_TOOL dict literals are never written inside docstrings in
        # this codebase (and the §B2.6 rule would catch it if they were).
        _line_comment_re = re.compile(r"#.*$", re.MULTILINE)
        for py_file in tree_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            text = _line_comment_re.sub("", py_file.read_text(encoding="utf-8"))
            for m in _name_re.finditer(text):
                if m.group(1).startswith("fastapi_"):
                    tree_dispatcher_names.add(m.group(1))
    known_non_catalog = tier1_meta | tree_dispatcher_names
    valid_tool_names = cat_tool_names | known_non_catalog
    missing_tools = [t for t in meta.get("entry_tools", []) if t not in valid_tool_names]
    if missing_tools:
        return False, (f"SKILL.md entry_tools reference unknown tools: {missing_tools[:3]}")

    # 12. Few-shot transcripts ≥ 3 (CONTRACT §B2.5 DoD: "≥ 3 few-shot
    #     transcripts under `## Few-shot transcripts`"). No upper bound —
    #     more transcripts = better agent grounding, not worse.
    transcripts_section = re.search(
        r"## Few-shot transcripts(.+?)(?=\n## )",
        body,
        re.DOTALL,
    )
    if not transcripts_section:
        return False, "SKILL.md 'Few-shot transcripts' section missing body"
    transcripts = re.findall(r"```[^\n]*\n(.*?)```", transcripts_section.group(1), re.DOTALL)
    if len(transcripts) < 3:
        return False, (
            f"SKILL.md must include ≥3 few-shot transcripts per CONTRACT "
            f"§B2.5 DoD; got {len(transcripts)}"
        )

    # 12b. Every `fastapi_*` token cited inside transcripts must resolve
    #      against the real catalog surface (or the known meta/dispatcher
    #      set). Prevents regressing to stale tool names like
    #      `fastapi_add_stripe_billing` that no longer exist — transcripts
    #      are the highest-weight agent steering examples.
    transcript_body = transcripts_section.group(1)
    cited = set(re.findall(r"\bfastapi_[a-zA-Z0-9_]+", transcript_body))
    unknown = sorted(cited - valid_tool_names)
    if unknown:
        return False, (
            f"SKILL.md transcripts cite unknown fastapi_* tool(s): "
            f"{unknown[:3]}. Every `fastapi_*` token in a transcript "
            f"must resolve against catalog.json or the known meta/tree "
            f"dispatcher set."
        )

    # 13. No forbidden drift heuristics (STATUS/ROADMAP territory)
    forbidden = ("benchmark score", "test count", "sprint", "Phase 4 complete")
    hits = [f for f in forbidden if f.lower() in body.lower()]
    if hits:
        return False, (
            f"SKILL.md contains forbidden drift-prone phrases: {hits}. Move these to STATUS.md."
        )

    # 14. No XML tags in the body (excluding backticked code / placeholders)
    body_stripped = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    body_stripped = re.sub(r"`[^`]*`", "", body_stripped)
    # Real XML tags have a closing `>` with letters inside, or a `/` prefix.
    # `<slug>` placeholder style is ambiguous; we focus on unambiguous XML.
    if re.search(
        r"</[A-Za-z][A-Za-z0-9]*\s*>|<[A-Za-z][A-Za-z0-9]*\s+[a-z][a-z-]*=", body_stripped
    ):
        return False, "SKILL.md body contains XML tags; remove them"

    # 15. Reference files listed exist on disk
    ref_section = re.search(r"## Reference files(.+?)(?=\n---|\Z)", body, re.DOTALL)
    if ref_section:
        # Paths live inside backticks on each bullet line.
        for m in re.finditer(r"^\s*-\s+`([^`]+)`", ref_section.group(1), re.MULTILINE):
            ref = m.group(1).strip()
            # Absolute (repo-root-relative, starts with /) vs sibling
            p = REPO_ROOT / ref.lstrip("/") if ref.startswith("/") else SKILL_ROOT / ref
            if not p.exists():
                return False, f"SKILL.md references missing file: {ref}"

    # 16. Versioning footer — must equal VERSION file (same invariant
    #     as check #9, applied to the prose footer so neither surface
    #     can drift independently). Reuses the module-level _SEMVER_RE
    #     (Codex v5 M2) so the footer is held to real semver, not the
    #     loose Wave-E approximation.
    footer_match = re.search(
        rf"\*version:\s*({_SEMVER_RE})\b",
        body,
    )
    if not footer_match:
        return False, ("SKILL.md missing versioning footer (*version: X.Y.Z[-suffix] ...*)")
    footer_version = footer_match.group(1)
    if footer_version != canonical_version:
        return False, (
            f"SKILL.md footer version ({footer_version!r}) does not match "
            f"VERSION file ({canonical_version!r})"
        )

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
    if schema_version != "2.0":
        return False, f"catalog.json schema_version={schema_version!r}; expected '2.0'"
    counts = data.get("counts") or {}
    # Schema v2: tools_total replaces v1's flat `tools` key (ADR-0003).
    for field, minimum in (
        ("tools_total", 150),
        ("primitives", 100),
        ("recipes", 200),
        ("skills", 1),
        ("bundles", 6),
    ):
        if int(counts.get(field, 0)) < minimum:
            return False, f"catalog.json counts.{field}={counts.get(field)} < floor {minimum}"

    # Determinism check — rebuild into a tempdir and compare stable hashes.
    import tempfile

    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_manifest_") as tmp:
        out_path = Path(tmp) / "catalog.json"
        proc = subprocess.run(
            [sys.executable, "-m", "engine.index.manifest", "verify", "--out", str(out_path)],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
        )
        if proc.returncode != 0:
            return False, f"manifest verify failed: {(proc.stdout + proc.stderr)[-300:]}"
        # Compare committed catalog's stable content (ignoring generated_at + kit_commit)
        live = json.loads(out_path.read_text())
        committed = json.loads(catalog.read_text())
        for f in ("generated_at", "kit_commit"):
            live.pop(f, None)
            committed.pop(f, None)
        if json.dumps(live, sort_keys=True) != json.dumps(committed, sort_keys=True):
            return False, (
                "engine/index/catalog.json drifted from on-disk sources. "
                "Regenerate via `python -m engine.index.manifest build` and commit."
            )
    return True, (
        f"catalog synced: {counts.get('tools_total')} tools "
        f"({counts.get('skills')} skill / {counts.get('bundles')} bundles), "
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
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
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
    for required in (
        "schedule:",
        "cron:",
        "engine.bench",
        "ANTHROPIC_API_KEY",
        "latest_score.json",
    ):
        if required not in txt:
            return False, f"workflow missing {required}"
    return True, "benchmark-nightly.yml present with schedule + claude dispatch + score upload"


def _r_code_level_benchmark() -> tuple[bool, str]:
    """B3.6 — code-level harness published + perfect on covered specs.

    The plan-level score (B3.5) measures the the agent's requirement→primitive
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
            s["spec_id"]
            for s in data.get("spec_results", [])
            if s.get("covered") and (s.get("score") or 0) < 100
        ]
        return False, f"covered specs not all at 100 ({score:.2f}): {fails[:3]}"
    return True, (
        f"code-level: {score:.2f} across {covered}/{total} covered specs ({coverage:.1f}% coverage)"
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
    expected = {
        "spec.py",
        "adapter.py",
        "judge.py",
        "runner.py",
        "publish.py",
        "snapshots.py",
        "attribution.py",
        "static_scan.py",
        "__init__.py",
    }
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

    return True, (f"blind harness present · {len(specs)} spec(s) authored · stub fixtures complete")


def _r_install_docker_ci() -> tuple[bool, str]:
    """B4.1 — install.sh + install-docker CI workflow present + hermetic."""
    installer = REPO_ROOT / "install.sh"
    workflow = REPO_ROOT / ".github" / "workflows" / "install-docker.yml"
    if not installer.exists():
        return False, "missing: install.sh"
    if not workflow.exists():
        return False, "missing: .github/workflows/install-docker.yml"
    txt = workflow.read_text(encoding="utf-8")
    for required in (
        "python:3.12-slim",
        "install.sh",
        "contract_check",
        "latest_score.json",
        "schedule:",
    ):
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
    required = ("README.md", "AGENT_SESSION.md")
    for sub in subdirs:
        for f in required:
            if not (sub / f).exists():
                return False, f"{sub.name}/ missing {f}"
        # cross-link table: must mention tools-used + primitives-imported
        readme = (sub / "README.md").read_text(encoding="utf-8")
        if "Tools used" not in readme or "Primitives imported" not in readme:
            return (
                False,
                f"{sub.name}/README.md missing cross-link table (Tools used / Primitives imported)",
            )
    return (
        True,
        f"{len(subdirs)} examples present with README + AGENT_SESSION + cross-link tables",
    )


def _r_docs_site_v1() -> tuple[bool, str]:
    """B4.3 — docs site includes top-level docs + per-tool pages."""
    import tempfile

    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_docs_v1_") as tmp:
        cmd = [sys.executable, "-m", "engine.docs.build", "--out", tmp, "--verify"]
        out = subprocess.run(
            cmd,
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
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
    return (
        True,
        f"docs site v1: {n_prim_pages} primitives + {n_tool_pages} tools + 5 top-level docs",
    )


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
    # Uses the module-level _SEMVER_RE (official semver.org spec).
    if not re.fullmatch(_SEMVER_RE, ver):
        return False, f"VERSION not semver: {ver!r}"
    cl = changelog.read_text(encoding="utf-8")
    for required in ("[0.1.0]", "Benchmark", "primitives", "tools"):
        if required not in cl:
            return False, f"CHANGELOG.md missing {required!r}"
    return True, f"CHANGELOG.md + VERSION={ver} with v0.1.0 entry citing score"


def _r_tier1_surface_truth() -> tuple[bool, str]:
    """B2.6 — tier-1 runtime strings tell the truth about the catalog.

    The tier-1 meta tools (mcp_tools/tier1.py) ship three agent-visible
    runtime surfaces: the module docstring, each MCP_TOOL description,
    and the workflow breadcrumb list inside `fastapi_meta_home()`'s
    return envelope. Prior audits read SKILL.md (the prose contract)
    but never diffed these literal runtime strings against the catalog
    they describe. Codex v6 + Opus sign-off both caught the residual
    drift: tier1.py kept advertising the pre-freeze `180 tools` / `122
    primitives` counts long after catalog.json moved to 201 / 299, and
    Wave F B2's SKILL.md skill-kit-vs-emitted-project split never
    propagated to the `fastapi_meta_home` workflow steps.

    This rule fails CI on:
      - any mention of a pre-freeze stale count (`180 tool(s|-tool)`,
        `122 primitive(s)`) anywhere in tier1.py
      - missing qualifier text in `fastapi_meta_audit` /
        `fastapi_meta_verify` descriptions: both MUST state the tool
        operates on the skill kit itself (not an emitted project)
      - missing current canonical count: tier1.py MUST cite the live
        catalog tool count somewhere (we search for `N tool`/`N-tool`
        where N = catalog.counts.tools) so a subsequent count bump
        forces this file to be updated deliberately.
    """
    tier1 = SKILL_ROOT / "mcp_tools" / "tier1.py"
    if not tier1.exists():
        return False, "missing: mcp_tools/tier1.py"
    src = tier1.read_text(encoding="utf-8")

    # Canonical counts from catalog.json (the machine source).
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog_path.exists():
        return False, "missing: engine/index/catalog.json"
    try:
        cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"catalog.json malformed: {exc}"
    # Schema v2: `tools_total` replaces v1 flat `tools` key (ADR-0003).
    # Falls back to legacy `tools` only if a transitional catalog ever
    # ships; today catalog.json always emits `tools_total`.
    _counts = cat.get("counts", {})
    tool_count = int(_counts.get("tools_total", _counts.get("tools", 0)))
    primitive_count = int(_counts.get("primitives", 0))
    if tool_count <= 0 or primitive_count <= 0:
        return False, (
            "catalog.json counts.tools_total / counts.primitives missing "
            "or zero — cannot validate tier1 surface truth"
        )

    # Stale-count detector — SCOPED to agent-visible runtime strings
    # only. Matches on:
    #   - `"description": ( ... )` blocks inside MCP_TOOL* dicts
    #   - the `"workflow": [ ... ]` list inside fastapi_meta_home's
    #     return envelope (the strings the agent reads at runtime)
    # Module docstrings, comments, and research citations like
    # "30–50-tool degradation threshold" are deliberately excluded —
    # they are internal commentary, not runtime surface.
    agent_visible_blobs: list[str] = []
    for m in re.finditer(
        r'"description":\s*\(\s*((?:[^()]|\([^)]*\))*?)\s*\),',
        src,
        re.DOTALL,
    ):
        agent_visible_blobs.append(m.group(1))
    wf_match = re.search(
        r'"workflow":\s*\[(.*?)\],',
        src,
        re.DOTALL,
    )
    if wf_match:
        agent_visible_blobs.append(wf_match.group(1))
    scoped_src = "\n".join(agent_visible_blobs)
    if not scoped_src:
        return False, (
            "could not extract MCP_TOOL descriptions + workflow from "
            "mcp_tools/tier1.py — file shape changed?"
        )

    tool_claims = set(int(m) for m in re.findall(r"\b(\d+)[\s-]+tool(?:s|-catalog)?\b", scoped_src))
    primitive_claims = set(int(m) for m in re.findall(r"\b(\d+)\s+primitive(?:s)?\b", scoped_src))
    # Any claim in agent-visible text that isn't the canonical count
    # AND isn't a small structural literal (≤20) is stale.
    stale_tool_claims = sorted(n for n in tool_claims if n != tool_count and n > 20)
    stale_primitive_claims = sorted(n for n in primitive_claims if n != primitive_count and n > 20)
    if stale_tool_claims:
        return False, (
            f"mcp_tools/tier1.py agent-visible text carries stale "
            f"tool-count claims {stale_tool_claims} — current catalog "
            f"has {tool_count} tools. Update the MCP_TOOL descriptions "
            f"+ workflow strings."
        )
    if stale_primitive_claims:
        return False, (
            f"mcp_tools/tier1.py agent-visible text carries stale "
            f"primitive-count claims {stale_primitive_claims} — current "
            f"registry has {primitive_count} primitives."
        )
    if tool_count not in tool_claims:
        return False, (
            f"mcp_tools/tier1.py MCP_TOOL descriptions + workflow do "
            f"not cite the current catalog tool count ({tool_count}) "
            f"anywhere. The agent reads these strings; they must "
            f"advertise the real surface size."
        )

    # Skill-kit scope qualifier — _audit and _verify MUST say what they
    # operate on (Wave F B2 lesson: agents took "audit" to mean
    # emitted-project validation; both descriptions must now disclaim).
    audit_match = re.search(
        r"MCP_TOOL_AUDIT\s*=\s*\{.*?\}",
        src,
        re.DOTALL,
    )
    verify_match = re.search(
        r"MCP_TOOL_VERIFY\s*=\s*\{.*?\}",
        src,
        re.DOTALL,
    )
    if not audit_match or not verify_match:
        return False, (
            "mcp_tools/tier1.py missing MCP_TOOL_AUDIT / MCP_TOOL_VERIFY "
            "block — expected at module level"
        )
    for label, block in (
        ("MCP_TOOL_AUDIT", audit_match.group(0)),
        ("MCP_TOOL_VERIFY", verify_match.group(0)),
    ):
        blob = block.lower()
        has_scope_note = (
            "skill-kit" in blob
            or "skill_root" in blob
            or "not an emitted project" in blob
            or "not the emitted project" in blob
            or "not validate an emitted project" in blob
        )
        if not has_scope_note:
            return False, (
                f"{label} description missing skill-kit-vs-emitted-"
                f"project scope note. Wave F B2 requires both meta "
                f"audit tools to disclaim: they operate on the skill "
                f"kit itself, NOT an emitted project."
            )

    return True, (
        f"tier1 runtime strings cite current catalog ({tool_count} "
        f"tools, {primitive_count} primitives) + scope-disclaim audit/"
        f"verify"
    )


def _r_tier1_surface_inventory() -> tuple[bool, str]:
    """B2.7 — `mcp_tools/tier1.py` exposes exactly 8 distinct MCP_TOOL* dicts.

    The cognition cap (≤ 8 always-loaded tools) is load-bearing — once
    the surface grows past 8, the Maestro starts ignoring the descriptions
    (Anthropic 30-50-tool degradation finding) and tier-1 stops being
    "always-discoverable". This rule freezes the count at 8 after
    WAVE-0-F2 (the two bundle tools landed; the redundant MCP_TOOL_HOME
    alias was retired). Counts DISTINCT dicts (by id) so aliases don't
    inflate the surface.

    The compose tool in `mcp_tools/compose.py` is registered alongside
    tier-1 but lives in a separate module by design; this rule only
    polices the module that the dual-index design names as the tier-1
    surface (per ADR-0003).
    """
    tier1 = SKILL_ROOT / "mcp_tools" / "tier1.py"
    if not tier1.exists():
        return False, "missing: mcp_tools/tier1.py"
    # Parse module-level MCP_TOOL* assignments via AST (no import — keeps
    # this rule cheap and side-effect free, the same pattern manifest.py
    # uses to scan tool files).
    import ast as _ast

    try:
        tree = _ast.parse(tier1.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return False, f"mcp_tools/tier1.py syntax error: {exc}"

    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, _ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, _ast.Name) and target.id.startswith("MCP_TOOL")):
                continue
            # Accept literal dict OR a Name (alias). We count alias *names*
            # separately so the previous MCP_TOOL_HOME = MCP_TOOL pattern
            # would be visible to the rule; modern tier1.py should NOT use
            # such aliases — each MCP_TOOL* identifier must bind a fresh
            # dict literal. We enforce that below.
            if isinstance(node.value, _ast.Dict):
                found.add(target.id)
            elif isinstance(node.value, _ast.Name):
                return False, (
                    f"mcp_tools/tier1.py: {target.id} is an alias of "
                    f"{node.value.id} — aliases inflate the tier-1 surface "
                    "count without adding a distinct behaviour. Bind a "
                    "literal dict or remove the alias."
                )
    expected = {
        "MCP_TOOL",
        "MCP_TOOL_SEARCH",
        "MCP_TOOL_DESCRIBE",
        "MCP_TOOL_SCAFFOLD",
        "MCP_TOOL_AUDIT",
        "MCP_TOOL_VERIFY",
        "MCP_TOOL_LIST_BUNDLE",
        "MCP_TOOL_ACTIVATE_BUNDLE",
    }
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        return False, (
            f"mcp_tools/tier1.py MCP_TOOL* set mismatch: "
            f"missing={missing} extra={extra}. The cognition cap (≤ 8) "
            "freezes the tier-1 surface at exactly these eight."
        )
    if len(found) != 8:
        return False, (
            f"mcp_tools/tier1.py declares {len(found)} MCP_TOOL* dicts; "
            "the cognition cap freezes tier-1 at exactly 8."
        )
    return True, "tier-1 surface = 8 MCP_TOOL* dicts in mcp_tools/tier1.py"


def _r_catalog_schema_version() -> tuple[bool, str]:
    """B2.8 — `catalog.json schema_version == "2.0"` (the v2 invariant).

    Schema v2 (ADR-0003) was a breaking change for internal consumers
    (Tier-1 router, audit, INVENTORY emitter). Pinning the on-disk
    schema_version here means a future bump to v3 cannot land without
    explicitly retiring this rule and updating every consumer — closes
    the class of half-migrations the WAVE-0-F0 audit surfaced.
    """
    catalog = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog.exists():
        return False, (
            f"missing: {catalog.relative_to(SKILL_ROOT)} — "
            "run `python -m engine.index.manifest build`"
        )
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"catalog.json malformed: {exc}"
    sv = data.get("schema_version")
    if sv != "2.0":
        return False, (
            f"catalog.json schema_version={sv!r}; expected '2.0' "
            "(set in engine/index/__init__.py::MANIFEST_SCHEMA_VERSION)"
        )
    # Sanity: skills array must be present + non-empty + every tool
    # must carry skill + bundle fields. These were added in v2 (ADR-0003).
    skills = data.get("skills") or []
    if not skills:
        return False, "catalog.json schema_version=2.0 but `skills` array is empty"
    tools = data.get("tools") or []
    for t in tools[:5]:  # cheap sample — manifest invariants enforce the full check
        if "skill" not in t or "bundle" not in t:
            return False, (
                "catalog.json tool entry missing v2 fields `skill`/`bundle` "
                f"(offender: {t.get('name')!r})"
            )
    return True, f"catalog.json schema_version='2.0' with {len(skills)} skill(s)"


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
    return True, "CONTRIBUTING.md complete (primitive + tool + recipe + dev setup)"


RULES: list[Rule] = [
    Rule("B0.1", 0, "PRODUCT.md canonical", _r_product_md),
    Rule("B0.2", 0, "ROADMAP.md honest + phased", _r_roadmap_md),
    Rule("B0.3", 0, "CONTRACT.md (this)", _r_contract_md),
    Rule("B0.4", 0, "SKILL.md ground-truth honest", _r_skillmd_honest),
    Rule("B0.5", 0, "README.md ≤100 lines + links", _r_readme_md),
    Rule("B0.6", 0, "agent memory pointer (repo-local)", _r_agent_memory_pointer),
    Rule("B0.7", 0, "No stub tests under /benchmark/", _r_benchmark_no_stubs),
    Rule("B0.8", 0, ".gitignore covers artefacts", _r_gitignore_artefacts),
    Rule("B0.9", 0, "no discontinued 'Maestro' terminology in live tree", _r_no_legacy_terminology),
    Rule("B1.0", 1, "core.venous copy-in distribution", _r_core_venous_distribution),
    Rule("B1.0.1", 1, "adapter layer + framework-free primitives", _r_adapter_layer_invariant),
    Rule("B1.1", 1, "primitives_by_concern.yaml registry", _r_registry_exists),
    Rule("B1.2", 1, "Compose-with in every primitive .md", _r_compose_with_coverage),
    Rule("B1.3", 1, "≥15 tools import core.venous", _r_tools_import_primitives),
    Rule("B1.5", 1, "no hardcoded @mcp_app.tool decorators", _r_no_manual_mcp_tool_decorator),
    Rule(
        "B1.6",
        1,
        "no orphan generators (every generate_* is tool or internal)",
        _r_no_orphan_generators,
    ),
    Rule("B1.7", 1, "fastapi adapter coverage (tested + maps to registry)", _r_adapter_coverage),
    Rule(
        "B1.8",
        1,
        "tier-lite eligibility (stateless, framework-free, no REPLACE_ME)",
        _r_tier_lite_eligibility,
    ),
    Rule("B2.1", 2, "find_primitive MCP tool + BM25 quality gate", _r_find_primitive_discovery),
    Rule("B2.2", 2, "suggest_composition MCP tool + recipe quality gate", _r_suggest_composition),
    Rule("B2.3", 2, "reference docs site idempotent build", _r_docs_site),
    Rule("B2.4", 2, "index catalog manifest synced + deterministic", _r_index_manifest),
    Rule("B2.5", 2, "SKILL.md Agent Skills contract (agent-facing)", _r_skill_md_contract),
    Rule("B2.6", 2, "tier1 runtime strings match catalog + scope-disclaim", _r_tier1_surface_truth),
    Rule(
        "B2.7",
        2,
        "tier-1 surface inventory: exactly 8 MCP_TOOL* in tier1.py",
        _r_tier1_surface_inventory,
    ),
    Rule(
        "B2.8",
        2,
        "catalog.json schema_version == '2.0' + v2 fields present",
        _r_catalog_schema_version,
    ),
    Rule("B3.1", 3, "20 benchmark specs (5 baseline / 10 mid / 5 adversarial)", _r_bench_specs),
    Rule("B3.2", 3, "scoring rubric implemented + tested", _r_bench_rubric_runner),
    Rule("B3.3", 3, "benchmark runner + stub agent + report JSON", _r_bench_rubric_runner),
    Rule("B3.4", 3, "nightly benchmark CI workflow", _r_bench_nightly_workflow),
    Rule("B3.5", 3, "baseline benchmark score published", _r_benchmark_score),
    Rule(
        "B3.6",
        3,
        "code-level harness published (perfect on covered, ≥25% coverage)",
        _r_code_level_benchmark,
    ),
    Rule("B3.7", 3, "blind benchmark harness + specs + stub fixtures", _r_blind_benchmark_harness),
    Rule("B4.1", 4, "install.sh + fresh-Docker CI", _r_install_docker_ci),
    Rule(
        "B4.2",
        4,
        "/examples/ populated (≥5 with README + AGENT_SESSION + cross-link)",
        _r_examples_populated,
    ),
    Rule("B4.3", 4, "docs site v1 (top-level docs + per-tool pages)", _r_docs_site_v1),
    Rule("B4.4", 4, "CHANGELOG + VERSION semver cite score", _r_changelog_semver),
    Rule("B4.5", 4, "CONTRIBUTING.md complete", _r_contributing_md),
    Rule("B4.6", 4, "VERSION triplet sync (repo-root + skill + STATUS.md)", _r_version_sync),
    Rule(
        "B4.7",
        4,
        "canonical counts sync (INVENTORY vs CLAUDE/STATUS/ROADMAP/CHANGELOG)",
        _r_counts_sync,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="CONTRACT.md machine enforcer.")
    parser.add_argument("--item", type=str, default=None, help="Run only this §B item (e.g. B1.1).")
    parser.add_argument(
        "--phase", type=int, default=None, help="Run all items in a phase (e.g. --phase 0)."
    )
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
    print(
        f"\n{passed}/{total} contract items satisfied"
        + (" — ALL GREEN" if failed == 0 else f" — {failed} VIOLATIONS")
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
