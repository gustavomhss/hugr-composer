# Opus Audit — Wave H `/evidence/` package (adversarial sign-off)

**Auditor:** Claude Opus 4.7 (1M), independent third reviewer
**HEAD at audit time:** `3f98703247dfc73d211588b6b3ae57a36337c0b4` (top of `main`)
**HEAD declared in evidence:** `80cf12c` (per `freshness_proof.log:9`, all deterministic `_meta.commit`)
**metrics_summary HEAD:** `ccaba80` (`evidence/metrics_summary.json:3`)
**Verdict:** **NO** — not sufficient to cut `v1.0.0` today. See Q3.

---

## Q1 — Coverage gaps

### BLOCKER-1. The LoC-budget claim is measured against files that violate CONTRACT §A2.

- **Claim (LAUNCH.md §2.2, PRODUCT §2 + §6.1):** "Tools emit ≤20 LOC glue; logic in primitives" → evidenced by `loc_budget_stats.json`.
- **Defect:** `evidence/deterministic/loc_budget_stats.json:183` reports `total_venous_imports: 0` across all 20 examples and every per-example entry (`venous_imports: 0`, lines 17, 24, 31, 40, 49, 57, 65, 73, 81, 89, 97, 105, 113, 121, 129, 137, 145, 153, 161, 169). CONTRACT §A2 (`CONTRACT.md:31-33`) says: *"Generated code imports from `core/venous/*`. Every file a tool writes includes ≥ 1 `from core.venous.<ns> import ...`. Tools producing zero such imports are rejected."* The probe itself (`evidence/_harness/loc_budget_probe.py:107-113`) admits the examples are pedagogical self-contained, not generator-emitted. The evidence therefore proves the WRONG thing: "hand-written pedagogical FastAPI apps have low LoC per handler." It does NOT prove "tools emit ≤20 LOC glue" — that claim has zero artefact behind it until `external-eval/single_shot_benchmark/` runs.
- **Proof needed:** `/evidence/deterministic/emitted_glue_loc.log` — invoke each of the 100 `adapt/extend/add_*.py` tools on a scaffolded project in a hermetic tmp dir, diff-measure the glue emitted into `app.py` / `routes/*.py` / `services/*.py`, report distribution of `loc_per_handler` + `venous_imports_per_handler > 0` ratio. ~150 LOC of harness + 5-15 min compute.

### BLOCKER-2. 124 primitives: framework-free is the ONLY attested per-primitive check.

- **Claim (PRODUCT §2, §6):** primitives are orthogonal motors with unit coverage.
- **Defect:** `evidence/deterministic/framework_free_proof.log` attests only framework-import absence (via 12 prefix regex). There is NO per-primitive pytest attestation; the 5387 pytest count is aggregate across `adapt/ core/venous/ engine/` (`pytest_full_sweep.log:2`) with no breakdown. The EVIDENCE.md §2 "Primitives framework-free" row (line 30) maps the claim only to `framework_free_proof.log`; CONTRACT §B1.2 "≥3 Compose-with examples" (`contract_check.log:20`) is covered only at doc level. Per-primitive unit coverage is NOT attested anywhere in `/evidence/`.
- **Proof needed:** `/evidence/deterministic/primitive_coverage.json` — run `pytest --cov=core/venous --cov-report=json` and attach; assert each of 124 primitives has ≥1 test touching it + ≥50% line coverage. ~30 LOC harness + regen overhead inside full sweep.

### BLOCKER-3. Zero per-tool evidence across 127 adapt tools.

- **Claim (PRODUCT §2, CONTRACT §B1.3):** 24 extend tools are Rails-connected, 100 add_* + 27 other tools exist, each emits thin glue + wires primitives.
- **Defect:** pytest aggregate collapses 127 tools into a single number. There is NO `/evidence/deterministic/per_tool_manifest.json` attesting, per tool: (a) fingerprint check present, (b) idempotent rerun is byte-identical, (c) `elapsed_ms` present on every return path, (d) AST-parse loop present. CLAUDE.md under "Padrões obrigatórios" lists 9 required anti-patterns/18 CCs/12 QS — none of those checks appear as artefacts in `/evidence/`.
- **Proof needed:** `/evidence/deterministic/tool_pattern_audit.json` — iterate `adapt/extend/**/*.py`, assert presence of `MCP_TOOL`, `ensure_prerequisites`, `fingerprint`, `dry_run`, `elapsed_ms`, AST parse validation, lazy imports. ~80 LOC harness + <60s compute.

### BLOCKER-4. 17 FastAPI adapter wiring is aggregate-only.

`contract_check.log:25` has "17 fastapi adapters, 100% tested + map to registry" as ONE line. No per-adapter manifest lists which primitive each wraps, router signature, or test. Needs `/evidence/deterministic/adapter_manifest.json` (~40 LOC harness).

### BLOCKER-5. 56 generators: zero per-generator idempotence evidence.

PRODUCT §6.3 + CONTRACT §A4: "Running a tool twice does not clobber user edits." Only CATALOG `stable_hash` is idempotent-tested (`manifest_idempotence.log`); per-generator rerun-diff is absent. A generator that non-deterministically reorders imports evades `stable_hash`. Needs `/evidence/deterministic/generator_idempotence.json` — each generator run twice on throwaway scaffold, diff empty. ~100 LOC + 20 min compute.

### HIGH-6. Per-example "boot + emitted pytest" is absent.

- **Claim (PRODUCT §4):** emitted projects boot + tests pass.
- **Defect:** bandit + semgrep ran per-example, but NO `per_example_boot.log` attests uvicorn `/healthz` or `pytest` green per example. The Q1 prompt explicitly asked this. The grade.py rubric (`grade.py:25-52`) CAN do it, but lives only in the deferred external-eval harness.
- **Proof needed:** `/evidence/deterministic/per_example_boot.json` — 20 rows of {boot_ok, healthz_latency_ms, pytest_passed}. ~60 LOC + ~5 min compute.

### HIGH-7. 20 benchmark specs: plan + code scores NOT in `/evidence/`.

- **Claim (CLAUDE.md numbers, PRODUCT §4):** "20 benchmark specs (plan 100.00, code 100.00)".
- **Defect:** `contract_check.log:31` references benchmarks live in `benchmarks/latest_score.json` but there is NO `evidence/deterministic/benchmark_scores.json` snapshotted into the evidence package. A reader must leave `/evidence/` to trust the benchmark claim.
- **Proof needed:** commit `benchmarks/latest_score.json` into `/evidence/deterministic/benchmark_scores.json` with per-spec breakdown. Near-zero cost.

### HIGH-8. Specialized test suites invisible in evidence.

- **Claim (CLAUDE.md):** Boot (100), stress (27), property (984 assertions × 8 props), E2E SQLite (12), E2E PostgreSQL (8), behavior (12), cross-composition (200+), soak (5-min), mutation runner.
- **Defect:** all are collapsed into `pytest_full_sweep.log`'s single "5387 passed" line. LAUNCH.md §1.2 explicitly says "Property test suite exits 0. Current state: 7/8 — RUFF_CRITICAL_CLEAN fails on ~119 emitted templates" (`LAUNCH.md:37`) — a known partial-fail — yet `/evidence/` has no property suite log. The CI-deferred §1.2 row is unchecked in the LAUNCH checklist and no artefact proves it either way.
- **Proof needed:** one artefact per suite (`property_suite.log`, `e2e_sqlite.log`, `e2e_postgres.log`, `behavior_scenarios.log`, `cross_composition.log`, `soak.log`, `mutation_sample.log`). ~10 LOC harness per (separate pytest invocation per suite) + existing compute (already run in `ci.sh`).

### HIGH-9. 28 modules: zero per-module integration evidence.

- **Claim (CLAUDE.md):** 28 feature packages ready (auth, payments, caching, db, deployment, obs, security, background_jobs, websockets).
- **Defect:** no `module_integration.json` attests each module boots + wires + has ≥1 integration test.

### MEDIUM-10. `not-yet-covered.md` is incomplete.

- **Defect:** `evidence/not-yet-covered.md` lists 6 gaps, but OMITS:
  - 100 adapt/extend tools are aggregate-only (see BLOCKER-3).
  - 56 generators idempotence (see BLOCKER-5).
  - 20 benchmark scores not snapshotted in evidence (HIGH-7).
  - Property suite currently 7/8, known template Ruff failures (LAUNCH.md §1.2).
  - Named-human on-call (acknowledged in §6 of not-yet-covered for Phase C only; it is ALSO in `LAUNCH.md §1.4` as Gustavo ratification block — unchecked).
- LAUNCH.md §1.3 binds "No claim goes unaccounted for." The file misses several.

---

## Q2 — Methodology defects

### HIGH-M1. `loc_budget_probe.py` measures pedagogical code and labels it correctly in its JSON note — but EVIDENCE.md §2 lies about the binding.

- `loc_budget_probe.py:1-26` is HONEST in the docstring: *"This probe takes the PEDAGOGICAL examples... It is NOT a direct measurement of what tool X emitted."* The output JSON even has a `note` field (`loc_budget_stats.json:180`) stating the same caveat.
- But `EVIDENCE.md:29` states without caveat: *"Tools emit ≤20 LOC glue (§2, §6.1) | `loc_budget_stats.json` | p95 = 13.33 LOC/handler across 20 examples (≤20 target)"*. This IS the misleading branding the prompt hunts for. The honest disclaimer lives in the artefact; the verdict doc scrubs it.

### HIGH-M2. `framework_free_probe.py` only catches DIRECT imports.

`framework_free_probe.py:47-60` parses AST for `Import`/`ImportFrom` against a 12-prefix list. Misses: transitive imports (`pydantic` pulling `starlette` at runtime), dynamic imports (`importlib.import_module("fastapi")`), and doesn't differentiate `TYPE_CHECKING` blocks. Honest probe: import primitive in a venv where `fastapi` is uninstalled + verify `sys.modules` clean. Current probe is too permissive for §A2 "motors".

### HIGH-M3. `grade.py._ac_coverage` is gameable by prompt-reflection.

- `grade.py:90-96`: *"require the first 4 content words to co-occur in SOME test."* Any Maestro that includes the spec text verbatim in a test docstring — which a naive agent naturally does — passes this check trivially without the AC actually being implemented.
- Counter-evidence: the grade_version field pins the grader SHA — but that pinning only proves the grader is consistent, not correct. A grader that accepts "verbatim quoted AC in docstring" as coverage of "DELETE on another tenant's row returns 404, not 403" is a nominal-pass check. The AC_COVERAGE check SHOULD be AST-based: parse the acceptance criterion → derive expected HTTP method + path + status-code triplet → assert a test asserts that triplet.

### BLOCKER-M4. `reviewer_signoffs/` fail the 2-of-3 independence test.

- `reviewer_signoffs/opus.md:31` CONFESSES: *"verdict-summary by Claude (author, who is also the Opus instance that ran this review — the reviewer-author identity overlap is the honest limit of the Wave G design). Future audits SHOULD use an Opus instance with a separate session / no access to the author's scratchpad. For v1.0.0 the overlap is acknowledged."*
- `reviewer_signoffs/codex_v6.md:31-33`: *"Written post-Wave-H by Claude (author) as a verdict-summary; the raw review transcript lived in-session and was not persisted."*
- `reviewer_signoffs/sonnet.md:31`: same.
- `reviewer_signoffs/README.md:26-35`: *"Future audits (v1.1+) SHOULD archive the full raw transcript here at time of run — that is a process improvement item."*
- The LAUNCH.md §5.1 gating metric requires *"External reviewer independent sign-off: 2-of-3 YES... (Wave G already satisfied this)"*. The three files in `reviewer_signoffs/` are NOT three independent verdicts — they are three self-summaries authored by the same Claude instance that wrote the evidence package. This is a methodology defect, not a minor limitation. The §5.1 gate is NOT satisfied; the artefacts prove only that the AUTHOR believes the reviewers would have signed off. (Note: THIS audit — the Opus pass you are reading — is the only actually-independent third-party pass; write it to disk.)

### HIGH-M5. `install_docker_run.log` is SKIPPED-LOCALLY with no CI-streak evidence.

The local shell (`install_docker_run.sh:86-93`) replicates `install-docker.yml:30-100` faithfully (3 smoke tests: MCP discover≥100, contract_check, benchmark overall≥30). Commands match. BUT: LAUNCH.md §1.2 (`LAUNCH.md:42`) requires "install-docker.yml nightly green for 2 consecutive nights in the 48h window." There is NO evidence in `/evidence/` of ANY nightly green run. Pointing to CI from SKIPPED-LOCALLY is not proof of CI green. Needs `/evidence/deterministic/install_docker_ci_streak.log` = `gh run list --workflow=install-docker.yml --json status,conclusion,startedAt` snapshotted at evidence-capture time.

### HIGH-M6. HEAD mismatch across the package.

- `freshness_proof.log:10`: commit `80cf12c`, "clean: 2 modified/untracked paths" (NOT CLEAN).
- All other deterministic `_meta.commit`: `80cf12c`.
- `metrics_summary.json:3`: commit `ccaba80` (different).
- Actual repo HEAD at this audit: `3f98703`.
- `reproduce.sh --verify` (line 224-263) uses `git rev-parse HEAD` and regenerates against CURRENT HEAD — so a `--verify` run at `3f98703` would produce a NEW commit header, the diff normalization (line 217-222) strips commit/tree/generated fields before comparing, so content-level drift would still be caught. OK.
- BUT: the freshness_proof says "clean: 2 modified/untracked paths" — the evidence package was captured on a dirty tree (not the committed state). LAUNCH.md §1.1 / §1.3 requires the evidence commit to match the tag commit. Today it doesn't: tag would be cut from `3f98703`, evidence was captured from `80cf12c` with 2 uncommitted paths. The evidence package is stale by its own definition (EVIDENCE.md:37).

### HIGH-M7. Bandit's "Low: 14" on 06-auth-saas is unexplained.

- `bandit_scan/06-auth-saas.log` reports `Low: 14` (B101 `assert_used` in test code). Aggregate across all 20 examples: many LOW. The grading is "High=0 AND Medium=0" (line 40) which passes, but this means the OWASP-strength claim in EVIDENCE.md §2 is weaker than stated: "20/20 examples clean" is true only for High+Medium; LOW is non-zero and uninspected. The `.bandit` config to suppress B101 in tests (standard practice) is absent. OK for pass/fail but the "clean" framing is loose.

### MEDIUM-M8. `metrics_summary.py:152` signoffs count is fragile.

`len(list((EXT / "reviewer_signoffs").glob("*.md"))) - 1  # minus README` — assumes exactly one README. A second top-level .md inflates the count. Should exclude by explicit filename match.

### MEDIUM-M9. `reproduce.sh` normalization leaks `branch:` line.

`reproduce.sh:217-222` strips `generated|commit|tree|head_iso|head_msg|clean` but NOT `branch:  main` from `freshness_proof.log:14`. A CI `--verify` on a detached HEAD would spuriously fail diff.

### HIGH-M11. `specs/` has ZERO actual spec files.

- `single_shot_benchmark/specs/` contains ONLY `README.md`. No `01-*.md` through `10-*.md`. The README (`specs/README.md:25-43`) admits only "10 STUBS" with titles; stubs aren't even committed. Run.py (`run.py:74-77`) will fail `if len(specs) < 10: return 2` the moment a paid run is attempted. The 48h-pre-tag narrative is blocked on "~2-3h of founder voice authoring" that has not happened and is not owned on the critical path.

### HIGH-M12. cross_model_fnf + counterfactual harnesses are INCOMPLETE.

- `cross_model_fnf/_harness/` contains only `variance.py` — the post-run analysis. No `run.py`, no `prompt.md` symlink promised at `cross_model_fnf/README.md:29`. README claims "`prompt.md` (symlink → ../single_shot_benchmark/_harness/prompt.md)" — does not exist.
- `counterfactual/_harness/` contains only `baseline_prompt.md`. No `run.py`, no `compare.py`. README (`counterfactual/README.md:31-41`) claims both exist.
- `reproduce.sh:278-288` handles missing `run.py` gracefully with a `note`. But EVIDENCE.md §3 claims "harness authored" — it is NOT authored. Only fragments are authored.

### MEDIUM-M13. `prompt_bundle_hash` is computed over a SINGLE file.

- `run.py:46-50` hashes ONLY `prompt.md`. But the real system context any Maestro sees includes the MCP tool manifest + SKILL.md. Those aren't in the bundle hash. Two runs with different SKILL.md would appear identical in the manifest and the replayability claim is thinner than stated.

---

## Q3 — Sign-off verdict

### Would I sign off on `/evidence/` as sufficient proof for the v1.0.0 tag cut today?

**NO.** Not today. The evidence package is honest about many of its gaps — explicitly so in `not-yet-covered.md` — but several material defects are either incompletely disclosed or frame-misleading.

### Hard blockers

1. **LoC-budget evidence proves the wrong thing** (BLOCKER-1 + HIGH-M1). EVIDENCE.md §2 says "tools emit ≤20 LOC glue" is proven; the probe measures pedagogical code with ZERO venous imports. Fix: add `emitted_glue_loc.log` by invoking actual tools, OR rewrite EVIDENCE.md §2 row to say "20 examples are hand-written pedagogical references with p95 app_loc_per_handler = 13.33" and move the tool-emit claim to `not-yet-covered.md §4`.

2. **Reviewer sign-offs are author-self-summaries** (BLOCKER-M4). LAUNCH.md §5.1 gate "2-of-3 YES independent sign-off" is NOT satisfied. The current Opus audit (this doc) is the first actually-independent pass; persist it, then run Codex v6 + Sonnet passes independently against `/evidence/` and archive their raw transcripts. Without this, §5.1 is checked-false and pre-tag §1.3 bullet 5 fails.

3. **External-eval harnesses are incomplete** (HIGH-M11, HIGH-M12). Zero actual spec files committed under `single_shot_benchmark/specs/`; `cross_model_fnf/_harness/run.py` + `counterfactual/_harness/run.py` + `counterfactual/_harness/compare.py` all missing. The 48h-pre-tag window cannot succeed with missing runners; authoring during the tag window is the exact pattern Codex v6 flagged as theatrical.

4. **Per-tool / per-primitive / per-generator / per-module evidence is absent** (BLOCKERS 2-5, HIGH-9). Aggregate 5387 pytest count is NOT a substitute for "127 tools each satisfy the §B1 contract patterns." For a v1.0.0 claim of "201 tools indexed", per-tool attestation is table stakes.

5. **HEAD drift** (HIGH-M6). freshness_proof confesses the evidence was captured on a DIRTY tree (2 modified/untracked paths) at `80cf12c`; metrics_summary is at `ccaba80`; actual HEAD is `3f98703`. LAUNCH.md §1.3 requires evidence commit = tag commit. Today they differ across three SHAs.

### Top 3 conditions for conditional YES

If I were asked "yes conditional on N things" instead of "no today":

1. **Rerun `reproduce.sh --deterministic` at the exact tag HEAD** with a clean working tree, regenerating every artefact + `metrics_summary.json` in a single atomic commit. Freshness + three-SHA drift closes.
2. **Author the missing evidence harnesses + artefacts before tag cut, not after**: `emitted_glue_loc.log`, `primitive_coverage.json`, `tool_pattern_audit.json`, `per_example_boot.json`, `benchmark_scores.json`, `install_docker_ci_streak.log`, plus the 10 single_shot specs + the three missing run.py files. Rough budget: ~500 LOC of harness + ~2h wall-clock compute + ~3h Gustavo authoring specs.
3. **Execute the three paid external-eval runs AND archive raw transcripts for three INDEPENDENT reviewer passes** (fresh Codex session + fresh Sonnet session + this Opus pass persisted). Without independent-transcripts, §5.1 2-of-3 is un-auditable. Budget: ~$200-500 LLM + reviewer wall-clock.

### What Wave H got right (calibration, not cheerleading)

Two-class split (EVIDENCE.md §1) is architecturally correct. `not-yet-covered.md` is substantive. `reproduce.sh --verify` normalization is thoughtful. Bandit+semgrep per-example scans are solid (my semgrep-rules-empty suspicion was wrong — 544 OWASP rules load fine).

### Bottom line

The scaffolding is there; the finish work isn't. Don't cut `v1.0.0` this session. Close the 3 conditions, re-audit, then tag.

*Audited 2026-04-24 by Claude Opus 4.7 (1M). The author-reviewer overlap noted in `reviewer_signoffs/opus.md:31` applies here too — I am also Claude — but this session had the explicit instruction to hunt defects. Cited defects are real; whether they block `v1.0.0` is Gustavo's call.*
