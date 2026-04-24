# LAUNCH.md — v1.0.0 zero-risk launch protocol

> **Status:** DRAFT, pre-freeze. Binding at v1.0.0 tag cut.
> **Owners:** Gustavo (launch decisions), Claude (evidence package generation + monitoring).
> **Scope:** Everything between "tree is technically done" and "the public is using v1.0 in production without catastrophic surprise."

---

## §0 — Philosophy: belt + suspenders + tailored pants

Three redundant safeguards, each covering a failure mode the others don't:

| Layer | Protects against | Mechanism |
|---|---|---|
| **Belt — Evidence package** | Technical-critique vergonha ("isso é mal arquitetado") | `/evidence/` directory: documented + reproducible artefacts mapping every PRODUCT.md claim → a runnable proof |
| **Suspenders — Phased rollout** | UX/distribution vergonha ("não funciona na minha máquina") | Private alpha → closed beta → public; each phase has exit criteria that MUST clear before widening audience |
| **Tailored pants — Rollback-ready ops** | Post-launch catastrophe vergonha ("HuGR destroyed my DB") | `stable_hash` pinning + `v1.0.1` hotfix path + yank protocol (POST_RELEASE.md §2) + 72h monitoring |

Any ONE layer alone is insufficient. Rails / Django / FastAPI each shipped with roughly one of these. HuGR v1.0.0 ships with all three.

---

## §1 — Pre-tag gates (blocking cuts the tag)

Before `v1.0.0` can be cut from HEAD, every box below MUST be checked. Order is irrelevant; all are hard gates.

### §1.1 — Technical gates (machine-verifiable)

- [ ] `engine.audit.contract_check` returns 37/37 ALL GREEN on `main` at the exact HEAD being tagged.
- [ ] `pytest adapt/ core/venous/ engine/` returns 5387+ passed / 0 failed on the same HEAD.
- [ ] `engine.index.manifest verify` shows `stable_hash` idempotent across 2 consecutive rebuilds.
- [ ] VERSION triplet (repo root + skill dir + STATUS.md) all read `1.0.0` — §B4.6 enforced.
- [ ] CHANGELOG `[1.0.0]` header has real date (no `YYYY-MM-DD` placeholder).

### §1.2 — Test gates (currently CI-deferred — MUST run pre-tag)

- [ ] Property test suite (`tests/property_tests.py`) exits 0. Current state: 7/8 — RUFF_CRITICAL_CLEAN fails on ~119 emitted templates with F401 unused imports + F541 empty f-strings. Resolution required: either fix the emitted-template style (Wave-2 template cleanup per ROADMAP §6.1) OR ratify an explicit carve-out in CONTRACT §E.
- [ ] E2E PostgreSQL suite green in CI — nightly run verified within the 48h pre-tag window.
- [ ] Behavior scenarios (12 domain archetypes) green in CI — same window.
- [ ] Soak test (5-min wall, 10 concurrent) green in CI — same window.
- [ ] Mutation runner sample (≥10 modules) green in CI — same window.
- [ ] `install-docker.yml` nightly green for 2 consecutive nights in the 48h window.

### §1.3 — Evidence package committed (see §2 below)

- [ ] `/evidence/` directory exists at HEAD being tagged, with the
      deterministic/external-eval split per §2.0.
- [ ] Every PRODUCT.md §1-§6 claim is either (a) mapped to an
      artefact in §2.2's tables OR (b) listed in
      `/evidence/not-yet-covered.md` with an honest reason. No
      claim goes unaccounted for.
- [ ] `/evidence/reproduce.sh --verify` runs clean (≤15min) on a
      fresh Docker container — deterministic artefacts
      byte-identical to committed (modulo timestamp).
- [ ] `/evidence/reproduce.sh --deterministic` runs clean (≤1h) on a
      fresh Docker container and regenerates `/evidence/deterministic/**`
      byte-for-byte.
- [ ] `/evidence/external-eval/**` carries ≥1 complete run manifest
      for each external-eval artefact (single_shot / cross_model_fnf /
      counterfactual / reviewer_signoffs). External-eval results are
      NOT byte-reproducible; they ARE archived in full.

### §1.4 — Gustavo ratifications (human gates)

- [ ] `FREEZE.md §4` signed + dated.
- [ ] `CONTRACT.md §E` amended with §A12 + §B1.8 ratification block.
- [ ] `docs/decisions/0004-tier-lite.md` flipped Proposed → Ratified with date.
- [ ] `ROADMAP.md §11` signed.

### §1.5 — Launch readiness

- [ ] Alpha cohort identified (5-10 devs, personally known, have accepted the invitation).
- [ ] Feedback channel set up (private GitHub repo access OR direct DM / email thread).
- [ ] `POST_RELEASE.md §rollback` protocol dry-run completed (practice yank on a throwaway pre-release tag).

---

## §2 — Evidence package (`/evidence/`)

### §2.0 — Deterministic vs external-eval split

Evidence divides into two classes with different reproducibility
guarantees. Codex v6 LAUNCH review (B1) correctly flagged that the
earlier "byte-identical reproducible in Docker" claim was theatrical
— cross-model LLM evals + counterfactual runs + human-graded
dimensions cannot be deterministic. We split the package so each
class is held to its honest standard:

- **Deterministic artefacts** — reproducible byte-for-byte modulo
  timestamps (hash-after-normalize matches). Live under
  `/evidence/deterministic/`. A fresh `reproduce.sh --deterministic`
  run on the same git commit MUST produce identical content.
- **External-eval artefacts** — results depend on live LLM
  inference, provider availability, stochastic output, and
  (for hand-editability) human judgment. Live under
  `/evidence/external-eval/`. We archive the full input-output
  bundle (model IDs, prompt hashes, transcripts, cost, timestamps,
  judge notes) so the run is AUDITABLE, not replayable bit-for-bit.

The top-level `EVIDENCE.md` verdict cites both classes with the
honest grading for each.

### §2.1 — Structure

```
evidence/
├── EVIDENCE.md                       # human-readable verdict: deterministic + external-eval separately graded
├── reproduce.sh                      # runs both by default; flags: --deterministic | --external-eval
├── metrics_summary.json              # dashboard (deterministic numbers) + (external-eval numbers w/ run-id refs)
├── deterministic/                    # ← byte-for-byte reproducible on fresh Docker, same commit
│   ├── contract_check.log            # 37/37 green (engine.audit.contract_check --quiet)
│   ├── pytest_full_sweep.log         # 5387/0/8 (adapt/ + core/venous/ + engine/)
│   ├── manifest_idempotence.log      # stable_hash across 2 builds
│   ├── loc_budget_stats.json         # LOC per emitted file + primitive-import ratio across 20 examples
│   ├── framework_free_proof.log      # 124 registered primitives boot without FastAPI installed
│   ├── bandit_scan/                  # per-example security static scan
│   │   └── example_01.log ... example_20.log
│   ├── semgrep_scan/                 # per-example OWASP ruleset
│   │   └── example_01.log ... example_20.log
│   ├── install_docker_run.log        # Docker fresh → install.sh → scaffold → boot
│   └── freshness_proof.log           # git commit SHA + tree hash at evidence gen time
├── external-eval/                    # ← auditable, NOT byte-reproducible
│   ├── single_shot_benchmark/
│   │   ├── results.json              # 10 fresh specs × single-shot × objective grade
│   │   ├── specs/                    # the 10 blind specs (archived; not part of benchmark corpus)
│   │   ├── transcripts/              # full tool-call traces per spec
│   │   └── run_manifest.json         # model_id, prompt_bundle_hash, tool_manifest_hash, commit, stable_hash, cost
│   ├── cross_model_fnf/
│   │   ├── results.json              # 10 specs × 3 models = 30 runs; per-run verdict
│   │   ├── transcripts/              # 30 full traces
│   │   ├── variance_report.json      # cross-model variance (target ≤10% = kit-carries-weight)
│   │   └── run_manifest.json         # one per model column (Claude / GPT / Gemini)
│   ├── counterfactual/
│   │   ├── results.json              # same 10 specs, same model, NO HuGR access
│   │   ├── transcripts/              # 10 baseline traces
│   │   └── run_manifest.json         # model_id, prompt (the "from-scratch" baseline prompt)
│   └── reviewer_signoffs/
│       ├── codex_v6.md               # Wave G external audit verdict
│       ├── sonnet.md                 # parallel Sonnet audit verdict
│       └── opus.md                   # independent Opus sign-off
└── not-yet-covered.md                # honest log of PRODUCT claims NOT YET evidenced
                                      # (e.g. "MCP server against Cursor / Zed" — manual verification only)
```

### §2.2 — Claim → Evidence mapping

Each PRODUCT.md claim is mapped to a specific artefact and a grading
method. Where §1-§6 of PRODUCT.md makes a claim we cannot evidence
at v1.0.0, it is listed in `/evidence/not-yet-covered.md` with the
reason + milestone that would enable evidence (NOT hidden).

**PRODUCT §1 — "library of executable knowledge, invokable by Maestro":**

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| Fresh install path works end-to-end | `install_docker_run.log` | time-to-boot + exit 0 | deterministic |
| Catalog deterministic (`stable_hash` idempotent) | `manifest_idempotence.log` | hash-match across rebuilds | deterministic |
| 37 machine-checked invariants (drift impossible) | `contract_check.log` | binary 37/37 | deterministic |
| Full test sweep green | `pytest_full_sweep.log` | pass/fail ratio + count | deterministic |

**PRODUCT §2 — "three-layer Rails architecture" + "code as SEED not CAGE":**

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| Tools emit ≤20 LOC glue; logic in primitives | `loc_budget_stats.json` | histogram; 95th percentile ≤ §A1 budget | deterministic |
| Primitives are framework-free motors | `framework_free_proof.log` | 124/124 boot without FastAPI | deterministic |

**PRODUCT §3 — "primary user is Maestro":**

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| Maestro discovers skill via MCP metadata (~100 tokens) | `single_shot_benchmark/run_manifest.json` | prompt-bundle token count | external-eval |
| Maestro loads SKILL.md (~5k tokens) | `single_shot_benchmark/run_manifest.json` | file token count | external-eval |
| Maestro composes primitives when tools don't fit | `single_shot_benchmark/transcripts/` | presence of `fastapi_meta_compose` call | external-eval |

**PRODUCT §4 — "Maestro produces running, tested, production-grade backend single-session":**

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| Single-shot success rate on unseen specs | `single_shot_benchmark/results.json` | X / 10 with boot + tests + security scan | external-eval |
| ≥70% benchmark target for "SOTA" | `single_shot_benchmark/results.json` + `cross_model_fnf/variance_report.json` | overall ≥70% per PRODUCT §4 | external-eval |
| No human-authored code in emitted project | `single_shot_benchmark/transcripts/` | zero manual edits in trace | external-eval |

**PRODUCT §5 — non-goals (validated by absence):**

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| Generated code is idiomatic + boring (hand-editable) | `external-eval/reviewer_signoffs/*.md` | 2-of-3 reviewers call the emitted code idiomatic | external-eval |

**PRODUCT §6 — design invariants:**

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| Tools emit ≤20 LOC glue (§6.1) | `loc_budget_stats.json` | 95th percentile ≤ budget | deterministic |
| Primitives are orthogonal (§6.2) | covered via `framework_free_proof.log` + per-primitive unit tests in `pytest_full_sweep.log` | unit tests per primitive pass | deterministic |
| Generated code survives hand-editing (§6.3) | tracked in `/evidence/not-yet-covered.md` — requires a soak-edit harness that does not yet exist | N/A at v1.0.0 | not-yet-covered |
| Every tool has MCP metadata (§6.5) | subset of `contract_check.log` (§B1.5 rule) | 37/37 implies present | deterministic |
| Semantic registry indexes every primitive (§6.6) | `contract_check.log` §B1.1 rule | 37/37 implies present | deterministic |

**Post-launch + security scans** (beyond §1-§6 but material for "production-grade"):

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| Emitted code passes bandit + semgrep (OWASP ruleset) | `bandit_scan/*` + `semgrep_scan/*` | 0 HIGH / 0 CRITICAL across 20 examples | deterministic |
| Kit is model-agnostic (same result across frontier LLMs) | `cross_model_fnf/results.json` + `variance_report.json` | cross-model variance ≤ 10% | external-eval |
| External reviewer concurrence | `external-eval/reviewer_signoffs/*.md` | 2-of-3 YES on sign-off question | external-eval |

### §2.3 — What is NOT yet covered

`/evidence/not-yet-covered.md` lists every PRODUCT claim that lacks
an evidence artefact at v1.0.0, with an honest reason + milestone.
At v1.0.0 it covers at minimum:

- **"MCP server locally against Claude Desktop / Cursor / Zed"**
  (PRODUCT §3 secondary). Manual verification only; automated IDE-
  invocation harness is a v1.1+ item.
- **"Generated code survives hand-editing" idempotency** (PRODUCT
  §6.3). The `_r_generator_*` rules assert idempotency at
  emit-time; longitudinal soak-edit coverage (apply tool, hand-
  edit, re-apply tool) is a v1.1+ item.
- **"Cheaper than hand-coded"** as an absolute claim. The
  `counterfactual/` artefact shows token + time + LOC ratio
  vs. a same-model no-HuGR baseline; "cheaper for real teams with
  real specs" is post-launch telemetry (v1.2+).

Hiding these gaps behind confident language is exactly the failure
mode Codex v6 B2 caught in the first LAUNCH.md draft. They are
listed explicitly so the evidence package is honest about what it
DOESN'T prove, not only what it does.

### §2.4 — Reproduction

`./evidence/reproduce.sh` MUST:

- For `--deterministic` subcommand: regenerate `/evidence/deterministic/**`
  byte-identical modulo timestamps (normalise timestamps, then hash —
  must match committed). Runs on a fresh Docker container in ≤1h.
  Exit non-zero if any file diverges.
- For `--external-eval` subcommand: run the live LLM evals + archive
  transcripts + write new `run_manifest.json` with fresh timestamps,
  model IDs, and cost. Results are NEW (non-replayable), but the
  archiving shape is deterministic — input prompts, model pins,
  graders. Typical runtime: ~2-3h + ~$200-500 in provider cost.
- For `--all` (default): runs both; external-eval results inform the
  verdict but do not gate reproduction of deterministic artefacts.
- For `--verify`: regenerate deterministic only + diff against
  committed; non-zero on any drift. Fast CI gate (<15min).

### §2.5 — Zero-trust verification

A reader who trusts nothing runs:

```bash
git clone https://github.com/humangr-labs/HuGR_Skills --branch v1.0.0
cd HuGR_Skills

# Fast: just confirm the kit is the kit they think it is.
./evidence/reproduce.sh --verify          # ~15min
                                          # exit 0 = deterministic artefacts match commit

# Full: regenerate deterministic from scratch.
./evidence/reproduce.sh --deterministic   # ~1h
                                          # exit 0 = byte-identical reproduction confirmed

# Optional: run the external-eval again (needs LLM API keys).
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
./evidence/reproduce.sh --external-eval   # ~2-3h, ~$200-500
                                          # produces new run_manifest.json files;
                                          # archive shape identical, results may vary

cat evidence/EVIDENCE.md                  # human-readable verdict
jq . evidence/metrics_summary.json         # machine-readable numbers
```

Deterministic claims are either reproducible or they're not — no
"trust me." External-eval claims are auditable (every run fully
archived) but acknowledge the underlying reality: LLM inference is
stochastic; "SOTA" is measured, not decreed.

---

## §3 — Phased rollout

### §3.1 — Phase A: Private alpha

- **Timing:** Immediately post-tag (day 1).
- **Audience:** 5-10 devs personally known to Gustavo. Not strangers from Twitter.
- **Distribution:** Direct invite (DM / email). No public announcement.
- **Feedback channel:** Dedicated Slack/Discord thread OR direct GitHub issues on a private fork.
- **Success instrumentation:**
  - Each alpha user runs `./evidence/reproduce.sh` on their machine AND reports any divergence.
  - Each alpha user attempts at least one novel scaffold (their own spec, not from the benchmark corpus) AND reports: time to boot, tests pass / fail, subjective quality.
  - Failure modes tracked in a shared doc.
- **Exit criteria (all three must hold):**
  - ≥3 alpha users successfully scaffolded + booted an emitted app on their own hardware.
  - Zero unresolved CRITICAL bugs (install fails / scaffold produces uncompilable code / data loss in primitive).
  - Catastrophic-bug rate trending downward (≤1 new CRITICAL per week for 2 consecutive weeks).
- **Duration:** 2-4 weeks. If exit criteria not met by week 4, do not advance — diagnose + fix.

### §3.2 — Phase B: Closed beta

- **Timing:** After Phase A exit.
- **Audience:** 25-100 devs via invite-only. Public waitlist form; issue invites in batches of 10.
- **Distribution:** Landing page at `hugr.dev` (or equivalent) with waitlist. No HN / Product Hunt post yet.
- **Feedback channel:** Public GitHub issues on `HuGR_Skills` repo, with a "beta" label.
- **Success instrumentation:**
  - GitHub issue velocity + bug severity distribution tracked weekly.
  - Install failure rate measured (opt-in phone-home from `install.sh`: OS + Python version + success/fail).
  - Benchmark FNF score re-run monthly on latest `main` to detect regression.
- **Exit criteria (all three must hold):**
  - ≥50 beta users have successfully onboarded (scaffold + first extend tool).
  - ≥10 emitted apps deployed to real production (self-reported; track via issue template).
  - Critical bug fix rate ≥2 per week over the last 4 weeks AND zero unresolved CRITICAL bugs aged >14 days.
  - Install failure rate <5% across all reported platforms.
- **Duration:** 4-8 weeks.

### §3.3 — Phase C: Public launch

- **Timing:** After Phase B exit.
- **Audience:** Unlimited.
- **Distribution:** HN Show post + Product Hunt + Twitter launch thread + blog post explaining the thesis.
- **Feedback channel:** GitHub issues + Discord/forum.
- **Prerequisites (all):**
  - Phase A + B cleared per their exit criteria.
  - FNF Test score ≥80% on fresh run at the launch HEAD.
  - `install-docker.yml` nightly green for ≥30 consecutive days.
  - Rollback protocol exercised at least once (dry-run OR real) in Phase A+B.
  - Post-launch response team on-call: Gustavo + 1 backup (even if the backup is "Claude Opus 4.X with commit access," explicitly named in POST_RELEASE.md).

### §3.4 — Launch-phase transition checklist

A dedicated checklist at `/checklists/launch_phase_transition.md` SHOULD be used before each phase transition. This LAUNCH.md owns the high-level discipline; the checklist owns the row-by-row verification.

---

## §4 — Rollback-ready ops

(Consolidates with ROADMAP §5.7, ROADMAP §5.8, and POST_RELEASE.md §2.)

### §4.1 — Yank criteria (drops v1.0.0 from distribution)

Any of the following triggers an immediate yank:

- Data loss bug in any primitive (write path emits corrupted data silently).
- Auth bypass in any emitted-project auth flow.
- Supply-chain compromise (dependency pulled from registry is malicious).
- License / legal violation (unknowingly shipped GPL code under proprietary claim, etc.).

Yank mechanics: per POST_RELEASE.md §2b. Tag is NEVER deleted (git contract); instead, marked pre-release + "DO NOT INSTALL" banner + `v1.0.1` shipped with the fix.

### §4.2 — Hotfix criteria (branches to v1.0.1 without yank)

- Bug is security-High or below AND fix lands ≤1 day.
- Issue is reproducible by ≥2 independent reporters.
- Primitive contract not violated (fix lives in adapter layer OR generator OR tool).

Hotfix mechanics: per POST_RELEASE.md §2a.

### §4.3 — Monitoring SLAs (first 72h post-tag)

- `security@humangr.com` responded to within 24h per SECURITY.md §Response SLA.
- Critical GitHub issues ack'd within 6h.
- CI on `main` green check every 4h for 72h; red on main triggers page to Gustavo.
- `install-docker` nightly green every morning for 72h; 2 consecutive fails = yank consideration.

### §4.4 — Consumer protection via `stable_hash`

Per CONTRACT §2.12 and ROADMAP §2.12: every Maestro session pins a `stable_hash` from `catalog.json`. When HuGR patches / yanks, the hash changes. Consumer-side protocol MUST abort on hash-change and re-seat against the new version. This is the automatic version-safety rail; it works even if the user never reads the CHANGELOG.

---

## §5 — Success metrics (what "didn't pass vergonha" actually measures)

Track through Phase C first 3 months:

| Metric | Target | Unacceptable |
|---|---|---|
| First-week install failure rate | <5% | >10% |
| Time from `install.sh` to first emitted scaffold booting | <10 min median | >30 min |
| FNF Test score on fresh run | ≥80% | <60% |
| Critical CVEs reported | 0 | ≥1 |
| Emitted apps reaching real production (self-reported) | ≥10 in first 3 months | 0 |
| First-shot scaffold success rate in public telemetry | ≥80% | <60% |
| Maestro token cost to ship first feature (auth + 1 CRUD) | <50k tokens | >200k tokens |
| External-reviewer verdict on `/evidence/` | ≥2 of 3 YES | <2 of 3 YES |

Each metric is a public number shipped in the quarterly `STATUS.md` update.

---

## §6 — This doc's own governance

- LAUNCH.md binds at the v1.0.0 tag cut.
- Amendments follow ROADMAP §8.5 process (ratification block + Gustavo signature).
- The phased-rollout phase names (A / B / C) + exit criteria are the public commitment; changing them after launch requires a CHANGELOG entry.

---

*Generated 2026-04-24 as part of Wave G sign-off triangulation. Source: session_handoff memory + ROADMAP.md §5 + POST_RELEASE.md §2.*
