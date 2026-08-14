# 0005 — Contract violations B0.5 + B3.4 (audit 45/47 → 47/47)

> **Status:** Ratified 2026-08-13 by Gustavo. Both violations retired same
> day (B0.5 via README rewrite, B3.4 via `benchmark-45d.yml` → rename —
> see §4).
> **Author:** Claude (2026-08-13).
> **Scope:** Documents the two pre-existing contract violations surfaced by
> `engine.audit.contract_check` (45/47 green) and the attack order chosen to
> retire them. Neither violation is related to the T0/T1 gate work merged as
> PR #47 — both predate it and were left untouched there.
>
> **Machine check:** `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check --quiet`
> → `47/47 contract items satisfied` (was 45/47).

---

## 1. Violations (as of 2026-08-13, `d059a1c9`)

| Rule | Verdict | Location |
|------|---------|----------|
| B0.5 | ✗ `README.md exceeds 100-line hard budget (237 lines)` | `engine/audit/contract_rules/phase0_identity.py:73` |
| B3.4 | ✗ `missing: .github/workflows/benchmark-nightly.yml` | `engine/audit/contract_rules/phase3_benchmarks.py:80` |

### 1.1 B0.5 — README.md ≤100 lines + links + counts-sync

CONTRACT §B0.5 hard budget: README.md ≤100 lines, must link
`PRODUCT.md`/`ROADMAP.md`/`CONTRACT.md`, must reference `install.sh`, and
must carry surface-count tokens that reconcile against `INVENTORY.md`
(machine-parsed, whitespace-tolerant regexes).

Root cause: the repo-root README grew organically (it doubles as the
entry doc for the embedded `gateway/` package) and drifted to 237 lines.
The 80→100 limit was itself raised in Wave-F M3 to buy headroom; the
README outgrew even that.

Fix committed in this ADR: README rewritten to ~75 lines, preserving the
gateway quick-start and the mandatory count tokens
(`Primitives: 124`, `Staged: 174` + `+41 quarantined`,
`# 61 macro scaffold helpers`, `# 135 tools`, `# 124 primitives + 18
FastAPI adapters`, links, `install.sh`).

### 1.2 B3.4 — nightly benchmark CI workflow

CONTRACT §B3.4 requires `.github/workflows/benchmark-nightly.yml` declaring
a scheduled (`schedule:`/`cron:`) job that dispatches `engine.bench`,
needs `ANTHROPIC_API_KEY`, and uploads `latest_score.json`.

Root cause: the file was never created under the contract name. Existing
`.github/workflows/benchmark-45d.yml` and `blind-bench-stub.yml` cover
adjacent needs but do not match the rule's name + required tokens.

Resolution (2026-08-13): `benchmark-45d.yml` renamed to
`benchmark-nightly.yml`. The workflow already carried every token the rule
requires (`schedule:`/`cron:`, `engine.bench` invocations,
`ANTHROPIC_API_KEY` for the claude-adapter dispatch, `latest_score.json`
publish) plus the existing cost controls: 45-day staleness gate on the
scheduled run and a policy that only a manual claude-adapter run commits a
score to main (stub runs upload an artifact but never publish). Also fixed
the stale `skills/SKILL-001-fastapi-production/` working-directory + artifact
path — the repo is flat (no `skills/` tree), so the previous file could not
run here. The claude-adapter path still requires the operator to define the
`ANTHROPIC_API_KEY` repository secret before a manual run spends on the API;
until then only the stub path fires on schedule (cost ≈ 0).

## 2. Attack order

| # | Rule | Reason chosen |
|---|------|---------------|
| 1 | B0.5 | Pure content. Zero infra/secret/cost surface. Single-file rewrite + local audit rerun. |
| 2 | B3.4 | Infra + secret + cost. Retired by renaming the existing benchmark workflow (name was the only missing token) rather than building a new one — preserves the 45-day staleness gate + stub-only scheduled cost. |

## 3. Acceptance

- B0.5: `contract_check` reports B0.5 green after README rewrite.
- B3.4: `contract_check` reports B3.4 green after workflow rename + flat-layout path fix.
- Final: `47/47 contract items satisfied` (was 45/47).
