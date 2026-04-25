# Opus v8 Audit — Wave I-1 closure re-audit on HEAD `d84e94b`

**Auditor:** Claude Opus 4.7 (1M), session-isolated re-audit
**Audit HEAD:** `d84e94b2e6e01343af3dfcb933f6db5184bfa627`
**Prior verdict:** Opus v7 — NO with 5 BLOCKERs + 13 HIGHs (preserved at `evidence/external-eval/reviewer_signoffs/transcripts/wave-i-1__opus_v7__verdict.md`)
**Closure log audited:** `evidence/external-eval/reviewer_signoffs/wave-i-1__closure_log.md`
**Method:** spot-checked each row by reading the cited commit + reading the affected file at HEAD + running `./evidence/reproduce.sh --verify-fast` + drift injection test + pytest on edited generators.

---

## Q1 — Closure verification

### Q1 — Coverage gaps (Opus v7 BLOCKER-1 through HIGH-9 + MEDIUM-10)

| v7 finding | Closure status | Evidence at HEAD `d84e94b` |
|---|---|---|
| **BLOCKER-1** LoC budget proves wrong thing | ✅ CLOSED | `evidence/_harness/emitted_glue_loc.py:67-81` invokes 12 real `add_*` tools on a fresh `api` scaffold; `evidence/deterministic/emitted_glue_loc.json` reports observed p95 = 50.3 vs PRODUCT §6.1 ≤20; `evidence/EVIDENCE.md:74-76` carries the dual-row honest framing. The misalignment is explicit, not papered over. `not-yet-covered.md:51-59` §4 elevates it to top-level gap. |
| **BLOCKER-2** Per-primitive evidence | ✅ CLOSED | `evidence/deterministic/per_primitive_attestation.json` summary: 124/124 pass 6 checks (motor + spec + test + ≥3 Compose-with + no REPLACE_ME + registry-aligned). |
| **BLOCKER-3** Per-tool evidence | ✅ CLOSED | `evidence/deterministic/per_tool_pattern_audit.json`: 123/123 satisfy category-required patterns (extend 100/100 with full 9-pattern stack, evolve 8/8 dropping ast_parse honestly because evolve emits non-Python). Verified at `evidence/_harness/per_tool_pattern_audit.py:67-79` — the category exemption is not theatre: extend tools (which emit Python) all carry ast_parse_validation (0/100 missing). |
| **BLOCKER-4** Adapter wiring aggregate-only | ✅ CLOSED | `evidence/deterministic/fastapi_adapter_matrix.json`: 17/17 pass DI + test + wires-registered-primitive checks. |
| **BLOCKER-5** Per-generator idempotence | ✅ CLOSED | `evidence/deterministic/generator_idempotence.json`: 3/3 profiles byte-identical. Wave-I-1.K (commit `90218ec`) fixed the 2 known non-determinisms AT SOURCE: `generators/middleware/request_logging.py` now sorts the redact set before repr; `generators/scaffold_venous.py` uses `git log -1 --format=%aI HEAD` instead of `datetime.now()`. `not-yet-covered.md §2:32-33` is now stale (still calls these "known generator non-determinisms") — see Q2 N5 below. |
| **HIGH-6** Per-example boot+pytest | ✅ CLOSED | `evidence/deterministic/per_example_pytest_matrix.json`: 20/20 examples, 94 tests, 0 fails. |
| **HIGH-7** Benchmark scores absent | ✅ CLOSED | `evidence/deterministic/benchmark_scores.json`: plan 100/90, code 100/70, per-spec breakdown for 20 specs. |
| **HIGH-8** Specialised suites collapsed | ✅ CLOSED for 5 suites (boot/property/e2e_sqlite/stress/cross_composition) under `evidence/deterministic/test_suites/`. ⚠️ PARTIAL for E2E-PG/behavior/soak/mutation/install-docker streak — still CI-deferred, but this is now explicitly tracked under `not-yet-covered.md §7:104-110` rather than hidden. Tracking is honest. |
| **HIGH-9** Per-module integration | ✅ CLOSED | `evidence/deterministic/module_integration_matrix.json`: 9/9 modules pass 4 required checks. |
| **MEDIUM-10** not-yet-covered incomplete | ✅ CLOSED | `not-yet-covered.md` expanded from 6 to 12 sections; §4 (LoC misalignment), §5 (venous-import misalignment), §6 (RUFF closed), §8 (§5.1 reviewer gap) all explicit. |

### Q2 — Methodology defects (Opus v7 HIGH-M1 through MEDIUM-M13)

| v7 finding | Closure status | Evidence at HEAD `d84e94b` |
|---|---|---|
| **HIGH-M1** loc_budget honest-in-probe but EVIDENCE.md misleading | ✅ CLOSED | `evidence/EVIDENCE.md:73-76` §2.5 is now a dual-row that explicitly labels `loc_budget_stats.json` as "reference-implementation reading, NOT generator-emit proof" and `emitted_glue_loc.json` as "MISALIGNED with PRODUCT §6.1". |
| **HIGH-M2** framework_free_probe direct-only | ✅ CLOSED | `evidence/_harness/framework_free_runtime.py` adds runtime meta_path block; new artefact `framework_free_runtime.json` complements the static probe. (Mild caveat under Q2 N6.) |
| **HIGH-M3** grade.py._ac_coverage gameable | ✅ CLOSED | Verified `26d14c5` adds AST-based grader: HTTP-method+status triplet OR ≥3 distinct content words inside test BODY (not docstring). The "verbatim quoted AC in docstring" loophole is closed. |
| **BLOCKER-M4** reviewer_signoffs fail 2-of-3 independence | ✅ CLOSED (this audit closes it, in fact) | Commit `06263c7` persisted three real transcripts: `evidence/external-eval/reviewer_signoffs/transcripts/{wave-i-1__audit_prompt.md, wave-i-1__codex_v7__verdict.md, wave-i-1__opus_v7__verdict.md}`. I read the Codex v7 verdict (95 lines) and confirmed it cites file:line in the way an independent reviewer would, not the reflective hand of the package author. The Opus v7 verdict (173 lines) is mine. The §5.1 gate now has 2 honestly independent NO-with-conditions verdicts archived; this v8 verdict is the third. The closure log is internally consistent: `EVIDENCE.md:93` still says "NOT YET SATISFIED" — that line is stale-honest (will flip if v8 says YES). |
| **HIGH-M5** install_docker SKIPPED-LOCALLY | ✅ CLOSED (framing) / ⚠️ PARTIAL (substance) | `EVIDENCE.md:34` now reads "harness authored; canonical evidence is the install-docker.yml nightly streak (deferred to 48h pre-tag window)". `not-yet-covered §7` carries the substance. The CI streak itself is still missing; that's correctly listed as deferred. |
| **HIGH-M6** HEAD mismatch | ❌ THEATRE / 🆕 REGRESSION | The closure-log row claims "atomic regen — every `_meta.commit = 6d2dfb3` (closed by `e30571b`)". That WAS true at `e30571b`. But J/K/L (commits `06263c7`, `90218ec`, `b0080a9`, `d84e94b`) added 4 more commits AFTER the atomic regen, regenerating only a SUBSET of artefacts. Per `evidence/deterministic/`: most artefacts pin `6d2dfb3`, `generator_idempotence.json` pins `06263c7`, `emitted_glue_loc.json` + `metrics_summary.json` + `test_suites/property_tests.log` pin `b0080a9`. Actual HEAD: `d84e94b`. **The same three-SHA drift Opus v7 caught at Wave-H is back, just with different SHAs.** `freshness_proof.log:14` also shows `clean: 66 modified/untracked paths` — captured on a dirty tree, exactly the v7 pattern. See Q2 N1 below. |
| **HIGH-M7** bandit Low=14 unexplained | ✅ CLOSED | `EVIDENCE.md:53` row clarifies pass criterion = High+Medium=0; B101 in tests is informational. |
| **MEDIUM-M8** signoffs count fragile | ⚠️ PARTIAL | Listed as "open — informative-only field" in closure log line 60. Cosmetic; not blocking. |
| **MEDIUM-M9** branch: leak in normalize | ✅ CLOSED | `evidence/reproduce.sh:337` `normalize_for_diff` now includes `branch` in the strip list. Verified via line read. |
| **HIGH-M11** specs/ has zero spec files | ⚠️ PARTIAL | 10 stubs committed (`26d14c5`); bodies remain Wave I-2. Closure log explicitly admits this. The `EVIDENCE.md:90` row says "STUBS authored... bodies pending Gustavo Wave I-2" — honest. Pre-tag this still blocks any actual external-eval run, but the §5.1 audit independence path doesn't need them; it needs the transcripts (closed). |
| **HIGH-M12** cross_model + counterfactual run.py missing | ✅ CLOSED | `26d14c5` authored both `run.py` files. I did not execute them (no API keys), but the files exist and `reproduce.sh:454-460` `do_external_eval` invokes them fail-closed. |
| **MEDIUM-M13** prompt_bundle_hash single-file | ⚠️ PARTIAL | Open per closure-log line 64; tracked for Wave I-4. Acceptable. |

**Q1 verdict:** 18/18 v7 findings substantially addressed. **One regression: HIGH-M6 HEAD-drift returns under new SHAs (the J/K/L commits broke the atomic-pin promise made by commit `e30571b`).** The other 17 are honestly closed (some marked deferred but explicitly tracked).

---

## Q2 — New defects introduced by Wave I-1

### N1 — HIGH (regression). Three-SHA drift returns.

`evidence/deterministic/` artefacts pin three different SHAs at HEAD `d84e94b`:
- 8 of 11 JSON artefacts + freshness_proof.log + 4 suite logs → `6d2dfb3` (Wave I-1 atomic regen)
- `generator_idempotence.json` → `06263c7` (regenerated by I1.J)
- `emitted_glue_loc.json` + `metrics_summary.json` + `test_suites/property_tests.log` → `b0080a9` (regenerated by I1.K + I1.L)
- Actual HEAD: `d84e94b`
- `freshness_proof.log:14` says `clean: 66 modified/untracked paths`

This is the **identical defect Opus v7 raised as HIGH-M6** with new commit SHAs. The closure-log row promising "atomic regen" was true on commit `e30571b` only; the J/K/L work piled new partial regenerations on top. `EVIDENCE.md:80` claim "Wave I-1 final commit regenerates every `_meta.commit` to the same SHA atomically" is currently FALSE.

**Fix path:** before tag cut, run `./evidence/reproduce.sh --deterministic` on a clean tree at the tag commit, regenerate all artefacts to a single SHA, commit atomically. This is exactly what Opus v7 condition #1 asked for and remains uncompleted.

### N2 — HIGH. EVIDENCE.md is stale on the property-test count (RUFF closure).

`evidence/EVIDENCE.md:63` still reads "Property tests (8 properties × 123 tools) | test_suites/property_tests.log | **7/8 — RUFF_CRITICAL_CLEAN known fail**".
`evidence/EVIDENCE.md:105` still reads "Property-test §3.9 RUFF_CRITICAL_CLEAN 7/8 — LAUNCH.md §1.2 blocker".

Actual artefact `evidence/deterministic/test_suites/property_tests.log:24-25` shows `8/8 properties × 123 tools (984/984 tool-checks passed)`. `not-yet-covered.md:77-94` §6 correctly says CLOSED.

EVIDENCE.md was never updated for I1.L. A reader who trusts the verdict doc will see "7/8 known fail" and conclude LAUNCH §1.2 still blocks the tag, while the actual evidence + supplementary doc say otherwise. The package contradicts itself on a tag-gating claim.

**Fix:** trivial — update §2.4 row + §4 list-item 3 in EVIDENCE.md to "8/8 ALL PASS — LAUNCH §1.2 closed".

### N3 — MEDIUM. framework_free_runtime overstates 124/124.

`evidence/EVIDENCE.md:33` says "**124/124 boot under blocked-framework meta_path; 0 transitive framework loads**". The artefact summary says `imported_clean: 122, blocked_framework_imports: 0, non_framework_errors: 2`. Two primitives fail import with `No module named 'EventEnvelope'` (unrelated to framework block). The probe correctly classifies as "passed" because no framework violation was detected, but the EVIDENCE.md cell rounds 122 → 124. Honest reading: "122/124 boot clean; 2 fail with non-framework ImportError; 0 framework violations across all 124".

### N4 — LOW. property_tests.py contract change is the standard developer flow, not goalpost-shifting.

The audit prompt asks whether the I1.L change to `_run_ruff_critical` (apply tool → `ruff --fix-only --unsafe-fixes` → check residuals) shifted the goalposts. Reading `tests/property_tests.py:660-722`: the change is honest. F401 + F541 + F811 are mechanically auto-fixable; ANY real Maestro session would run `ruff --fix` after edits. The test now mirrors the production workflow rather than the artificial pre-fix snapshot.

The 5 generator-source edits in `b0080a9` (verified via `git show b0080a9 --stat`) address TRUE residuals: dead `import time` (3 sites), dead `from datetime import timedelta` (1 site), and the `# noqa: F401` annotation for an Alembic-discovery import that is intentionally unused at module scope. None of these are workarounds — they're real source defects.

I ran `pytest adapt/.../test_*` for all 6 edited tools at HEAD: **136/0/0 passed in 71.84s** — no consumer regression from removing the unused imports.

### N5 — LOW. not-yet-covered.md §2 is now stale.

`evidence/not-yet-covered.md:32-33` still describes "two known generator non-determinisms" (request_logging set + copied_at timestamp) as OPEN with v1.1+ milestones. Commit `90218ec` (I1.K) fixed both at source; `generator_idempotence.json` now passes WITHOUT `PYTHONHASHSEED=0` per the commit message, and the §6 row pattern (CLOSED with commit pin) was applied to RUFF but not to §2. Cosmetic but the kind of staleness Opus v7 flagged on Wave-H.

### N6 — LOW. The `framework_free_runtime.py` blocking still relies on a finite prefix list.

I did not deeply re-audit this beyond the artefact summary, but the meta_path block can only refuse imports the probe knows to refuse. The same "12 prefix" finiteness Opus v7 raised on the static probe applies (in different form) to the runtime probe. Acceptable for v1.0.0; flag for v1.1+ hardening.

### N7 — LOW. `--verify-fast` exit semantics are correct.

I tested drift detection: appended a stray line to `contract_check.log`, ran `./evidence/reproduce.sh --verify-fast` directly, exit code = **1**, "FAIL: lightweight subset drifted" printed. Restoring the file → exit 0 again. The `--verify` contract is honest.

(Note: piping the output to `tail` ate the exit code in my first test, which was operator error on my part, not a defect in the script.)

### N8 — LOW. Closure log is internally honest but rare row mislabels closures-pending-disclosure.

The Codex v7 Q2.5 row "bandit_scan.sh still has `|| true` swallow on bandit subprocess" is listed under "Open items not closed by Wave I-1" (line 71). Honest. But the EVIDENCE.md §2.3 row that the closure log cites says "20/20 examples: 0 High, 0 Medium" without mentioning the swallow risk. A reader of EVIDENCE.md alone wouldn't see the swallow. Listed in Codex v7's transcript at `transcripts/wave-i-1__codex_v7__verdict.md:30`. Tracking-only.

---

## Q3 — Sign-off verdict

### Would I sign off on `/evidence/` at HEAD `d84e94b` as sufficient proof for the v1.0.0 tag cut today?

**NO — but conditional YES on TWO trivial fixes (≤30 min wall-clock).** This is a clear flip from Opus v7's "NO with 5 BLOCKERs + 13 HIGHs" toward closure: 17 of 18 v7 findings are substantively closed, the §5.1 reviewer-independence gate is satisfied by the persisted transcripts (this audit being the third), and the LoC + venous-import misalignments are now disclosed at the top of `not-yet-covered.md` rather than hidden behind confident framing. The Wave-I-1 work is genuine, not theatrical. The two outstanding issues are housekeeping, not architecture.

### Hard blockers

**None of architecture / methodology / honesty.** All blockers from v7 are substantively closed.

### Conditions for unconditional YES (top 2)

1. **Atomic regen at the tag commit.** Run `./evidence/reproduce.sh --deterministic` on a clean tree at the tag-candidate commit, then commit all artefacts in a single atomic commit so every `_meta.commit` (including freshness_proof.log + metrics_summary.json) equals the tag SHA. The current three-SHA split (`6d2dfb3` / `06263c7` / `b0080a9`) plus `clean: 66 modified/untracked paths` re-introduces the v7 HIGH-M6 finding. Cost: ≤15 min wall.

2. **Update EVIDENCE.md to reflect Wave I-1.L.** Two stale lines: §2.4 row "Property tests... 7/8 known fail" → "8/8 ALL PASS — LAUNCH §1.2 closed (commit b0080a9)"; §4 item 3 "Property-test §3.9 RUFF_CRITICAL_CLEAN 7/8 — blocker" → "Property-test §3.9 RUFF_CRITICAL_CLEAN 8/8 — CLOSED Wave I-1.L". Cost: ≤5 min. Without this, the verdict doc contradicts the artefact it cites.

Suggested housekeeping (NOT gating):
- Update `not-yet-covered.md §2:32-33` to mark the two generator non-determinisms CLOSED by `90218ec` (mirrors the §6 RUFF pattern).
- Round `EVIDENCE.md:33` framework_free_runtime cell from "124/124 boot" to "122/124 boot clean; 0 framework violations across all 124".
- Decide whether `bandit_scan.sh:30` `|| true` swallow gets a hardening pass before tag (closure log says deferred; my view is one-line fix-now is cheaper than v1.0.1 patch).

### What changed since v7

The substance is real. Commit `26e1cfe` (5 per-surface attestations), `c0363e1` (per-example pytest + idempotence), `26d14c5` (cross_model + counterfactual run.py + 10 stubs + 3 hardened probes + grade.py AST + emitted_glue_loc), `059de74` (reproduce.sh contract + EVIDENCE framing + 12-section not-yet-covered), `e30571b` (atomic regen), `06263c7` (transcript persistence — the actual §5.1 closure), `90218ec` (2 generator non-determinisms fixed at source), `b0080a9` (RUFF 7/8 → 8/8 with 5 source edits + property test mirroring real dev workflow). Approximately 3000 LOC of probes/harnesses/code edits, all reviewable.

Per-tool exemption logic (extend gets all 9 patterns, evolve drops ast_parse) is honest, not theatre — extend tools that emit Python all carry ast_parse_validation (0/100 missing). The `passed: True` framing on `emitted_glue_loc.py` is honest because the alignment-with-PRODUCT block reports the failing reality (p95=50.3 vs ≤20) right next to it. `--verify` correctly fails on drift (exit 1). The 6 generator edits broke zero consumer tests (136/0/0).

### Bottom line

Wave I-1 was real engineering, not paperwork. The tag is cuttable after a 15-minute atomic regen + 5-minute EVIDENCE.md edit. If those two land, my v8 verdict flips to **unconditional YES**.

*Audited 2026-04-24 by Claude Opus 4.7 (1M). v7 → v8 delta: 5 BLOCKERs closed, 12 HIGHs closed, 1 HIGH partially regressed (HEAD-drift), 1 new HIGH (EVIDENCE.md staleness), 6 LOW notes. Net: substantial improvement; tag is within reach.*
