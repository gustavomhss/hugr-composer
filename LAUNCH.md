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

**PRODUCT §1 — "library of executable knowledge, invokable by agent":**

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

**PRODUCT §3 — "primary user is agent":**

| Claim | Artefact | Grading | Class |
|---|---|---|---|
| agent discovers skill via MCP metadata (~100 tokens) | `single_shot_benchmark/run_manifest.json` | prompt-bundle token count | external-eval |
| agent loads SKILL.md (~5k tokens) | `single_shot_benchmark/run_manifest.json` | file token count | external-eval |
| agent composes primitives when tools don't fit | `single_shot_benchmark/transcripts/` | presence of `fastapi_meta_compose` call | external-eval |

**PRODUCT §4 — "agent produces running, tested, production-grade backend single-session":**

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
git clone https://github.com/humangr-labs/HuGR-Arsenal --branch v1.0.0
cd HuGR_Arsenal

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
- **Distribution:** Direct invite (DM / email), one-per-user invite
  token (HuGR-issued UUID) used to tie every alpha report back to a
  specific onboarding session — no anonymous reporting.
- **Feedback channel:** Dedicated Slack/Discord thread + required
  `alpha_report.md` template per invite token (closed-loop: no
  report = not counted toward exit criteria).
- **Platform matrix (required coverage before exit):**
  - ≥2 OS families (at least one of: macOS Intel, macOS Apple Silicon;
    AND at least one of: Linux x86_64, Linux ARM, Windows + WSL).
  - ≥2 Python minor versions among the supported set
    (3.12, 3.13).
- **Success instrumentation (closed-loop, not telemetry-opt-in):**
  - Each alpha user runs `./evidence/reproduce.sh --verify` on their
    machine AND reports PASS/FAIL + any divergence.
  - Each alpha user attempts at least one novel scaffold (their own
    spec, not from the benchmark corpus) AND fills
    `alpha_report.md`: install time, time-to-boot, tests pass/fail,
    a 1-sentence subjective quality note, any bug with a
    minimal-repro.
  - Failure modes tracked in `/docs/alpha/failure_modes.md` (shared
    doc; one row per incident).
- **Exit criteria (all four must hold):**
  - **≥5 alpha users** completed successful end-to-end runs
    (scaffold → boot → emitted pytest green on their own hardware).
  - Platform matrix above covered: ≥2 OS families AND ≥2 Python
    minors represented in the ≥5 successful runs.
  - Zero unresolved CRITICAL bugs per POST_RELEASE.md §3 severity
    ladder (auth-bypass / SQL injection / shell injection /
    secrets leak / scaffold-emits-uncompilable-code / data-loss
    in primitive / unbootable release).
  - Median CRITICAL MTTR <7 days over the alpha window; zero
    CRITICAL aged >14 days at exit.
- **Duration:** 2-4 weeks. If exit criteria not met by week 4, do
  not advance — diagnose + fix.

### §3.2 — Phase B: Closed beta

- **Timing:** After Phase A exit.
- **Audience:** 25-100 devs via invite-only. Public waitlist form;
  issue invites in batches of 10.
- **Distribution:** Landing page at `hugr.dev` (or equivalent) with
  waitlist. Invite token per user (same system as alpha); every
  download of `install.sh` carries a run-ID that the installer
  echoes in its final line. No HN / Product Hunt post yet.
- **Feedback channel:** Public GitHub issues on `HuGR_Arsenal` repo
  with a `beta` label + invite-token field in issue template
  (closed-loop: token links the report to the download cohort,
  denominator for "success rate" is the cohort size, not the
  reporter count).
- **Success instrumentation:**
  - GitHub issue velocity + bug severity distribution tracked
    weekly (MTTR + backlog per severity).
  - Install completion rate = `(install.sh exit-0 reports) /
    (invites issued)` — binding only when the run-ID instrumentation
    is shipped (it is a Wave-2 delivery; if not shipped by Phase B
    open, this metric is CONTEXT-only, not gating).
  - Onboarding completion rate = `(users who ran ≥1 extend tool
    successfully) / (invites issued)` — same closed-loop
    denominator as install completion.
  - Benchmark FNF score re-run monthly on latest `main` to detect
    regression.
- **Exit criteria (all four must hold):**
  - **≥50 beta invites activated** with successful onboarding
    (scaffold + ≥1 extend tool completed per closed-loop report).
  - **Median CRITICAL MTTR <7 days** over the last 4 weeks AND zero
    unresolved CRITICAL aged >14 days.
  - **Critical-incidence rate:** <1 new CRITICAL per 100 activated
    invites over last 4 weeks (this is the CORRECT direction of
    optimization; the earlier "bug fix rate ≥2/week" gate was
    backwards and rewarded churn).
  - **Install completion rate ≥90%** across reported platforms
    (BINDING only if run-ID instrumentation shipped; otherwise
    CONTEXT; see §5 gating-versus-context distinction).
- **Duration:** 4-8 weeks.

### §3.3 — Phase C: Public launch

- **Timing:** After Phase B exit.
- **Audience:** Unlimited.
- **Distribution:** HN Show post + Product Hunt + Twitter launch
  thread + blog post explaining the thesis.
- **Feedback channel:** GitHub issues + Discord/forum.
- **Prerequisites (all):**
  - Phase A + B cleared per their exit criteria.
  - FNF Test score ≥80% on fresh run at the launch HEAD.
  - `install-docker.yml` nightly green for ≥30 consecutive days.
  - Rollback protocol exercised at least once (dry-run OR real)
    in Phase A+B.
  - **Named-human on-call coverage.** Gustavo + 1 real human backup
    with: commit access, release secrets, paging responsibility,
    authority to yank. An LLM is NOT an acceptable backup on-call.
    Until a second human is named + briefed, Phase C cannot open;
    for Phase A (tight, private, trusted cohort) solo on-call is
    acceptable with the explicit acknowledgement in
    `POST_RELEASE.md` that bus-factor-1 is the stated risk.

### §3.4 — Launch-phase transition checklist

A dedicated checklist at `/checklists/launch_phase_transition.md`
SHOULD be used before each phase transition. This LAUNCH.md owns
the high-level discipline; the checklist owns the row-by-row
verification.

---

## §4 — Rollback-ready ops

Severity taxonomy + yank/hotfix mechanics live in `POST_RELEASE.md`
(§2 mechanics + §3 severity ladder). LAUNCH.md does NOT maintain a
parallel severity list — Codex v6 LAUNCH review (B4) correctly
flagged that two overlapping incident taxonomies leave ops staff
arguing at 3am whether a specific bug is a yank or a hotfix.

### §4.1 — Severity + response class (canonical: POST_RELEASE §3)

| Severity (POST_RELEASE §3) | Response class | Owner |
|---|---|---|
| **Critical** — auth bypass, SQL injection, shell injection, secrets leak, scaffold emits uncompilable code, data loss in primitive write path, unbootable release, supply-chain compromise, license / legal violation | YANK if no same-day fix (POST_RELEASE §2b); else HOTFIX same business day (POST_RELEASE §2a) | Gustavo (final call); on-call may cut hotfix + defer yank decision |
| **High** — known-bad crypto defaults in emitted code, incorrect auth config, perf regression >50% in emitted scaffold boot | HOTFIX ≤1 business day | Gustavo |
| **Medium** — generator bug affecting edge-case prompts, doc drift after a counts change | Next MINOR | Claude + Gustavo review |
| **Low** — cosmetic, typo, example polish | Any MINOR | Claude |

Yank mechanics (when Critical + no same-day fix): POST_RELEASE §2b.
Hotfix mechanics: POST_RELEASE §2a. Emergency revert: POST_RELEASE
§2c. LAUNCH.md does not duplicate those procedures — it points at
them, so a single edit in POST_RELEASE.md updates the launch
rollback contract too.

### §4.2 — When LAUNCH.md adds to POST_RELEASE (and only then)

This doc narrows POST_RELEASE in two places only, BOTH are about
the first 72h post-tag launch window specifically:

- **Paging escalation** — see §4.3 below. POST_RELEASE.md §3
  currently names Gustavo as final call + "on-call engineer in
  emergencies"; §4.3 below locks that down to a named human
  before Phase C opens (pre-Wave-F POST_RELEASE.md had on-call
  coverage TBD; keeping it TBD through public launch is
  unacceptable).
- **Automatic yank-consideration trigger** — two consecutive
  `install-docker.yml` nightly failures post-tag = yank-consideration
  (per §4.3). POST_RELEASE.md §1 monitoring table tracks this as a
  watch line, but does not auto-escalate; LAUNCH.md raises it to
  a trigger during the post-tag window.

### §4.3 — Monitoring SLAs (first 72h post-tag)

- `security@humangr.com` responded to within 24h per SECURITY.md §Response SLA.
- Critical GitHub issues ack'd within 6h.
- CI on `main` green check every 4h for 72h; red on main triggers page to Gustavo.
- `install-docker` nightly green every morning for 72h; 2 consecutive fails = yank consideration.

### §4.4 — Consumer protection via `stable_hash`

Per CONTRACT §2.12 and ROADMAP §2.12: every agent session pins a `stable_hash` from `catalog.json`. When HuGR patches / yanks, the hash changes. Consumer-side protocol MUST abort on hash-change and re-seat against the new version. This is the automatic version-safety rail; it works even if the user never reads the CHANGELOG.

---

## §5 — Success metrics

Codex v6 LAUNCH review (M1) flagged the first draft's metric list
as vanity/silence-sensitive — metrics like "0 critical CVEs
reported" improve when users fail to report, "≥10 emitted apps in
prod (self-reported)" is fabricable, "reviewer-majority YES" begs
the question of who chooses the reviewers. A zero-risk launch
needs falsifiable operational numbers for GATING and acknowledges
the vanity-adjacent ones as CONTEXT.

### §5.1 — Gating metrics (binding; phase transitions blocked if any is unacceptable)

Closed-loop: every metric below has a denominator tied to a
HuGR-issued invite token (Phase A) or run-ID (Phase B+). Opt-in
telemetry is NOT the denominator.

| Metric | Target | Unacceptable (blocks transition) | Window |
|---|---|---|---|
| Alpha platform-matrix coverage | ≥2 OS families × ≥2 Python minors | <2 on either axis | Phase A exit |
| Alpha successful end-to-end runs | ≥5 | <5 | Phase A exit |
| Median CRITICAL MTTR | <7 days | >14 days | rolling 4 weeks |
| Unresolved CRITICAL aged >14 days | 0 | ≥1 | any point |
| Critical incidence rate | <1 per 100 activated invites | ≥3 per 100 | rolling 4 weeks, Phase B+ |
| FNF Test score on fresh HEAD | ≥80% | <60% | Phase C prereq; quarterly re-run |
| `install-docker.yml` nightly streak pre-Phase-C | ≥30 consecutive days green | <14 days | Phase C prereq |
| Named-human on-call (not LLM) for Phase C | Gustavo + 1 named human | any other shape | Phase C prereq |
| External reviewer independent sign-off | 2-of-3 YES on the canonical sign-off prompt | <2-of-3 | pre-tag only (Wave G already satisfied this) |

### §5.2 — Context metrics (tracked, reported, NOT gating)

These numbers are published quarterly in `STATUS.md` for
transparency. They are NOT gates — every one has a known
gameability vector or a silence-sensitive denominator. They inform
strategy, do not block rollout.

| Metric | Note |
|---|---|
| Install-completion rate (telemetry-derived) | Binding only when the run-ID phone-home instrumentation ships in Wave 2. Until then: CONTEXT. Opt-in denominator; use with caution. |
| First-shot scaffold success rate (telemetry) | Same caveat as install-completion. BINDING only post-Wave-2 telemetry. |
| Median time-to-first-emitted-scaffold-boot | CONTEXT. Self-selected population, different hardware/network. |
| agent token cost for "auth + 1 CRUD" feature | CONTEXT. Provider prices + model choice dominate; useful as a delta vs counterfactual baseline, not as absolute. |
| Emitted apps reaching real production (self-reported) | CONTEXT. Self-report is un-falsifiable; track to see trend, do not gate. |
| Critical CVEs reported | CONTEXT. Silence-sensitive — low count may mean "no bugs" or "no one reported." Pair with pentest rate + SECURITY.md disclosure activity. |
| GitHub stars / forks / external contributors | CONTEXT. Vanity unless coupled to signed commits + reviewed PRs. |

### §5.3 — Why this split

The gating column only contains metrics that FALSIFY something
concrete: a user who did or didn't complete onboarding via a
closed-loop token, an MTTR measured from issue-created to
issue-closed on labeled incidents, a benchmark score re-run from
the same specs. Each is auditable from git log + GitHub issue
history + benchmark output. Each can prove itself wrong; a bad
denominator cannot hide the problem.

Context metrics are where vanity lives. They matter for strategy
(are we growing? are users self-reporting success?) but NONE of
them can be treated as proof of shipping safely. Codex v6 M1 was
right: if the launch protocol gates on numbers that improve when
users fail to report, the protocol is a ceremony, not a safety net.

---

## §6 — This doc's own governance

- LAUNCH.md binds at the v1.0.0 tag cut.
- Amendments follow ROADMAP §8.5 process (ratification block + Gustavo signature).
- The phased-rollout phase names (A / B / C) + exit criteria are the public commitment; changing them after launch requires a CHANGELOG entry.

---

*Generated 2026-04-24 as part of Wave G sign-off triangulation. Source: session_handoff memory + ROADMAP.md §5 + POST_RELEASE.md §2.*
