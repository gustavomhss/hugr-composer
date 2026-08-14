# 0005 — Contract violations B0.5 + B3.4 (audit 45/47)

> **Status:** Ratified 2026-08-13 by Gustavo.
> **Author:** Claude (2026-08-13).
> **Scope:** Documents the two pre-existing contract violations surfaced by
> `engine.audit.contract_check` (45/47 green) and the attack order chosen to
> retire them. Neither violation is related to the T0/T1 gate work merged as
> PR #47 — both predate it and were left untouched there.
>
> **Machine check:** `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check --quiet`
> → `45/47 contract items satisfied — 2 VIOLATIONS`.

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

Not fixed here: creating it requires infra decisions with cost/security
surface (secrets, scheduled spend on the Anthropic API, score publication
policy). Logged as a follow-up.

## 2. Attack order

| # | Rule | Reason chosen |
|---|------|---------------|
| 1 | B0.5 | Pure content. Zero infra/secret/cost surface. Single-file rewrite + local audit rerun. |
| 2 | B3.4 | Infra + secret + cost. Needs an operator decision on dispatch cadence and score floor publication. |

## 3. Acceptance

- B0.5: `contract_check` reports B0.5 green (46/47) after README rewrite.
- B3.4: tracked as open item in `STATUS.md`; blocked on operator decision
  documented in §1.2.
