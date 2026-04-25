# Codex Audit v7 — Wave H (`/evidence/` package)

You are auditing Wave H adversarially. Your job is to FIND WHAT IS MISSING OR WRONG, not to validate. Zero deference to the author.

## Product context (calibration)

- **Repo:** `humangr-labs/HuGR_Skills` (private). Path: `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills`.
- **Product model:** SKILL-001-fastapi-production = ONE skill in a Maestro (LLM orchestrator) catalog. Maestro is model-agnostic (Claude / GPT / Gemini / Qwen). Skill's purpose: produce running, tested, production-grade FastAPI backends from short specs, single-session.
- **Canonical claims:** `PRODUCT.md` §1-§6. Launch protocol: `LAUNCH.md`. Evidence spec: `LAUNCH.md §2`.
- **Current state:** v1.0.0-rc.1, HEAD=`3f98703`, 37/37 contract green, 5387/0/8 pytest.

## Skill surface (for calibrating "enough evidence")

```
201  tools in catalog.json
124  registered primitives (core/venous/<ns>/<Name>/)
176  staged primitives (PascalCase-filtered)
 17  FastAPI adapters (production-wired)
127  adapt tools (100 extend + 27 other)
 56  generators
 28  modules/ feature packages
 20  examples (5 baseline / 10 mid / 5 adversarial)
 20  benchmark specs (plan_level 100.00, code_level 100.00)
124  formal specs
 37  machine-checked contract rules (§B0–§B4)
5387 unit tests
```

## What Wave H built

`/evidence/` — 74 files, 2 commits (`ccaba80` + `3f98703`).

### Deterministic artefacts (byte-reproducible)
- `contract_check.log` → 37/37 ALL GREEN
- `pytest_full_sweep.log` → 5387 passed / 0 failed / 8 skipped (27min)
- `manifest_idempotence.log` → stable_hash=`00cefc4cc477` matches across 2 builds
- `framework_free_proof.log` → 124 registered primitives, 0 web-framework imports
- `loc_budget_stats.json` → p95 = 13.33 LOC/handler across 20 examples
- `bandit_scan/` (20 per-example logs + SUMMARY.json) → 0 High, 0 Medium
- `semgrep_scan/` (20 per-example + SUMMARY.json) → 0 ERROR (p/python + security-audit + owasp-top-ten)
- `install_docker_run.log` → SKIPPED-LOCALLY (docker daemon off); CI-canonical (install-docker.yml nightly)
- `freshness_proof.log`

### External-eval (harness authored, paid runs deferred to 48h pre-tag)
- `single_shot_benchmark/_harness/` (prompt.md + grade.py + run.py skeleton) + `specs/README.md` (10 stubs, bodies pending Gustavo sign-off)
- `cross_model_fnf/_harness/variance.py` + README
- `counterfactual/_harness/baseline_prompt.md` + README
- `reviewer_signoffs/` (codex_v6.md + sonnet.md + opus.md — SUMMARIES of Wave-G verdicts; raw transcripts NOT persisted)

### Orchestration
- `reproduce.sh` (4 subcommands: `--verify` ≤15min, `--deterministic` ≤1h, `--external-eval` ~$200-500, `--all`)
- `EVIDENCE.md` top-level verdict
- `metrics_summary.json` dashboard
- `not-yet-covered.md` (6 gaps listed: MCP/Cursor/Zed, hand-edit soak, cheaper-absolute, cross-framework SOTA, pentest-beyond-static, bus-factor)
- `_harness/` (6 scripts)

## The adversarial questions

Answer **in strict order**, **cite specific files with line numbers**, **zero hand-waving**.

### Q1 — Coverage gaps (BLOCKER class)

Given the skill surface table above, list every **material** PRODUCT.md or LAUNCH.md claim that `/evidence/` does NOT prove or only weakly proves. For each gap state:

- Claim (file + §)
- Why current evidence is insufficient
- What artefact WOULD prove it (file name + probe approach)
- Rough cost (lines of harness code + compute)

**Explicit prompts:**
- 127 adapt tools: is the per-tool evidence equal to the aggregate pytest count (5387/0/8) or is there a per-tool manifest check?
- 124 primitives: is framework-free the only per-primitive check, or is per-primitive unit coverage individually attested?
- 17 FastAPI adapters: is adapter-wiring correctness evidenced beyond the aggregate?
- 56 generators: is per-generator idempotence evidenced?
- 28 modules: is per-module integration evidenced?
- 20 examples: is per-example **boot + pytest** evidenced, or only per-example bandit/semgrep?
- 20 benchmark specs: are per-spec plan+code scores in `/evidence/`?
- E2E SQLite (12), behavior (12), cross-composition (200+), property (984 assertions), boot test (100), stress test (27), soak test, mutation: which of these have dedicated `/evidence/` artefacts vs which are only reflected in the aggregate pytest log?

### Q2 — Methodology defects (HIGH class)

Examine `/_harness/` scripts + `EVIDENCE.md` claim→artefact mappings + reviewer_signoffs/. Find:

1. Probes that measure the WRONG thing
   - e.g., `loc_budget_probe.py` measures `/examples/` which are **pedagogical self-contained**, not fresh-emit from generators. Is this honest framing or misleading branding?
   - `framework_free_probe.py` checks 12 framework prefixes — does it catch INDIRECT imports (e.g., a primitive using `pydantic` which pulls `starlette`)?
2. Probes too permissive (false-negative prone)
3. Grading that begs the question
   - e.g., `grade.py` `_ac_coverage` does grep-based matching on first 4 content words — can a Maestro game this by including spec text verbatim in test docstrings?
4. `reviewer_signoffs/` are SELF-SUMMARIES by the Wave-H author (who is also one of the reviewers — Opus), not independent archives of raw transcripts. Is this acceptable for 2-of-3 sign-off or a methodology defect?
5. `install_docker_run.log` is SKIPPED-LOCALLY — does the CI workflow actually run what the log CLAIMS it runs (check `.github/workflows/install-docker.yml`)?
6. Any other methodology defect you spot.

### Q3 — Sign-off verdict

Given Q1 + Q2, answer:

> "Would you sign off on `/evidence/` as sufficient proof for the v1.0.0 tag cut today?"

- **Yes / No**
- **Top 3 conditions** if conditional
- **Hard blockers** if No

## Rules of engagement

- Cite specific files + line numbers for every defect
- Do NOT say "consider adding X" — say "X IS MISSING because [reason]"
- If uncertain about a claim, say "unclear from [file]; verify via [command]"
- Think hard. This is a v1.0.0 tag-cut readiness audit.
- Severity taxonomy: **BLOCKER / HIGH / MEDIUM / LOW / NIT**
- Target output: ≤2500 words, structured by Q1/Q2/Q3.

Good hunting.
