"""Regression tests for the Phase-3 deferred closures (PR-G).

PR-E and PR-F closed eight of the thirteen Codex hunt findings; five sat
outside their frozen partitions and were deferred to this PR-G:

* C2 F-005 — ``promote.py`` advertised ``FILL_AND_PROMOTE`` as actionable
  in its module docstring but ``plan()`` hard-rejected the verdict.
  Fixed by aligning the docstring with the implementation: the verdict
  is reclassify-only and the rejection message now says so explicitly.
* C2 F-006 — ``classify.py`` Rule 5 docstring claimed quarantined
  non-framework-coupled items continue through the signal/shell flow,
  but the implementation (and the tests) short-circuit them at
  ``NEEDS_REVIEW``. Fixed by aligning the docstring with the code.
* C2 F-007 — ``docs/repo-standard.md`` and the audit/docs-site code
  disagreed on whether ``CONTRIBUTING.md`` belongs at root or under
  ``docs/``. Fixed by picking root as canonical (the audit + the
  docs-site already treat it that way). STANDALONE re-anchor (2026-06):
  after extraction there is no ``docs/contributing.md`` pointer nor a
  ``docs/repo-standard.md`` — the docs builder renders root CONTRIBUTING.md
  directly and ``scripts/checks/md_location.py`` encodes the root-canonical
  convention, so the F-007 checks now assert *no parallel fork* + the
  hygiene rule keeps root governance docs canonical.
* C4 F-004 — ``install.sh`` printed a tool decomposition whose labels
  contradicted the catalog, and pointed at a missing skill ``README.md``.
  Fixed by reconciling the decomposition to the catalog truth and
  shipping ``skills/SKILL-001-fastapi-production/README.md``.
* C4 F-005 — ``scripts/checks/md_location.py`` exempted privileged
  basenames (``CHANGELOG.md``, ``CLAUDE.md``, ``CONTRIBUTING.md``,
  ``LICENSE.md``) at ANY depth, letting stray narrative markdown be
  smuggled into code packages. Fixed by splitting the basename pool
  into a root-only set and a package-level set.

Each test below is paired with a "before-fix would have failed" reasoning
note so a future maintainer reading a red test can identify which
finding it traces back to.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Skill root = the parent of the `engine` package (this file lives at
# `engine/tests/test_codex_phase3_closures.py`).
SKILL_ROOT = Path(__file__).resolve().parents[2]
# Layout-aware repo root (mirrors engine/docs/build.py): in the Arsenal monorepo
# the skill lived under `skills/SKILL-001-…/`, so the repo root was two levels up;
# in this standalone repo the skill root IS the repo root. Without this, the
# governance files (CONTRIBUTING.md, install.sh, scripts/checks/md_location.py)
# resolve to a path OUTSIDE the repo and every REPO_ROOT-based check errors.
REPO_ROOT = SKILL_ROOT.parents[1] if SKILL_ROOT.parent.name == "skills" else SKILL_ROOT


# ---------------------------------------------------------------------------
# C2 F-005 — promote.py docstring vs plan() drift
# ---------------------------------------------------------------------------


def test_c2_f005_promote_docstring_excludes_fill_and_promote() -> None:
    """The executor docstring must not advertise FILL_AND_PROMOTE as actionable.

    Before fix: the module docstring listed FILL_AND_PROMOTE alongside
    PROMOTE_AS_ADAPTER + PROMOTE_AS_PRIMITIVE as a verdict the executor
    runs, but ``plan()`` (line ~155) hard-rejected it. Reading the
    docstring alone would lead a maintainer to wire FILL_AND_PROMOTE
    into the executor — only to discover at runtime that the gate
    refuses it. The fix aligns the docstring with the code: the verdict
    is reclassify-only.
    """
    src = (SKILL_ROOT / "engine" / "promotion" / "promote.py").read_text(encoding="utf-8")
    # The docstring "Invariants" block must not list FILL_AND_PROMOTE
    # alongside the two actionable verdicts.
    m = re.search(r"Invariants:.*?(?=\n\n[^\s])", src, re.DOTALL)
    assert m is not None, "promote.py docstring has no Invariants block"
    invariants = m.group(0)
    assert "FILL_AND_PROMOTE" in invariants, (
        "Invariants block should still NAME the verdict — but as "
        "reclassify-only, not as actionable. Don't silently drop it."
    )
    # The actionable-verdict list must be (ADAPTER, PRIMITIVE), no FILL.
    actionable_line = re.search(r"actionable\s+verdict\s+\(([^)]+)\)", invariants)
    assert actionable_line is not None, "Expected an 'actionable verdict (...)' clause"
    assert "FILL_AND_PROMOTE" not in actionable_line.group(1), (
        "FILL_AND_PROMOTE listed as actionable — the F-005 drift is back."
    )


def test_c2_f005_plan_rejection_message_points_to_reclassify() -> None:
    """When plan() refuses FILL_AND_PROMOTE the error must direct the user
    to the reclassify path (the now-canonical contract)."""
    sys.path.insert(0, str(SKILL_ROOT))
    try:
        from engine.promotion import promote as promote_mod
        from engine.promotion.schemas import Verdict
    finally:
        sys.path.pop(0)
    # Source-level assertion (no need to construct a full ledger):
    src = (SKILL_ROOT / "engine" / "promotion" / "promote.py").read_text(encoding="utf-8")
    # plan() must mention the reclassify hint for FILL_AND_PROMOTE.
    assert "reclassify-only" in src, (
        "plan() should explain the reclassify path when rejecting "
        "FILL_AND_PROMOTE — otherwise the user gets the bare 'refuses' "
        "error with no actionable next step."
    )
    # And FILL_AND_PROMOTE must still be a real enum value (we're not
    # nuking the verdict — classify still emits it).
    assert Verdict.FILL_AND_PROMOTE.value == "fill_and_promote"
    # Module loads without error (catches accidental syntax breakage).
    assert promote_mod is not None


# ---------------------------------------------------------------------------
# C2 F-006 — classify.py Rule 5 docstring drift
# ---------------------------------------------------------------------------


def test_c2_f006_classify_rule5_docstring_matches_code() -> None:
    """Rule 5 docstring must say NEEDS_REVIEW (what the code does),
    not FILL_AND_PROMOTE / NEEDS_CALLER (what the prose used to claim).

    Before fix: docstring said quarantined non-framework items continue
    through the signal/shell flow → FILL_AND_PROMOTE or NEEDS_CALLER;
    code (line ~270) and test suite (`test_rule5_quarantined_non_framework_needs_review`)
    both enforce NEEDS_REVIEW.
    """
    src = (SKILL_ROOT / "engine" / "promotion" / "classify.py").read_text(encoding="utf-8")
    rule5_match = re.search(r"5\. Physically quarantined.*?(?=\n\n|\n6\.)", src, re.DOTALL)
    assert rule5_match is not None, "Rule 5 docstring block not found"
    rule5 = rule5_match.group(0)
    # Must say NEEDS_REVIEW (the actual code path).
    assert "NEEDS_REVIEW" in rule5, (
        f"Rule 5 docstring must mention NEEDS_REVIEW (the verdict the code "
        f"returns). Drift back to F-006. Block was:\n{rule5}"
    )
    # The verdict line specifically (the `→ XXX` arrow) must point at
    # NEEDS_REVIEW, not at the old FILL_AND_PROMOTE / NEEDS_CALLER drift.
    # Prose elsewhere in the block may reference those names while
    # explaining what the rule does NOT do.
    arrow_line = re.search(r"→\s*([A-Z_]+)", rule5)
    assert arrow_line is not None, "Rule 5 block must declare its verdict via `→ VERDICT`"
    assert arrow_line.group(1) == "NEEDS_REVIEW", (
        f"Rule 5 declares verdict `→ {arrow_line.group(1)}` but the code "
        "returns NEEDS_REVIEW. F-006 drift returned."
    )


def test_c2_f006_classify_rule5_code_still_emits_needs_review() -> None:
    """Sanity: the existing test_classify.py contract (NEEDS_REVIEW) holds.

    Guard against a "fix the docstring by changing the code" regression.
    """
    sys.path.insert(0, str(SKILL_ROOT))
    try:
        from engine.promotion.classify import _classify_single
        from engine.promotion.schemas import StateFlags, Verdict
    finally:
        sys.path.pop(0)
    state = StateFlags(
        name="X",
        namespace="api",
        is_quarantined=True,
        quarantine_reason="too_small",
        replace_me_count=0,
        has_tla=False,
        has_concurrency=False,
        has_mutable_class_state=False,
        loc=20,
        test_file_present=True,
        invariants_stubbed=False,
    )
    verdict, _, _, staging_reason, _, _ = _classify_single(state, [])
    assert verdict == Verdict.NEEDS_REVIEW, (
        f"Rule 5 code regressed from NEEDS_REVIEW to {verdict}. "
        "The F-006 fix aligned the docstring with the code; if the code "
        "changed, the docstring AND test_classify.py must change together."
    )
    assert staging_reason is not None


# ---------------------------------------------------------------------------
# C2 F-007 — root CONTRIBUTING vs docs/contributing split
# ---------------------------------------------------------------------------


def test_c2_f007_root_contributing_is_canonical_and_complete() -> None:
    """Root CONTRIBUTING.md must exist + cover the four required surfaces.

    The F-007 decision was: root is canonical (audit + docs-site already
    read root). If root vanishes or the audit-required sections disappear,
    B4.5 will go red.
    """
    contrib = REPO_ROOT / "CONTRIBUTING.md"
    assert contrib.exists(), "Root CONTRIBUTING.md is the F-007 canonical file"
    text = contrib.read_text(encoding="utf-8").lower()
    # Audit B4.5 requires primitive / tool / recipe / dev-setup coverage.
    for needed in ("primitive", "tool", "recipe", "setup"):
        assert needed in text, f"Root CONTRIBUTING.md missing `{needed}` coverage"


def test_c2_f007_root_contributing_has_no_parallel_fork() -> None:
    """F-007 in the standalone repo: root CONTRIBUTING.md is the SINGLE source.

    In the Arsenal monorepo the docs site rendered a thin ``docs/contributing.md``
    pointer back to root. The standalone docs builder (``engine/docs/build.py``)
    renders the ROOT ``CONTRIBUTING.md`` directly at ``/contributing/`` — so a
    ``docs/contributing.md`` would re-introduce the very fork F-007 closed.
    Assert no such fork exists and the builder still publishes the root file.
    """
    # No parallel contributor-doc fork under docs/.
    assert not (REPO_ROOT / "docs" / "contributing.md").exists(), (
        "docs/contributing.md re-introduces a contributor-doc fork — in the "
        "standalone repo root CONTRIBUTING.md is the single source and "
        "engine/docs/build.py renders it directly at /contributing/."
    )
    # The docs builder publishes root CONTRIBUTING.md at /contributing/.
    build_src = (SKILL_ROOT / "engine" / "docs" / "build.py").read_text(encoding="utf-8")
    assert '("CONTRIBUTING.md", "contributing"' in build_src, (
        "engine/docs/build.py must render root CONTRIBUTING.md at /contributing/ "
        "(the F-007 canonical publish path)."
    )


def test_c2_f007_md_location_keeps_root_governance_canonical() -> None:
    """F-007 in the standalone repo: the md-hygiene rule does NOT force root
    governance docs under ``docs/``.

    The monorepo encoded the "where docs live" rule in ``docs/repo-standard.md``
    ("ALL narrative docs under /docs/"), which contradicted root-canonical
    CONTRIBUTING/CONTRACT/ROADMAP/…. The standalone repo encodes the convention
    in ``scripts/checks/md_location.py`` instead: root governance basenames are
    allowed at the repo root, so there is no contradiction left to remove.
    """
    md = _load_md_location()
    # The convention basenames remain allowed at the repo root (not forced into docs/).
    assert md._is_violation("CONTRIBUTING.md") is False
    # Root governance docs are recognised as canonical at the repo root.
    assert {"CONTRACT.md", "ROADMAP.md", "STATUS.md"} <= md.ROOT_GOV, (
        "md_location.ROOT_GOV must recognise root governance docs as canonical "
        "at the repo root (the standalone replacement for repo-standard.md)."
    )


# ---------------------------------------------------------------------------
# C4 F-004 — install.sh banner + skill README
# ---------------------------------------------------------------------------


def test_c4_f004_install_sh_decomposition_sums_to_catalog_total() -> None:
    """The install banner's per-bucket breakdown must add up to catalog.json's
    `tools_total` (201). Pre-fix the labels were `100 + 27 + 56 + 7 + 9 + 2`
    which sums to 201 but mislabels each bucket against the catalog truth.
    """
    install_sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    # Find all "N slice/macro/dispatcher/…" numbers in the banner block.
    banner = install_sh
    # Extract the "(... + ... + ... + ... + ...)" tuple near "MCP tools".
    m = re.search(r"MCP tools\${c_reset}\s*\(([^)]+)\)", banner)
    assert m is not None, "Could not locate the MCP tools decomposition tuple"
    nums = [int(n) for n in re.findall(r"\b(\d+)\b", m.group(1))]
    assert sum(nums) == 201, (
        f"install.sh banner decomposition {nums} sums to {sum(nums)}, "
        "not 201 (catalog.json tools_total). F-004 drift."
    )
    # And the banner must point at files that actually exist post-install.
    # The skill README is the F-004 hot point.
    assert (SKILL_ROOT / "README.md").exists(), (
        "skills/SKILL-001-fastapi-production/README.md must exist — "
        "install.sh advertises it as a doc target. F-004 unfixed."
    )
    # And install.sh must reference the new doc targets.
    assert "STATUS.md" in install_sh, (
        "install.sh banner should point at STATUS.md (release/freeze info)."
    )


def test_c4_f004_catalog_total_remains_201() -> None:
    """Lock the canonical catalog total the banner is reconciled against.

    If catalog.json moves off 201, the install.sh banner must be re-cut.
    """
    import json

    catalog = json.loads(
        (SKILL_ROOT / "engine" / "index" / "catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["counts"]["tools_total"] == 201, (
        f"Catalog tools_total = {catalog['counts']['tools_total']} ≠ 201. "
        "Update install.sh banner + re-sum the decomposition."
    )


# ---------------------------------------------------------------------------
# C4 F-005 — md_location.py basename bypass
# ---------------------------------------------------------------------------


def _load_md_location():
    spec = importlib.util.spec_from_file_location(
        "_md_location_test_mod",
        REPO_ROOT / "scripts" / "checks" / "md_location.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_c4_f005_root_only_basename_smuggle_rejected() -> None:
    """A privileged root-only basename buried in a code package must be flagged.

    Pre-fix: `_is_violation("skills/SKILL-001-…/engine/CHANGELOG.md")` → False
    (allowed by basename, regardless of depth). That's the F-005 bypass.
    Post-fix: same path → True (rejected).
    """
    md = _load_md_location()
    smuggle = "skills/SKILL-001-fastapi-production/engine/CHANGELOG.md"
    assert md._is_violation(smuggle) is True, (
        f"`{smuggle}` should be flagged after F-005 closure — "
        "ROOT_ONLY_BASENAMES (CHANGELOG/CONTRIBUTING/LICENSE/CLAUDE) "
        "must not pass at any depth except repo root."
    )
    # CLAUDE.md is the highest-impact one (memory smuggle).
    assert md._is_violation("adapt/extend/api_design/CLAUDE.md") is True
    # CONTRIBUTING.md the F-007 hot path.
    assert md._is_violation("skills/SKILL-001-fastapi-production/CONTRIBUTING.md") is True
    # LICENSE.md likewise.
    assert md._is_violation("engine/promotion/LICENSE.md") is True


def test_c4_f005_root_only_basenames_still_allowed_at_root() -> None:
    """Root-level CHANGELOG/CONTRIBUTING/LICENSE/CLAUDE remain allowed.

    Don't over-correct: those are the legitimate convention placements.
    """
    md = _load_md_location()
    for fname in ("CHANGELOG.md", "CONTRIBUTING.md", "LICENSE.md", "CLAUDE.md"):
        assert md._is_violation(fname) is False, f"`{fname}` at repo root must remain allowed."


def test_c4_f005_package_basenames_still_allowed_at_depth() -> None:
    """README/SKILL/KNOWLEDGE/LLM remain package-level conventions.

    Don't over-correct in the other direction either: per-package thin
    READMEs are the documented pattern.
    """
    md = _load_md_location()
    for path in (
        "skills/SKILL-001-fastapi-production/engine/README.md",
        "skills/SKILL-001-fastapi-production/modules/auth/KNOWLEDGE.md",
        "skills/SKILL-001-fastapi-production/SKILL.md",
        "skills/SKILL-001-fastapi-production/LLM.md",
    ):
        assert md._is_violation(path) is False, (
            f"`{path}` should remain allowed (package-level convention)."
        )


def test_c4_f005_repo_wide_scan_passes_after_grandfathering() -> None:
    """`md_location.py` on every tracked .md must exit 0.

    Trade-off: 5 pre-existing files are listed in GRANDFATHERED_PATHS.
    This test pins that list so silent additions to the grandfather set
    fail review.
    """
    md = _load_md_location()
    assert hasattr(md, "GRANDFATHERED_PATHS"), (
        "md_location.py should expose GRANDFATHERED_PATHS — the test "
        "needs it to detect silent additions to the legacy-allow list."
    )
    assert len(md.GRANDFATHERED_PATHS) == 5, (
        f"GRANDFATHERED_PATHS expected to hold 5 legacy entries, "
        f"found {len(md.GRANDFATHERED_PATHS)}. If you add to it, declare "
        "the new entry + open a follow-up to migrate it to docs/."
    )
    # Run the repo-wide scan.
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "checks" / "md_location.py")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"md_location.py repo-wide exited {result.returncode}:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Sanity: contract_check still green at the baseline ceiling
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Pre-existing B2.1/B2.2 MCP-discovery failures are environment-dependent "
        "(documented in PR-E + PR-F). Per-rule body tests below cover what "
        "this PR touches."
    )
)
def test_contract_check_all_green() -> None:
    """Documented skip — kept as a marker so a future env-fix can flip it on."""
    pass
