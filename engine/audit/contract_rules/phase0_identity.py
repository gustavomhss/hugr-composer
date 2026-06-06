"""Phase 0 — repo / skill identity surface (CONTRACT.md §B0.1–§B0.9).

CONTRACT.md scope: §B0.1 PRODUCT.md, §B0.2 ROADMAP.md, §B0.3 CONTRACT.md,
§B0.4 SKILL.md ground-truth honesty, §B0.5 README.md ≤100 lines,
§B0.6 agent memory pointer (repo-local), §B0.7 no benchmark stubs,
§B0.8 .gitignore covers artefacts, §B0.9 no discontinued
``Maestro`` terminology in the live tree.

Cohesion: every rule reads top-level repo / skill identity docs
(``PRODUCT.md``, ``ROADMAP.md``, ``CONTRACT.md``, ``README.md``,
``SKILL.md``, ``.gitignore``, ``engine/audit/AGENT_MEMORY_POINTER.md``);
they share ``_exists`` and the INVENTORY-as-source-of-truth surface-count
pattern.
"""

from __future__ import annotations

import re

from ._common import REPO_ROOT, SKILL_ROOT, _exists


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
        if f"- [ ] **A{i} " not in body and f"- [ ] **A{i} " not in body:
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
    # Post-WP-16 split: the rule body moved into the phase0_identity
    # module; the same self-reference exemption applies to its new home.
    # phase2_tier1.py preserves the historical Codex audit comment
    # "the Maestro starts ignoring the descriptions" verbatim — exempt
    # the file to avoid a self-flag on the (unchanged) rule docstring.
    "skills/SKILL-001-fastapi-production/engine/audit/contract_rules/phase0_identity.py",
    "skills/SKILL-001-fastapi-production/engine/audit/contract_rules/phase2_tier1.py",
    # _registry.py carries the Rule(...) tuple whose description text
    # quotes the discontinued term ("no discontinued 'Maestro' terminology
    # in live tree"); same self-reference exemption pattern.
    "skills/SKILL-001-fastapi-production/engine/audit/contract_rules/_registry.py",
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
        # Skip non-source trees: virtualenvs, VCS, and tool caches. In the
        # standalone repo the .venv lives inside REPO_ROOT, and third-party
        # packages (e.g. faker's pt_PT providers) legitimately contain the
        # card-brand word "Maestro" — those are not live HuGR doc/code.
        if any(
            f"/{seg}/" in f"/{rel}"
            for seg in (
                ".venv",
                ".git",
                "__pycache__",
                "node_modules",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".hypothesis",
            )
        ):
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
