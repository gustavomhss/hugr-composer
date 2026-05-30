"""CONTRACT.md rule registry + CLI entrypoint.

CONTRACT.md scope: NONE (assembler module — no rule body lives here).

Assembles the ``RULES: list[Rule]`` literal in the CONTRACT.md order
(``B0.1 → B4.7``, 40 entries total post-F2) by importing every
``_r_*`` callback from the phase modules. The literal is hand-written
in CONTRACT.md order — NOT assembled from per-phase lists (WP-16 §6 +
F-08 anti-drift).

Also hosts ``main()`` — the ``argparse``-driven CLI that powers
``python -m engine.audit.contract_check``. Moved here verbatim from the
pre-split monolith so per-rule output text + exit codes are byte-
identical to pre-split (WP-16 §11 byte-equivalence gate).
"""

from __future__ import annotations

import argparse
import sys

from ._common import Rule
from .phase0_identity import (
    _r_agent_memory_pointer,
    _r_benchmark_no_stubs,
    _r_contract_md,
    _r_gitignore_artefacts,
    _r_no_legacy_terminology,
    _r_product_md,
    _r_readme_md,
    _r_roadmap_md,
    _r_skillmd_honest,
)
from .phase1_primitives import (
    _r_adapter_coverage,
    _r_adapter_layer_invariant,
    _r_compose_with_coverage,
    _r_core_venous_distribution,
    _r_no_manual_mcp_tool_decorator,
    _r_no_orphan_generators,
    _r_registry_exists,
    _r_tier_lite_eligibility,
    _r_tools_import_primitives,
)
from .phase2_catalog import (
    _r_catalog_schema_version,
    _r_docs_site,
    _r_find_primitive_discovery,
    _r_index_manifest,
    _r_suggest_composition,
)
from .phase2_skill_md import _r_skill_md_contract
from .phase2_tier1 import _r_tier1_surface_inventory, _r_tier1_surface_truth
from .phase3_benchmarks import (
    _r_bench_nightly_workflow,
    _r_bench_rubric_runner,
    _r_bench_specs,
    _r_benchmark_score,
    _r_blind_benchmark_harness,
    _r_code_level_benchmark,
)
from .phase4_release import (
    _r_changelog_semver,
    _r_contributing_md,
    _r_counts_sync,
    _r_docs_site_v1,
    _r_examples_populated,
    _r_install_docker_ci,
    _r_version_sync,
)

# ---------------------------------------------------------------------------
# RULES — explicit literal, CONTRACT.md order (NOT a sum-of-phase-lists).
#
# Order is the source of truth: every Rule(item, phase, description, check)
# tuple is hand-listed in the same order as the pre-split monolith. F-02
# note: B3.2 and B3.3 share the single callback ``_r_bench_rubric_runner``
# by design — defined once in phase3_benchmarks, referenced twice here.
# ---------------------------------------------------------------------------
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
