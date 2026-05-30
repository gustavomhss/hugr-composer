"""Phase 2 SKILL.md contract — agent-facing entry doc (CONTRACT.md §B2.5).

CONTRACT.md scope: §B2.5 only — the SKILL.md Agent Skills contract
(20-rule check from ``docs/research/SKILL_META_FORMAT.md`` §13):
frontmatter shape, SPDX→LICENSE signature match for 19 licenses, body
sections, machine-readable YAML, transcript validation, footer version
sync.

Isolated in its own module because ``_r_skill_md_contract`` is 448 LOC
on its own — co-locating it with the rest of B2 pushed
``phase2_catalog`` over the 500-LOC hard cap. The ``_license_signatures``
table + ``_gnu_sig`` factory dominate its budget.
"""

from __future__ import annotations

import json
import re

from ._common import _SEMVER_RE, REPO_ROOT, SKILL_ROOT


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
