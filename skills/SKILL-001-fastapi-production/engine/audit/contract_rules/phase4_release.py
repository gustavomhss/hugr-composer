"""Phase 4 — release surface (CONTRACT.md §B4.1–§B4.7).

CONTRACT.md scope: §B4.1 install.sh + fresh-Docker CI, §B4.2 /examples/
populated, §B4.3 docs site v1 (top-level + per-tool pages),
§B4.4 CHANGELOG + VERSION semver, §B4.5 CONTRIBUTING.md complete,
§B4.6 VERSION triplet sync (root + skill + STATUS.md),
§B4.7 canonical counts sync (INVENTORY vs CLAUDE/STATUS/ROADMAP/
CHANGELOG/SKILL/FREEZE/INTERFACES).

Cohesion: every rule audits a release-surface doc (README site, install
path, examples, CHANGELOG, VERSION triplet, narrative-doc count sync).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from ._common import _SEMVER_RE, REPO_ROOT, SKILL_ROOT


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
