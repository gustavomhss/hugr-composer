# Work Package Contract — `WP-16-engine-contract-check-split`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-16-specific content fills each section.
> Theme: **cohesion-driven decomposition of `engine/audit/contract_check.py`**
> (2 325 LOC superfile → ≥4 cohesive modules each ≤500 LOC) while preserving
> the public surface (`python -m engine.audit.contract_check`,
> `engine.audit.contract_check:main`) and emitting an identical 37/37 result.
>
> **Model elevation:** WP-16 runs on `opus`, not `sonnet`, because
> `contract_check.py` is the audit safety net — the file every other WAVE 1
> migration relies on for "did I break anything". A regression here flips the
> safety net silently. See §11 for the byte-equivalent diff-gate mandated for
> this WP.
>
> **This is a refactor-WP, not a tool-migration.** `add_cursor_pagination`
> (the WP-F1 golden) is cited only as a *pattern reference* for the per-tool
> directory layout idiom used elsewhere in WAVE 1; it is **not** the template
> for this WP. The split here is engine-internal — the public dotted path stays
> `engine.audit.contract_check`, the implementation modules live in a sibling
> package created by this WP.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-16-engine-contract-check-split` |
| **Title** | Split `engine/audit/contract_check.py` (2325 LOC) into ≥4 cohesive sub-modules, public surface preserved |
| **Wave** | `1` |
| **Depends on** | none (engine surface is self-contained; not blocked by the WAVE 1 tool migrations) |
| **Blocks** | none — sibling WPs (WP-01..03 + WP-Z2/C/D/E + WP-17) are file-disjoint; this WP touches only `engine/audit/contract_check.py` and creates a new sibling sub-package |
| **Branch** | `wp/16-engine-contract-check-split` (off the post-dependency main) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — engine code carries the audit contract; an undetected drift in any rule flips the safety net every other WAVE 1 WP relies on (§11) |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/engine/audit/contract_check.py    [REWRITE → thin facade]
  skills/SKILL-001-fastapi-production/engine/audit/contract_rules/
    __init__.py
    _common.py
    phase0_identity.py
    phase1_primitives.py
    phase2_catalog.py
    phase2_skill_md.py
    phase2_tier1.py
    phase3_benchmarks.py
    phase4_release.py
    _registry.py
  ```
- **Golden reference (pattern only, NOT a template):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` — cited solely as the "per-tool directory + cohesion" idiom used elsewhere in WAVE 1. This WP does NOT migrate a tool; it splits an engine superfile. Do not over-extrapolate the golden.
- **Shared base/contract to import (read-only):** none — `contract_check.py` is engine-internal; it imports only stdlib + `engine.promotion.state` (lazy, B1.8 rule) + `engine.bench.blind.*` (lazy, B3.7 rule) + `yaml`. These imports stay in their respective phase modules.
- **Spec to follow:** `docs/repo-standard.md` §3 (file-size cap), `docs/architecture.md` (engine layer), this manifest. CONTRACT.md (the file `contract_check.py` enforces) is the source of truth for rule ordering — do not re-order `RULES`.
- **Staging pool (read-only reference):** `core/venous/_staging/` — referenced by rule `_r_registry_exists` for the half-extracted-dir check. The rule moves verbatim into `phase1_primitives.py`; the staging tree itself is read-only.

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-01/02/03 (resiliency / observability / security) tools** — all `adapt/extend/infrastructure/add_<tool>/` directories listed in those manifests' §1.
- **WP-Z2/C/D/E (in-flight sibling WPs)** — every `adapt/extend/<category>/add_<tool>/` directory.
- **WP-17 (`_build_compose.py` split)** — the sibling engine superfile and the new sub-package `engine/audit/compose_data/` it creates. WP-16 must not touch a single byte of `_build_compose.py` or its split modules.
- **`engine/tests/test_delivery_contract.py`** — this is the behavior-preservation oracle (985 LOC of coverage). It MUST keep passing without edits. Touching it for any reason = WP rejected.
- **CONTRACT.md** — the source of truth for the rule ordering enforced by `RULES = [...]`. Do not reorder rules in CONTRACT.md to match a different split; the split must respect CONTRACT.md, not the other way around.
- **`pyproject.toml`, CI config, `.pre-commit-config.yaml`** — out of scope.
- **`engine/audit/__init__.py`** — currently empty. WP-16 keeps it empty unless re-exports are needed to preserve `from engine.audit.contract_check import …` — and even then only verbatim re-exports of names already public.
- **`hugr_auth/`, `core/venous/`, `adapt/`, `generators/`, `modules/`** — non-engine packages. Off limits.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)

### Goal
Decompose the 2 325-LOC `engine/audit/contract_check.py` into a cohesion-driven set of ≥4 sub-modules — each ≤500 LOC (hard cap per `docs/repo-standard.md` §3, sweet spot ≤300) — under a new `engine/audit/contract_rules/` package, while:
1. Preserving `python -m engine.audit.contract_check` as the entrypoint.
2. Preserving the `RULES` list ORDER verbatim (CONTRACT.md §B0.x → §B4.7 source of truth).
3. Preserving `engine.audit.contract_check.main()` as the public callable.
4. Yielding byte-identical pre/post output for `python -m engine.audit.contract_check` (37/37, same per-line text — §11 gate).
5. Keeping `pytest engine/tests/test_delivery_contract.py` green identically (985 LOC of coverage — the behavior oracle).

### Before
`engine/audit/contract_check.py` is a single 2 325-LOC module carrying:
- The `Rule` dataclass + 37 rule callbacks (`_r_*`) — each is a closed file-scoped function exercising one CONTRACT.md §B item.
- A module-level `RULES: list[Rule] = [...]` registry (37 entries) that is the contract-ordering source of truth.
- A `main()` CLI entrypoint with `--item` / `--phase` filters.
- Module constants: `REPO_ROOT`, `SKILL_ROOT`, `_SEMVER_RE`.
- Two top-level helpers: `_exists`, `_grep_count`.

The file is 4.6× the sweet-spot LOC cap and 4.6× the hard cap target. The
single hottest rule, `_r_skill_md_contract` (B2.5), is 448 LOC on its own —
nearly an entire module's budget worth of one rule.

### After
- Package `engine/audit/contract_rules/` exists with the modules in §3
  Decomposition.
- `engine/audit/contract_check.py` becomes a thin facade: imports `RULES` and
  `main` from `engine.audit.contract_rules`, re-exports both, and keeps the
  `if __name__ == "__main__": sys.exit(main())` shim.
- `engine/audit/contract_check.py` final LOC ≤ 30 (facade only). It is
  EXPLICITLY kept (not deleted) so `python -m engine.audit.contract_check`
  + `from engine.audit.contract_check import main` consumers see no churn.
- No public name added or removed. No rule deleted, renamed, or re-ordered.
- No CONTRACT.md text touched.
- The `_SEMVER_RE` constant moves to `_common.py`; rules that use it import
  from `_common`. No re-definition allowed (DRY — Codex v5 M2 caught the
  original drift).
- Each new module opens with a 5–10-line docstring stating its CONTRACT.md
  scope (phase + rule IDs) + its single responsibility.

### Decomposition (mandatory — invariant I2)

| # | Module path (under `engine/audit/contract_rules/`) | Est. LOC | Rules / responsibilities | Depends on (modules) |
|---:|---|---:|---|---|
| 1 | `_common.py` | ~60 | `REPO_ROOT`, `SKILL_ROOT`, `_SEMVER_RE`, `Rule` dataclass, helpers `_exists`, `_grep_count`. The shared base every phase module imports. | stdlib only |
| 2 | `phase0_identity.py` | ~270 | §B0.1 `_r_product_md`, §B0.2 `_r_roadmap_md`, §B0.3 `_r_contract_md`, §B0.4 `_r_skillmd_honest`, §B0.5 `_r_readme_md` (114 LOC — single largest in phase), §B0.6 `_r_claude_memory`, §B0.7 `_r_benchmark_no_stubs`, §B0.8 `_r_gitignore_artefacts`. **Cohesion:** all eight rules read top-level repo / skill identity docs (`PRODUCT.md`, `ROADMAP.md`, `CONTRACT.md`, `README.md`, `SKILL.md`, `.gitignore`, `~/.claude/projects/`); they share `_exists` and rely on the same INVENTORY-as-source-of-truth surface-count pattern. | `_common` |
| 3 | `phase1_primitives.py` | ~390 | §B1.0 `_r_core_venous_distribution`, §B1.0.1 `_r_adapter_layer_invariant`, §B1.1 `_r_registry_exists`, §B1.2 `_r_compose_with_coverage`, §B1.3 `_r_tools_import_primitives`, §B1.5 `_r_no_manual_mcp_tool_decorator`, §B1.6 `_r_no_orphan_generators`, §B1.7 `_r_adapter_coverage`, §B1.8 `_r_tier_lite_eligibility` (78 LOC — lazy-imports `engine.promotion.state`). **Cohesion:** every rule reads `core/venous/`, `engine/primitives_by_concern.yaml`, or `engine/index/catalog.json` and asserts a property of the primitive layer (registry sync, framework-purity, sibling-pairing coverage, adapter wiring, orphan-generator detection, lite-tier eligibility). | `_common` (+ lazy `engine.promotion.state`) |
| 4 | `phase2_catalog.py` | ~215 | §B2.1 `_r_find_primitive_discovery`, §B2.2 `_r_suggest_composition`, §B2.3 `_r_docs_site`, §B2.4 `_r_index_manifest`. **Cohesion:** all four rules subprocess-shell into `engine.{discovery,docs,index}.*` modules, parse the catalog manifest, and exercise an MCP-tool registration smoke. They share the `env_pythonpath = str(SKILL_ROOT)` + subprocess pattern. | `_common` |
| 5 | `phase2_skill_md.py` | ~470 | §B2.5 `_r_skill_md_contract` (448 LOC — single largest rule in the file, enforces the 20-rule Anthropic Agent Skills contract: frontmatter shape, SPDX→LICENSE signature match for 19 licenses, body sections, machine-readable YAML, transcript validation, footer version sync). Isolated in its own module because its sheer size + the `_license_signatures` table + `_gnu_sig` factory dominate its budget; co-locating it with other B2 rules pushed `phase2_catalog.py` over the cap. | `_common` |
| 6 | `phase2_tier1.py` | ~160 | §B2.6 `_r_tier1_surface_truth` (145 LOC). Separate from `phase2_catalog.py` because B2.6 is the only B2 rule that parses `mcp_tools/tier1.py` (runtime-string truth check), uses a different family of regexes (`MCP_TOOL_*` dict literals + workflow lists), and shares no helper with the rest of B2 except `_common`. Splitting B2 into catalog + skill_md + tier1 keeps every module ≤500 LOC and respects the three distinct surfaces B2 rules audit (catalog file, Maestro entry doc, tier-1 runtime tool surface). | `_common` |
| 7 | `phase3_benchmarks.py` | ~220 | §B3.1 `_r_bench_specs`, §B3.2 + §B3.3 `_r_bench_rubric_runner` (shared callback for two rule IDs — preserved verbatim, see F-02), §B3.4 `_r_bench_nightly_workflow`, §B3.5 `_r_benchmark_score`, §B3.6 `_r_code_level_benchmark`, §B3.7 `_r_blind_benchmark_harness` (lazy-imports `engine.bench.blind.*`). **Cohesion:** all rules read `benchmarks/*.json`, run `engine.bench.*` subprocess smokes, or validate the nightly CI workflow + scorefiles. | `_common` |
| 8 | `phase4_release.py` | ~400 | §B4.1 `_r_install_docker_ci`, §B4.2 `_r_examples_populated`, §B4.3 `_r_docs_site_v1`, §B4.4 `_r_changelog_semver`, §B4.5 `_r_contributing_md`, §B4.6 `_r_version_sync`, §B4.7 `_r_counts_sync` (223 LOC — single largest in phase, holds the INVENTORY ↔ {CLAUDE/STATUS/ROADMAP/CHANGELOG/SKILL/FREEZE/INTERFACES} reconciliation). **Cohesion:** every rule audits a release-surface doc (README site, install path, examples, CHANGELOG, VERSION triplet, narrative-doc count sync). | `_common` |
| 9 | `_registry.py` | ~120 | The `RULES: list[Rule] = [...]` registry — imports every `_r_*` callback from the phase modules above and ASSEMBLES them in the exact CONTRACT.md order (B0.1 → B4.7). Also hosts the `main()` CLI (argparse, filter logic, pass/fail loop, exit code). | every `phase*` module + `_common` |
| 10 | `__init__.py` (`contract_rules/`) | ~10 | `from ._registry import RULES, main` re-export. Enables `from engine.audit.contract_rules import RULES, main`. | `_registry` |

**Surviving facade:** `engine/audit/contract_check.py` shrinks to ≤30 LOC:

```python
"""CONTRACT.md machine enforcer (facade).

Implementation moved to ``engine.audit.contract_rules`` (split per WP-16).
This module preserves the historic public surface:

    python -m engine.audit.contract_check
    from engine.audit.contract_check import main, RULES
"""
from __future__ import annotations
import sys
from engine.audit.contract_rules import RULES, main

__all__ = ["RULES", "main"]

if __name__ == "__main__":
    sys.exit(main())
```

### Dependency graph (cycle-free — invariant I12)

```
                 ┌───────────────┐
                 │   _common     │  ← stdlib only
                 └───────┬───────┘
                         │ imported by
   ┌────────┬────────────┼────────────┬────────┬────────┐
   ▼        ▼            ▼            ▼        ▼        ▼
phase0   phase1      phase2_*     phase3   phase4
identity primitives  (catalog,    benches  release
                     skill_md,
                     tier1)
   │        │            │            │        │
   └────────┴────────────┴────────────┴────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  _registry   │  imports every phase_*; assembles RULES; main()
                  └──────┬───────┘
                         │
                         ▼
                ┌──────────────────┐
                │   __init__.py    │  re-exports RULES + main
                └──────┬───────────┘
                       │
                       ▼
       engine/audit/contract_check.py (facade)
       — re-exports from contract_rules
```

No back-edges. `_common` has zero in-package edges. `_registry` is the single
import sink. Each `phase*` is a leaf in the call graph from `_registry`.
Topological sort: `_common → phase0..phase4 → _registry → __init__ → facade`.

### Out of scope
- Any change to rule logic, message text, exit code, output formatting, or
  pass/fail criterion. Behavior is identical pre/post per §11.
- Renaming any rule callback (`_r_*`) or rule ID (`B0.1` etc.).
- Re-ordering `RULES`. The CONTRACT.md ordering is the source of truth; the
  list literal in `_registry.py` MUST hold the same 37 entries in the same
  order as the pre-split file.
- Touching `engine/tests/test_delivery_contract.py`.
- Adding a new rule, deleting a rule, or merging two rules.
- Touching CONTRACT.md.
- "Improving" file paths, regex patterns, error messages, or skip-set
  membership — those are separate work packages.
- Promoting any lazy import to eager (e.g. `engine.promotion.state`,
  `engine.bench.blind.*`); a lazy import preserves CLI startup performance
  for `--item`/`--phase` filters that don't touch those rules. Test-time
  discovery of `phase1_primitives.py` must not eagerly pay the promotion-
  module cost when the caller filtered to a phase 0 rule (F-07).

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Output of `python -m engine.audit.contract_check` is byte-identical pre/post (§11 diff gate). Proven by §6 gate 1, not by claim.
- [ ] **Public surface preserved.** `from engine.audit.contract_check import main` and `from engine.audit.contract_check import RULES` resolve to objects with the same identity semantics (same callable, same list with same 37 `Rule` entries in the same order, by item id). Verified by §6 gate 4.
- [ ] **No module exceeds 500 LOC.** Hard cap per `docs/repo-standard.md` §3. Verified by `python scripts/checks/file_size.py engine/audit/contract_rules/` returning empty.
- [ ] **`engine/audit/contract_check.py` ≤ 30 LOC** (facade only) — verified by `wc -l`.
- [ ] **No new dependencies.** No `pyproject.toml` change. Lazy imports stay lazy.
- [ ] **`RULES` order preserved.** Pre-split `[r.item for r in RULES]` equals post-split `[r.item for r in RULES]` element-wise. Verified by §6 gate 4.
- [ ] **37/37 result identical.** `python -m engine.audit.contract_check` exits 0 with the same per-rule pass/fail breakdown (line by line) pre vs post. Verified by §11.
- [ ] **`pytest engine/tests/test_delivery_contract.py` green identically.** 985 LOC of coverage; same number passed pre vs post (§6 gate 5).
- [ ] **No stale staging-directory references.** The staging tree is `_staging/` (renamed in PR #24); no manifest text, comment, or code path may use the pre-rename name (DoD D10 enforces).
- [ ] **No silent rule deletion.** `engine.audit.contract_rules._registry.RULES` length == 37; every `B<n>.<m>` item id present pre is present post (§6 gate 4).
- [ ] **Docstrings honest.** Each new module's docstring states the CONTRACT.md scope it covers (phase + rule IDs). No module silently re-implements a helper from `_common`.
- [ ] **Cycle-free dependency graph.** `python -c "import engine.audit.contract_check"` succeeds; `python -m pyflakes engine/audit/contract_rules/` reports no `circular import` warning.

## 5. Behavior-preservation oracle (per §3 of the WP scope)

The behavior-preservation oracle for this WP is **NOT** a new emitted-test
(this is a refactor-WP, not a tool migration — per the WP-scope manifest §D-G
+ I8). The oracle is the EXISTING test suite + the EXISTING audit run:

1. **`engine.audit.contract_check`** itself, run via `python -m engine.audit.contract_check`, must return 37/37 with a byte-identical per-line output pre vs post (§11).
2. **`engine.tests.test_delivery_contract`** must run green identically pre vs post (`pytest engine/tests/test_delivery_contract.py -q`).
3. Per-phase filter behavior unchanged: `python -m engine.audit.contract_check --phase 0` returns the same 8/8 subset; `--phase 1` returns 9/9; `--phase 2` returns 6/6; `--phase 3` returns 7/7; `--phase 4` returns 7/7 (totals: 8+9+6+7+7 = 37 ✓).
4. Per-item filter behavior unchanged: `python -m engine.audit.contract_check --item B2.5` returns 1/1 (the largest single rule).

If any of (1)–(4) drift, **stop and report** — do not paper over.

**This WP does NOT emit a new test under P1 #15.** P1 #15 governs tool
migrations (each tool emits a behavior assertion in the generated project).
This WP is an engine-internal refactor; its oracle is the pre-existing
`engine.audit.contract_check` invocation + `test_delivery_contract` suite.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local

# Mandatory gate 1 — byte-equivalent pre/post comparison (§11)
git stash                              # park current split
$PY -m engine.audit.contract_check 2>&1 | tee /tmp/cc_pre.txt ; PRE=$?
git stash pop                          # restore split
$PY -m engine.audit.contract_check 2>&1 | tee /tmp/cc_post.txt ; POST=$?
test "$PRE" = "$POST"                  # exit codes match
diff -u /tmp/cc_pre.txt /tmp/cc_post.txt   # PASS = empty diff (byte-equivalent)

# Mandatory gate 2 — file-size cap (docs/repo-standard.md §3 hard cap 500 LOC)
$PY scripts/checks/file_size.py engine/audit/contract_check.py engine/audit/contract_rules/

# Mandatory gate 3 — ruff (lint + format)
$PY -m ruff check engine/audit/contract_check.py engine/audit/contract_rules/
$PY -m ruff format --check engine/audit/contract_check.py engine/audit/contract_rules/

# Mandatory gate 4 — public-surface + RULES order + count
$PY -c "
from engine.audit.contract_check import main, RULES
items = [r.item for r in RULES]
expected = ['B0.1','B0.2','B0.3','B0.4','B0.5','B0.6','B0.7','B0.8',
            'B1.0','B1.0.1','B1.1','B1.2','B1.3','B1.5','B1.6','B1.7','B1.8',
            'B2.1','B2.2','B2.3','B2.4','B2.5','B2.6',
            'B3.1','B3.2','B3.3','B3.4','B3.5','B3.6','B3.7',
            'B4.1','B4.2','B4.3','B4.4','B4.5','B4.6','B4.7']
assert items == expected, f'RULES order drift: {items}'
assert len(RULES) == 37, f'expected 37 rules, got {len(RULES)}'
print('public surface ok: 37 rules, order preserved')
"

# Mandatory gate 5 — delivery_contract test suite (the 985-LOC behavior oracle)
$PY -m pytest engine/tests/test_delivery_contract.py -q -p no:cacheprovider
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, §11
byte-equivalence diff MUST be PASS (zero-length diff).

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-16 owns (write surface):**
- `engine/audit/contract_check.py` — rewritten as ≤30-LOC facade.
- `engine/audit/contract_rules/` — NEW package, 9 files listed in §1.

**WP-16 must NOT touch (forbidden):**

| Owner | Forbidden paths |
|---|---|
| WP-17 | `engine/audit/_build_compose.py` + any new `engine/audit/compose_data/` sub-package created by WP-17 |
| WP-01/02/03 | every `adapt/extend/infrastructure/add_<tool>/` listed in their §1 |
| WP-Z2/C/D/E | every `adapt/extend/<category>/add_<tool>/` for the four sibling WPs |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Behavior oracle | `engine/tests/test_delivery_contract.py` (985 LOC — read-only here) |
| Source of truth | `/CONTRACT.md` (rule ordering source) |
| Shared | `pyproject.toml`, CI workflows, `.pre-commit-config.yaml`, `hugr_auth/`, `core/venous/`, `adapt/`, `generators/`, `modules/` |

`git diff --name-only main..HEAD` MUST list only paths inside §1 write surface (≤10 files: 1 rewritten facade + 9 new files in `contract_rules/`).

## 8. Estimated effort

Measurements taken on `main` at branch creation; LOC = `wc -l`.

| Source file | Current LOC | Target post-split modules (count + cumulative LOC) | Wall-clock | Model |
|---|---:|---|---:|---|
| `engine/audit/contract_check.py` | 2 325 | 1 facade (≤30) + 9 new modules in `contract_rules/` (~2 315 total, range 60–470 per module) | 6 – 8 h | `opus` |

**Model recommendation: `opus`.** Engine code carries the audit contract;
`sonnet` ran on the same surface during the v9 audit cycle missed the
`grading_check` matched-header BLOCKER + the freshness-pin circular
dependency. `opus` reasoning is required to read the per-module diff (§11),
judge cohesion boundaries between rules whose helpers overlap, and verify the
`RULES` order against CONTRACT.md by inspection. The single rule
`_r_skill_md_contract` (448 LOC) is itself denser than most files in the
repo; getting its module boundary right is `opus` territory.

## 9. Failure modes (≥8 anticipated traps — engine non-regression risk profile)

1. **F-01. Surface drift via missing re-export.**
   - *Symptom:* downstream importer (test, script, CI runner) fails with `ImportError: cannot import name 'main' from 'engine.audit.contract_check'`.
   - *Cause:* facade rewrites `contract_check.py` but forgets to re-export a public name (`RULES`, `main`, or the `Rule` dataclass) that an out-of-tree caller imports.
   - *STOP-and-report rule:* before split, `git grep -nE "from engine\.audit\.contract_check import" -- '*.py' '*.md'` to enumerate every consumer. Every name on the left of `import` MUST be re-exported by the new facade. Missing one = stop and report.

2. **F-02. Rule placement ambiguity (B3.2 + B3.3 share `_r_bench_rubric_runner`).**
   - *Symptom:* split moves the callback into one module but `RULES` references it from two `Rule(...)` entries; the assembled list breaks `import` if the second reference is left as a dangling name.
   - *Cause:* the source file uses a single callback for two rule items (lines 2253-2254). Splitting must preserve the shared callback as ONE function imported once and referenced by two `Rule(...)` entries.
   - *STOP-and-report rule:* `phase3_benchmarks.py` defines `_r_bench_rubric_runner` exactly once; `_registry.py` references it by name in both the B3.2 and B3.3 `Rule(...)` literals. Defining it twice = stop and report.

3. **F-03. Import cycle between `_registry` and a `phase*` module.**
   - *Symptom:* `python -c "import engine.audit.contract_check"` raises `ImportError` from a circular import.
   - *Cause:* a phase module accidentally imports from `_registry` (e.g. to reuse the `Rule` dataclass) instead of from `_common`.
   - *STOP-and-report rule:* the `Rule` dataclass lives in `_common.py`. Every phase module imports `Rule` from `_common`. `_registry.py` is the only module that imports `_r_*` callbacks from phase modules — never the reverse. Violation = stop and report.

4. **F-04. Performance regression via eager lazy-import promotion.**
   - *Symptom:* `python -m engine.audit.contract_check --item B0.1` (a phase-0 rule) takes noticeably longer post-split, because `phase1_primitives.py` import-time eagerly pulls `engine.promotion.state` (which `_r_tier_lite_eligibility` uses).
   - *Cause:* moving a function that did its import lazily inside its body to a place where the same import is now done at module top-level.
   - *STOP-and-report rule:* the lazy import in `_r_tier_lite_eligibility` (line ~522: `from engine.promotion.state import _detect_concurrency, _detect_framework_imports`) stays INSIDE the function. Same rule for `_r_blind_benchmark_harness` and `engine.bench.blind.*` (line ~1907). Eager promotion = stop and report.

5. **F-05. Output drift (byte-equivalence gate fails).**
   - *Symptom:* §11 diff is non-empty: a per-rule line of `python -m engine.audit.contract_check` output changed (e.g. spacing, success/failure message text, exit code).
   - *Cause:* the loop in `main()` was rewritten "for clarity" and now produces slightly different formatting; or a rule callback's success message changed during the move.
   - *STOP-and-report rule:* the `main()` body is moved VERBATIM into `_registry.py`. Every rule callback's `return True, "…"` message is moved character-by-character. Reformatting messages = stop and report.

6. **F-06. Dependency leak — `_common` grows beyond its scope.**
   - *Symptom:* a helper that only one rule needs (e.g. the `_gnu_sig` factory inside `_r_skill_md_contract`) gets hoisted to `_common.py` "to keep the module small". `_common.py` balloons; every phase module pays the cost.
   - *Cause:* over-eager DRY application.
   - *STOP-and-report rule:* `_common.py` holds ONLY: module constants (`REPO_ROOT`, `SKILL_ROOT`, `_SEMVER_RE`), the `Rule` dataclass, and the two helpers (`_exists`, `_grep_count`) that are demonstrably used by ≥2 phase modules in the source file. Anything else stays in the phase module that needs it. Hoisting more = stop and report.

7. **F-07. Test-time discovery breaks because of lazy-import gotchas.**
   - *Symptom:* `engine.tests.test_delivery_contract` (985 LOC) imports `RULES` to enumerate rules; the import now triggers a chain that loads `engine.promotion.state`, which calls `_detect_framework_imports` on the wrong tree under pytest's working directory, raising.
   - *Cause:* lazy import moved to module top during the split.
   - *STOP-and-report rule:* `pytest engine/tests/test_delivery_contract.py -q` runs green identically pre vs post. Any new test failure = stop and report.

8. **F-08. `RULES` order silently changes due to alphabetical sort in `_registry.py`.**
   - *Symptom:* `python -m engine.audit.contract_check --phase 0` returns a different subset because B0.x rules are now interleaved with B1.x in `RULES`.
   - *Cause:* author "sorted for tidiness" or appended phase imports alphabetically (`phase0_*, phase1_*, phase2_catalog, phase2_skill_md, phase2_tier1, phase3_*, phase4_*`) and `RULES` was assembled by import order rather than the CONTRACT.md order.
   - *STOP-and-report rule:* `_registry.py` holds an EXPLICIT `RULES = [Rule("B0.1", …), Rule("B0.2", …), …, Rule("B4.7", …)]` literal in CONTRACT.md order, NOT a `RULES = sum([phase0.RULES, phase1.RULES, …], [])` construction. The CONTRACT.md order is the source of truth, not the module organization.

9. **F-09. Silent rule deletion during the move.**
   - *Symptom:* `len(RULES) == 36` post-split. `python -m engine.audit.contract_check` reports 36/36 — *passes*, but a CONTRACT item is no longer audited.
   - *Cause:* a copy-paste mistake during the move dropped a `_r_*` callback or its `Rule(...)` entry.
   - *STOP-and-report rule:* gate 4 asserts `len(RULES) == 37` AND every B-id is present. CI fails before merge if either drifts.

10. **F-10. Hard-cap LOC breach for `phase2_skill_md.py`.**
    - *Symptom:* `_r_skill_md_contract` weighs in at 448 LOC; combined with module docstring + imports it lands at 470–490 LOC. A future small addition (e.g. one more SPDX identifier + its signature) pushes it past 500.
    - *Cause:* `_r_skill_md_contract` is dense by design (20 rules in one callback).
    - *STOP-and-report rule:* if the post-split file already lands ≥ 480 LOC, the WP-16 author MUST flag it in the PR body. If it lands > 500, **stop and report** — a sub-split (e.g. extracting `_license_signatures` to a sibling `_skill_md_license.py`) becomes its own follow-up WP and this WP does not ship.

11. **F-11. Hidden behavior leak via module-import side effects.**
    - *Symptom:* `python -c "import engine.audit.contract_check"` no longer raises during import, but `import engine.audit.contract_rules.phase2_catalog` *does* — because the latter eagerly imports `mcp_tools` at module top.
    - *Cause:* an import lifted from inside a function body to module top during the split.
    - *STOP-and-report rule:* every existing `import` inside a `_r_*` callback body STAYS inside that body. No new top-level imports beyond what `_common`, stdlib, `yaml` (lazy where the source had it lazy), and the standalone rule modules already need.

12. **F-12. Stale staging-directory token re-introduced.**
    - *Symptom:* grep finds the pre-PR-#24 staging-tree token in the new manifest or any new module.
    - *Cause:* author copied from an older brief that pre-dated PR #24's staging-tree rename.
    - *STOP-and-report rule:* the only legal staging-tree token in this WP is `_staging/`. Any other staging-tree name in `docs/wp/WP-16*` or `engine/audit/contract_rules/` = stop and report; rename to `_staging`.

13. **F-13. `engine/audit/__init__.py` accidentally edited.**
    - *Symptom:* `engine/audit/__init__.py` (currently empty) gains content "to re-export from contract_check".
    - *Cause:* author thought a top-level re-export was required for the public surface.
    - *STOP-and-report rule:* `engine/audit/__init__.py` STAYS empty (zero bytes). The public surface is `engine.audit.contract_check` — the FILE — not `engine.audit`. No `__init__.py` re-export is needed; the facade module itself provides the surface.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** `engine/audit/contract_rules/` package created with 9 files per §3 (including `__init__.py`).
- [ ] **D-02.** `engine/audit/contract_check.py` rewritten as ≤30-LOC facade.
- [ ] **D-03.** Every new file ≤500 LOC (gate 2). No file exceeds the hard cap.
- [ ] **D-04.** `_common.py` is the only module imported by every `phase*`; phase modules never import each other.
- [ ] **D-05.** `_registry.py` `RULES` literal in CONTRACT.md order; `len(RULES) == 37`; gate 4 green.
- [ ] **D-06.** `python -m engine.audit.contract_check` exits 0 with the same per-line output as pre-split. Diff = empty (§11 + gate 1).
- [ ] **D-07.** `pytest engine/tests/test_delivery_contract.py -q` PASS — same count green pre vs post (gate 5).
- [ ] **D-08.** `--phase 0/1/2/3/4` + `--item Bx.y` filter behavior identical pre vs post (sanity-spot-checked in §7).
- [ ] **D-09.** Ruff (check + format --check) green for the facade + every new module (gate 3).
- [ ] **D-10.** No stale staging-tree token anywhere in the WP-16 diff (only `_staging/` is legal post PR #24).
- [ ] **D-11.** `git diff --name-only main..HEAD` lists only paths in §1 write surface.
- [ ] **D-12.** Lazy imports (`engine.promotion.state` inside `_r_tier_lite_eligibility`, `engine.bench.blind.*` inside `_r_blind_benchmark_harness`) verified still INSIDE the function body.
- [ ] **D-13.** No edits to `engine/audit/__init__.py`, `engine/tests/test_delivery_contract.py`, or `/CONTRACT.md`.
- [ ] **D-14.** `_SEMVER_RE` defined exactly once (in `_common.py`); every consumer imports from `_common` (Codex v5 M2 anti-drift).
- [ ] **D-15.** Each new module's docstring states its CONTRACT.md scope (phase + rule IDs) per §4 invariant.
- [ ] **D-16.** Self-review: agent re-read its own diff as an adversarial reviewer (looking specifically for F-01..F-13 traps) and pasted findings in PR body.

## 11. Risk callout (WP-16-specific — engine audit safety-net blast radius)

**Why this section exists:** `engine/audit/contract_check.py` is the safety
net the entire WAVE-1 batch relies on for "did I break anything?". A subtle
drift in any of its 37 rules can ship as:

- A relaxed rule that no longer detects the drift class it was added to catch
  (every rule carries a comment naming the audit finding it closes — Codex v3
  B1, Sonnet parallel v6 L1, Codex v9 BLOCKER, etc. — losing one of those
  closures defeats the historic audit work).
- A tightened rule that fails CI on a legitimate state, blocking unrelated
  PRs from landing.
- A rule whose output text changes, breaking downstream parsers (CI logs are
  scraped by humans + grep; line-text shape is part of the surface).
- An import-cycle that silently disables `python -m engine.audit.contract_check`
  at runtime, leaving the audit job green-by-omission.
- A lazy import promoted to eager, paying a multi-hundred-ms cost on every
  CLI invocation (the audit job runs in pre-commit + CI + locally — that
  cost compounds).
- A re-ordering of `RULES` that breaks `--phase N` semantics, producing the
  wrong subset for partial runs.

**Mitigation: byte-equivalent pre/post output gate.** Before declaring this
WP done, the agent MUST capture both outputs and diff them:

```bash
# Pre-split capture (on main, BEFORE the WP branch)
git checkout main
PY=.venv/bin/python
$PY -m engine.audit.contract_check 2>&1 | tee /tmp/cc_pre.txt
PRE_EXIT=$?

# Post-split capture (on the WP branch, AFTER the split)
git checkout wp/16-engine-contract-check-split
$PY -m engine.audit.contract_check 2>&1 | tee /tmp/cc_post.txt
POST_EXIT=$?

# Byte-equivalent OR rule-by-rule pre/post comparison gate
test "$PRE_EXIT" = "$POST_EXIT"          # exit codes match
diff -u /tmp/cc_pre.txt /tmp/cc_post.txt  # PASS = empty

# Rule-by-rule cross-check (defense-in-depth: catches the case where
# whitespace/ANSI codes differ but the per-rule pass/fail is the same):
$PY -m engine.audit.contract_check --quiet 2>&1 | grep -E '^[[:space:]]+[✓✗]' | \
  awk '{print $2, $3}' | sort > /tmp/cc_pre_summary.txt
# (re-run on post branch and diff /tmp/cc_post_summary.txt)
```

PASS criteria (both must hold):
- exit codes identical AND
- byte-equivalent line-by-line output OR (where ANSI / timestamp noise
  intrudes) byte-equivalent rule-id × pass/fail summary.

Any non-empty diff for non-cosmetic reasons = **stop and report — do NOT
ship**. Paste the diff verbatim in the PR body. Cosmetic diffs (e.g.
trailing whitespace) MUST also be reported, not silently normalized.

Run the same gate against `pytest engine/tests/test_delivery_contract.py -q`:
the pass/fail count + per-test name list MUST match. The 985-LOC
delivery_contract suite is the engine's defense-in-depth oracle; a single
test flipping pre→post is a stop-and-report event.

**Model elevation rationale:** `opus` reasoning is required to read the §11
diff and judge "cosmetic" vs "behavioral" drift, especially for rule
callbacks that read JSON / YAML with non-deterministic key order (lazily
shrugged off as "cosmetic" by `sonnet` v8/v9 in past audit cycles). The
B2.5 `_r_skill_md_contract` rule (448 LOC) is also dense enough that
`sonnet` historically missed multiple sub-checks; `opus` is the model that
caught the SPDX→LICENSE signature gap (Codex v5 B1) — the same caliber of
attention is required for the split.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
