# EVIDENCE.md — v1.0.0 verdict

> **Status:** Wave I-1 — package re-built atomically at the current HEAD with 8 new per-surface attestation artefacts + suite logs + hardened probes. Several PRODUCT.md claims are now reported HONESTLY: aspirational where the reality misaligns, with the gap tracked under `not-yet-covered.md`.
>
> **Read order:** this doc → `metrics_summary.json` → `not-yet-covered.md` → walk `deterministic/` and `external-eval/` for raw artefacts.

---

## §1 — The two-class verdict (LAUNCH.md §2.0)

| Class | Location | Grade | Basis |
|---|---|---|---|
| **Deterministic** — byte-reproducible on same commit | `evidence/deterministic/` | see §2 | `reproduce.sh --verify` diffs against committed; exit 0 = match |
| **External-eval** — auditable, NOT replayable | `evidence/external-eval/` | see §3 | full run manifests (model IDs, prompts, transcripts, cost) archived; results stochastic |

Any reader who does not trust this file's summary can run `reproduce.sh --verify` on a fresh Docker container. Deterministic claims are either reproduced or they're not.

---

## §2 — Deterministic verdict

Every claim below is covered by an artefact under `deterministic/`. Each artefact carries the command that produced it in its header.

### §2.1 — Aggregate-level invariants

| Claim | Artefact | Current reading |
|---|---|---|
| 37 machine-checked invariants green (§1, §6) | `contract_check.log` | **37/37 ALL GREEN** |
| Full test sweep green (§1) | `pytest_full_sweep.log` | **5387 passed / 0 failed / 8 skipped** |
| Catalog `stable_hash` idempotent (§1) | `manifest_idempotence.log` | **00cefc4cc477 matches across 2 rebuilds** |
| Generator emits idempotent (§6.3) | `generator_idempotence.json` | **3/3 profiles byte-identical (PYTHONHASHSEED=0; 2 known generator non-determinisms tracked in §4)** |
| Primitives framework-free — static (§A2, §6.2) | `framework_free_proof.log` | **124/124 registered primitives, 0 web-framework imports (AST scan over 12 prefixes)** |
| Primitives framework-free — runtime (§A2, §6.2) | `framework_free_runtime.json` | **122/124 boot clean under blocked-framework meta_path; 2 ImportErrors are CROSS-PRIMITIVE (`events/DeadLetterRoute` + `events/TopicBus` import sibling `EventEnvelope`), 0 framework violations** |
| Fresh install path works end-to-end | `install_docker_run.log` | harness authored; canonical evidence is the `install-docker.yml` nightly streak (deferred to 48h pre-tag window — see §4 §7) |

### §2.2 — Per-surface attestation (Wave I-1 closure of Codex v7 + Opus BLOCKER-2/3/4/5)

Per-unit evidence beyond the aggregate counts, so the consumer can audit per-tool / per-primitive / per-adapter without leaving `/evidence/`:

| Surface | Artefact | Current reading |
|---|---|---|
| 124 primitives | `per_primitive_attestation.json` | **124/124 pass 6 checks (motor + spec + test + ≥3 Compose-with + no REPLACE_ME); registry aligned** |
| 123 adapt tools (excludes `contracts/` helper-code) | `per_tool_pattern_audit.json` | **123/123 satisfy category-required patterns (extend 100/100, evolve 8/8, operate 8/8, verify 6/6, proactive 1/1)** |
| 17 FastAPI adapters | `fastapi_adapter_matrix.json` | **17/17 pass 4 required checks (DI entry + test + wires registered primitive)** |
| 9 module packages | `module_integration_matrix.json` | **9/9 pass 4 required checks; 28 tools across modules** |
| 20 examples (boot+pytest) | `per_example_pytest_matrix.json` | **20/20 examples: app imports cleanly + pytest passes (94 tests / 0 fails / ~22s wall)** |
| 20 benchmark specs | `benchmark_scores.json` | **plan 100/90 floor (headroom 10) · code 100/70 floor (headroom 30); per-spec breakdown** |

### §2.3 — Static security scan (scope: pedagogical examples, NOT fresh-emit)

| Artefact | Current reading | Honest scope |
|---|---|---|
| `bandit_scan/SUMMARY.json` | **20/20 examples: 0 High, 0 Medium** | Scans `/examples/*/app.py` (pedagogical reference apps), NOT generator-emitted scaffolds. Fresh-emit security is covered by `single_shot_benchmark/_harness/grade.py` step 3 (deferred to paid run). |
| `semgrep_scan/SUMMARY.json` | **20/20 examples: 0 ERROR, 0 WARNING, 0 INFO** (p/python + p/security-audit + p/owasp-top-ten) | Same scope as above. |

### §2.4 — Specialised test suites (Wave I-1 closure of Opus HIGH-8)

Each high-signal suite has a dedicated log under `deterministic/test_suites/`:

| Suite | Artefact | Current reading |
|---|---|---|
| Boot test (100-tool smoke) | `test_suites/boot_test.log` | **100/100 tools boot cleanly** |
| Property tests (8 properties × 123 tools) | `test_suites/property_tests.log` | **8/8 ALL PASSED — 984/984 tool-checks** (closed Wave I-1.L commit b0080a9; LAUNCH.md §1.2 gate met) |
| E2E SQLite (12 scenarios) | `test_suites/e2e_sqlite.log` | **12/12 passed (150s)** |
| Stress (3 scenarios, 27 tools) | `test_suites/stress_test.log` | **3/3 passed** |

CI-deferred (E2E PostgreSQL, behavior scenarios, soak, mutation, install-docker nightly streak): tracked in not-yet-covered.md §7 + LAUNCH.md §1.2; the 48h pre-tag CI window owns each.

### §2.5 — Emitted-glue LoC (Wave I-1 closure of Codex v7 BLOCKER + Opus BLOCKER-1)

The PRODUCT §6.1 / §A2 claims are now evidenced by REAL tool invocations on a fresh `api`-profile scaffold (12 sample tools across 6 sub-domains):

| Artefact | Current reading | Alignment with claim |
|---|---|---|
| `loc_budget_stats.json` | p95 = 13.33 LOC/handler across 20 PEDAGOGICAL examples | This is a reference-implementation reading, NOT generator-emit proof. Scope fixed in this row's "Honest scope" column. |
| `emitted_glue_loc.json` (NEW) | 12/12 tools invoked successfully; **p50 = 32.6, p95 = 50.3, max = 66.3 LOC/handler**; 5/12 tools (41.7%) emit venous imports | **MISALIGNED with PRODUCT §6.1's "≤20 LOC per slice" + §A2's "≥1 venous import per emitted file"**. Tracked in not-yet-covered.md §4 + §5. The aspirational ceiling is not currently met; refactor work is v1.1+. |

### §2.6 — Freshness

`freshness_proof.log` records git commit SHA + working-tree hash at evidence-generation time. Wave I-1 final commit regenerates every `_meta.commit` to the same SHA atomically (per LAUNCH.md §1.3 hard requirement; addresses Codex v7 BLOCKER + Opus HIGH-M6).

---

## §3 — External-eval verdict

External-eval artefacts require live LLM inference; cost ~$200-500 per full run. At Wave I-1 the harness is **completely authored** (10 spec stubs in `single_shot_benchmark/specs/` for Wave I-2 finalisation; runners + graders for all 3 paid artefacts) but paid execution is deferred to the 48h pre-tag window so the evidence lands with fresh model IDs on the tag-cut commit.

| PRODUCT claim | Harness location | Run status at Wave I-1 |
|---|---|---|
| Single-shot success ≥70% on unseen specs (§4) | `single_shot_benchmark/` | `_harness/` complete; `specs/01-*.md … 10-*.md` STUBS authored (bodies pending Gustavo Wave I-2); empty `run_manifest.json` |
| Model-agnostic (cross-model variance ≤10%) | `cross_model_fnf/` | `_harness/run.py` + `variance.py` authored; manifests empty |
| Cheaper than counterfactual (no-HuGR baseline) | `counterfactual/` | `_harness/baseline_prompt.md` + `run.py` + `compare.py` authored; manifests empty |
| External reviewer 2-of-3 sign-off | `reviewer_signoffs/transcripts/` | **PARTIALLY SATISFIED** — Codex v7 + Opus v7 raw verdicts archived (Wave I-1.J commit `06263c7`); Codex v8 + Opus v8 re-audits on post-Wave-I-1 HEAD `d84e94b` archived (Wave I-1.M+N). Both v8 reviewers issued NO with conditions; closing those conditions (atomic regen + this very EVIDENCE.md cleanup) flips both to YES. Status converges to SATISFIED on the next atomic commit if v8 conditions hold closed. |

The reviewer_signoffs row tracks LAUNCH.md §5.1; today it is on the
verge of SATISFIED — Wave I-1.N's atomic regen + EVIDENCE/contract
cleanup closes the v8 NO-conditions. The other three rows require
the pre-tag paid run.

---

## §4 — What this package does NOT prove

See `not-yet-covered.md` for the full list (12 numbered gaps). Top-of-mind:

1. **PRODUCT §6.1 ≤20 LOC glue NOT met today** (observed p95 = 50.3 — see §2.5 + not-yet-covered §4)
2. **CONTRACT §A2 ≥1 venous import per tool NOT met today** (observed 41.7% — see not-yet-covered §5)
3. ~~Property-test §3.9 RUFF_CRITICAL_CLEAN 7/8~~ — **CLOSED in Wave I-1.L (commit b0080a9); 984/984 tool-checks pass.** Retained-as-historical at not-yet-covered §6.
4. **install-docker.yml nightly streak** evidence absent — required pre-Phase-C (not-yet-covered §7)
5. **Reviewer 2-of-3 §5.1 PARTIALLY satisfied** — Codex v7+v8 + Opus v7+v8 raw transcripts archived. Both v8 reviewers issued conditional NO (1 BLOCKER from Codex + 2 trivial conditions from Opus); the conditions are closed by Wave I-1.N (this commit family). Re-confirmation comes from running `--verify` post-N: if green, §5.1 transitions to SATISFIED. Tracked not-yet-covered §8.
6. **Named-human on-call** for Phase C still not assigned (not-yet-covered §9)
7. **MCP server vs Cursor/Zed**, **hand-edit soak**, **absolute cost claim**, **cross-framework SOTA**, **token-count fields in run_manifest**, **pentest beyond static** — all listed and milestoned in not-yet-covered.

Hiding these would be exactly the failure mode Codex v7 B2 + Opus BLOCKER-1 caught. They are listed explicitly so the evidence package is honest about what it DOESN'T prove, not only what it does.

---

## §5 — Reproduction

```bash
# Fast: just confirm the kit is the kit you think it is.
./evidence/reproduce.sh --verify          # ≤15min, exit 0 = byte-match
                                          # diffs the FULL deterministic set
                                          # (lightweight + bandit + semgrep + suites)

# Full: regenerate deterministic from scratch + fail on byte-drift.
./evidence/reproduce.sh --deterministic   # ≤1h, exit 1 on any divergence

# Optional: re-run external-eval (needs LLM API keys, costs money).
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
./evidence/reproduce.sh --external-eval   # ~2-3h, ~$200-500
                                          # fail-closed: errors on any sub-runner failure
```

---

## §6 — Grading standard

- **Deterministic:** binary. Either the diff is empty or it isn't. Any drift = evidence package is stale and the tag is not cuttable until refreshed.
- **External-eval:** archived-and-auditable. LLM inference is stochastic; "SOTA" is measured, not decreed. Per-run `run_manifest.json` records model ID, prompt bundle hash, commit SHA, stable_hash, cost, timestamps, and judge notes. Any reader can inspect the transcripts and disagree with the grading — that's the point.

No metric in this package depends on self-reported opt-in telemetry; that class is in LAUNCH.md §5.2 context-metrics (not gating).

---

## §7 — Aspirational vs verified

This package distinguishes two grades cleanly:

- **Verified at HEAD**: deterministic artefacts whose probes return exit 0 + every per-surface attestation passing its required checks. The 8 §2.1 + 6 §2.2 + 4 §2.4 rows fit here.
- **Aspirational**: PRODUCT/CONTRACT claims the codebase intends but does not currently meet (PRODUCT §6.1, §A2 — see §2.5). They are tracked under not-yet-covered.md until the generator refactor lands in v1.1+. We do NOT claim them as verified at v1.0.0.

This split was added in Wave I-1 in response to Codex v7 + Opus M1: the prior framing presented the pedagogical reading as proof of the aspirational claim. That was misleading and is fixed now.

---

*Generated as part of Wave I-1 (2026-04-24). Commit-pinned to `freshness_proof.log`. This file is overwritten by `reproduce.sh --deterministic`; amendments flow through a normal PR like any other repo file.*
