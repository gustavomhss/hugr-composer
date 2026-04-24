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

- [ ] `/evidence/` directory exists at HEAD being tagged.
- [ ] Every claim in PRODUCT.md §1-§3 maps to an artefact under `/evidence/artifacts/`.
- [ ] `/evidence/reproduce.sh` runs clean on a fresh Docker container and regenerates all artefacts with identical hashes.

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

### §2.1 — Structure

```
evidence/
├── EVIDENCE.md                       # human-readable index + verdict
├── reproduce.sh                      # single-command regeneration
├── metrics_summary.json              # dashboard of all numbers
└── artifacts/
    ├── contract_check.log            # 37/37 green (engine.audit.contract_check --quiet)
    ├── pytest_full_sweep.log         # 5387/0/8 (adapt/ + core/venous/ + engine/)
    ├── manifest_idempotence.log      # stable_hash across 2 builds
    ├── loc_budget_stats.json         # LOC per emitted file + primitive-import ratio
    ├── framework_free_proof.log      # primitives tested without FastAPI installed
    ├── bandit_scan/                  # per-example security static scan
    │   └── example_01.log ... example_20.log
    ├── semgrep_scan/                 # per-example OWASP ruleset
    │   └── example_01.log ... example_20.log
    ├── single_shot_benchmark.json    # 10 fresh specs × single-shot × objective grade
    ├── cross_model_fnf.json          # FNF Test: Claude vs GPT vs Gemini, same specs
    ├── counterfactual.json           # same spec WITHOUT HuGR — baseline comparison
    ├── install_docker_run.log        # Docker fresh → install.sh → scaffold → boot
    ├── freshness_proof.log           # git commit SHA + tree hash at evidence gen time
    └── reviewer_signoffs/
        ├── codex_v6.md               # Wave G external audit verdict
        ├── sonnet.md                 # parallel Sonnet audit verdict
        └── opus.md                   # independent Opus sign-off
```

### §2.2 — Claim → Evidence mapping (PRODUCT.md → `/evidence/artifacts/`)

| Claim | Artefact | Grading |
|---|---|---|
| "Contract discipline — 37 machine-checkable rules" | `contract_check.log` | binary pass/fail |
| "5000+ tests, all green" | `pytest_full_sweep.log` | count + pass ratio |
| "Catalog deterministic — `stable_hash` idempotent" | `manifest_idempotence.log` | hash-match |
| "Code as SEED, not CAGE — ≤N LOC glue per emitted file" | `loc_budget_stats.json` | histogram + 95th percentile |
| "Framework-free motors — primitives work standalone" | `framework_free_proof.log` | all 124 pass without FastAPI |
| "Production-grade security" | `bandit_scan/*` + `semgrep_scan/*` | 0 HIGH / 0 CRITICAL across 20 examples |
| "Single-shot success on unseen specs" | `single_shot_benchmark.json` | X / 10 |
| "Maestro-agnostic across frontier models" | `cross_model_fnf.json` | N / 30 (10 specs × 3 models); variance ≤ 10% |
| "Cheaper than hand-coded" | `counterfactual.json` | token count + time + LOC ratio |
| "Fresh install path works" | `install_docker_run.log` | time-to-boot + exit code 0 |
| "Independent external review" | `reviewer_signoffs/*.md` | 3 verdicts, majority YES |

### §2.3 — Reproduction

`./evidence/reproduce.sh` MUST:

- Run on a fresh Docker container (no local assumption) in under 3 hours.
- Regenerate every file under `/evidence/artifacts/` with the same content modulo timestamp + cost metadata.
- Exit non-zero if any artefact diverges from the committed version (detects silent drift in the kit that wasn't caught by §1.1-§1.2 gates).

### §2.4 — Zero-trust verification

A reader who trusts nothing:

```bash
git clone https://github.com/humangr-labs/HuGR_Skills --branch v1.0.0
cd HuGR_Skills
./evidence/reproduce.sh          # ~2-3h
cat evidence/EVIDENCE.md          # human-readable verdict
jq . evidence/metrics_summary.json  # machine-readable numbers
```

Every claim is either reproducible or it's not. There is no "trust me."

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
