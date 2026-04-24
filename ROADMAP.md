# ROADMAP — HuGR SkillKit

> **Status:** PROPOSED (awaits ratification — see §11).
> **Post-ratification, this document is read-only.** Amendments require a
> new dated ratification line at the bottom of §11.
>
> **Purpose:** single source of truth for what HuGR is, how we measure
> "done", and where we're going. Consolidates the pre-freeze scattered
> knowledge (`PRODUCT.md` contract, old `/ROADMAP.md` phases,
> `/GOLIVE.md` ops checklist, `/FREEZE.md §2` deferrals, per-primitive
> invariants, session-handoff memory).
>
> **Companion docs (kept, still authoritative in their scope):**
> - `PRODUCT.md` — what HuGR promises
> - `CONTRACT.md` — machine-checked rules (§A inviolable + §B gates)
> - `FREEZE.md` — v1.0 scope lock + ratification
> - `GOLIVE.md` — operational commands for the cut
> - `POST_RELEASE.md` — 72h runbook
> - `MIGRATION.md` — v0.x → v1.0 breaking changes
> - `SECURITY.md` — disclosure + SLA
> - `INVENTORY.md` (skill-scoped) — machine-generated counts
>
> **This doc:** strategy + invariants + DoDs + checklists. Load FIRST.

---

## Part 0 — How to read this doc

### §0.1 — Role-based read-order

| If you are… | Read |
|---|---|
| First-time contributor | §1 (state) → §2 (invariants) → §3 (quality) → §4 (DoDs) → Checklists §7.A or §7.D |
| Release engineer cutting v1.0 | §5 (ship gate) → `/GOLIVE.md` (commands) → Checklist §7.I → §5.8 rollback → §7.J |
| Wave-2/3/4 worker | §6 (waves) → `engine/promotion/LEDGER.md` → Checklist §7.F / §7.G / §7.H |
| Auditor / reviewer | §2 (invariants) → §4 (DoDs) → `engine.audit.contract_check` output → §8.3 drift protocol |
| Security-sensitive contributor | §3.11 → `/SECURITY.md` → §2.5 (no-PII invariants) |
| Future-us debugging drift | §1 (state) vs. INVENTORY.md + `engine.inventory` → §8.3 |
| Gustavo (ratifying) | §11 (freeze block) → §5.1 (your pre-tag items) → §8.2 risks |

### §0.2 — Doc map at a glance (single-owner rule)

| Doc | Scope |
|---|---|
| `/PRODUCT.md` | What HuGR promises (contract with users) |
| `/CONTRACT.md` | Machine-checked rules (§A + §B + §C + §D + §E) |
| `/ROADMAP.md` (this) | Strategy + invariants + DoDs + checklists |
| `/FREEZE.md` | v1.0 scope lock + ratification block |
| `/GOLIVE.md` | Operational commands for the cut |
| `/LAUNCH.md` | Zero-risk launch protocol (evidence + phased rollout + rollback) |
| `/POST_RELEASE.md` | 72h runbook + rollback protocol |
| `/MIGRATION.md` | v0.x → v1.0 breaking changes |
| `/SECURITY.md` | Disclosure + SLA ladder |
| `/CHANGELOG.md` | Per-release notes + benchmark history |
| `/INTERFACES.md` | Maestro + Forge consumer contracts |
| `/CONTRIBUTING.md` | Contributor onboarding |
| `/README.md` | ≤100-line entry with links |
| `skills/SKILL-001-fastapi-production/INVENTORY.md` | Machine-generated canonical counts |
| `skills/SKILL-001-fastapi-production/STATUS.md` | Human-readable surface counts |
| `skills/SKILL-001-fastapi-production/SKILL.md` | Skill contract (Maestro-facing) |
| `skills/SKILL-001-fastapi-production/engine/promotion/LEDGER.md` | Staged-primitive triage ledger |
| `docs/decisions/NNNN-*.md` | ADRs (architectural decisions) |

Full doc-map with cross-ref rules in §8.4.

### §0.3 — Convention: counts are machine-verified

Every count in this doc reconciles against
`skills/SKILL-001-fastapi-production/INVENTORY.md`. Regenerate
INVENTORY via `PYTHONPATH=. .venv/bin/python -m engine.inventory`.
Drift between this doc and INVENTORY = audit bug (caught by CONTRACT
§B4.7). Never hand-edit counts; always regen + commit the regen.

---

## Part 1 — Current state (machine-verified 2026-04-21)

Regenerate counts via `PYTHONPATH=. .venv/bin/python -m engine.inventory`.
Every row below is emitted by a specific command; if the doc says 124 and
the command says 125, the doc is wrong, not the command.

### §1.1 — Canonical counts

| Surface | Count | Notes |
|---|---:|---|
| MCP-registered tools on disk | 257 | Files with `MCP_TOOL` metadata |
| Tools indexed in `catalog.json` | 201 | Canonical `fastapi_<domain>_<verb>_<noun>` |
| Tier-1 meta tools | 7 | home / search / describe / scaffold / compose / audit / verify |
| Tree dispatchers | 9 | auth, data, api, realtime, resiliency, obs, compliance, deployment, testing |
| Adapt tools | 127 | 100 extend / 8 evolve / 8 operate / 6 verify / 4 contracts / 1 proactive |
| Generators | 56 | scaffolders per subsystem |
| Module packages | 28 | pre-built feature bundles |
| Registered primitives | 124 | `core/venous/<ns>/<Name>/` — framework-free, full shell |
| FastAPI adapters | 17 | Production-wired in `core/venous/_adapters/fastapi/` |
| Provider adapters | 2 | `_adapters/redis/PubSubAdapter.py` + `_adapters/stripe/BillingAdapter.py` |
| Staged primitives | 176 | `_extracted/<ns>/`, surfaced as `status="staged"` |
| Quarantined primitives | 42 | `_extracted/_quarantine/`, hidden from catalog |
| Recipes | 392 | Parsed from primitive `.md` `## Compose with:` sections |
| Benchmark specs | 20 | 5 baseline / 10 mid / 5 adversarial |
| Ledger entries | 219 | Post-Wave-1.5 triage state |
| Contract rules passing | 37/37 | Machine-verified by `engine.audit.contract_check` |
| Plan-level benchmark | 100.00 | 20/20 specs, v3 best-of-ensemble |
| Code-level benchmark | 100.00 | 20/20 specs, executable pytest rubric |
| Rails-connected extend tools | 24/100 | Floor = 22 (§B1.3 non-regression) |

### §1.2 — What's done (by phase)

- **Phase 0** — Docs honesty (PRODUCT/ROADMAP/CONTRACT/CLAUDE/SKILL). ✅
- **Phase 1** — Rails wiring: registry + recipes + auto-discovery. ✅ (floor=22 for §B1.3, §6.1 refactor long-tail deferred to Wave 2 signals)
- **Phase 2** — Discoverability (`fastapi_meta_search` + siblings). ✅
- **Phase 3** — Plan-level benchmark (100.00 / 20/20 specs). ✅
- **Phase 4** — Productisation (install.sh, 20 examples, docs site, CONTRIBUTING). ✅
- **Phase 5** — Code-level benchmark (100.00 / 20/20) + promotion pipeline. ✅
- **Wave 1** (pre-freeze) — BulkheadAdapter promotion + 2 bulkhead test failures closed. ✅
- **Wave 1.5** (pre-freeze) — PubSub + Billing motor/adapter pairs promoted; 3 NEEDS_REVIEW ledger entries cleared; scaffolder `__init__.py` preservation fix. ✅

### §1.3 — What's open

- **Ship gate** (§5 below) — Claude-side ops + Gustavo-side ratifications.
- **Wave H — evidence package** (`/evidence/`) — documented + reproducible
  artefact mapping each PRODUCT.md claim to a runnable proof. Pre-tag
  requirement per `/LAUNCH.md §1.3` + §2.
- **Property test §3.9 resolution** — RUFF_CRITICAL_CLEAN 7/8 must go
  green OR receive an explicit carve-out in CONTRACT §E.
- **CI 48h window** — E2E Postgres + behavior scenarios + soak +
  mutation + install-docker green for 48h pre-tag per §5.7 / LAUNCH §1.2.
- **Phased rollout** (`/LAUNCH.md §3`) — post-tag alpha → beta → public,
  NOT executed pre-tag.
- **Wave 2 / 3 / 4** — post-v1.0 deferrals per §6.

---

## Part 2 — Invariants (inviolable across every phase)

An invariant is a statement that MUST be true for any valid commit on
`main`. A commit that violates an invariant is rejected (machine-checked
where possible; reviewer-enforced where not).

### §2.1 — CONTRACT §A — inviolables (12 rules)

> **Mirror, not summary.** Each row below quotes the rule headline from
> `/CONTRACT.md §A` verbatim. If CONTRACT.md drifts from this table,
> CONTRACT.md wins and this table is wrong. Raise a §B4.7-class drift
> bug.

| ID | Rule (headline from CONTRACT.md §A) |
|---|---|
| §A1 | **Tools emit ≤ 20 lines of glue per capability.** Measured excluding imports + docstrings. Violating tool fails adapt contract gate. |
| §A2 | **Generated code imports from `core/venous/*`.** Every file a tool writes includes ≥1 `from core.venous.<ns> import ...`. Tools producing zero such imports are rejected. |
| §A3 | **Primitives are orthogonal.** Each does one thing; no primitive depends on mutating another at runtime. Surfaces in the T4 metamorphic gate. |
| §A4 | **Running a tool twice does not clobber user edits.** Fingerprints + `dry_run` + idempotency. Non-negotiable. |
| §A5 | **Every primitive has ≥3 composition examples in its `.md`.** `grep -L "## Compose with:" core/venous/*/*/*.md` returns empty. |
| §A6 | **Every tool has an `MCP_TOOL` metadata block.** Auto-discovery mandatory; manual MCP registration forbidden Phase 1+. |
| §A7 | **Registry is single source of truth for discoverability.** `engine/primitives_by_concern.yaml` indexes every production primitive. Missing from registry = doesn't exist. |
| §A8 | **No claim in any doc without code on disk.** Drift = audit bug to fix SAME DAY as discovery. |
| §A9 | **Benchmark is arbiter Phase 3+.** No surface merged without citing a benchmark scenario it moves red→green. |
| §A10 | **Terminology lock (PRODUCT.md §8) is sacred.** Casual renaming is a bug, not a style preference. |
| §A11 | **Opus for correctness-critical audit, not Sonnet.** Sonnet hallucinated a race condition; Opus caught 30 real bugs Sonnet missed. |
| §A12 | **`_extracted/` is a pool, not a backlog.** Promote only when benchmark gap demands. No preemptive triage. Amended: benchmark gap **OR** registered-tool import **OR** ratified triage pass (this ROADMAP + `docs/decisions/0004-tier-lite.md §3`). |

**Cross-cutting implications (derived from §A, not part of §A):**

- §A2 + §A7 → Rails-style wiring. Every new `add_*` tool declares
  `imports_primitives` in its `MCP_TOOL`, and §B1.3 counts compliance.
- §A4 → every tool has an idempotency fingerprint documented in the
  module docstring.
- §A5 + §A7 → every primitive has ≥3 `compose_with` bullets in the
  registry YAML AND ≥3 `## Compose with:` bullets in `<Name>.md`.
- §A8 → CLAUDE.md / STATUS.md / ROADMAP.md / CHANGELOG.md MUST NOT
  carry hand-maintained counts; §B4.7 machine-checks reconciliation
  against `INVENTORY.md`.
- §A10 → the vocabularies in §2.4 are LOCKED. Renames require a MAJOR
  semver bump.
- §A11 → audit agents use Opus; spec authoring / bulk refactors may
  use Sonnet.

### §2.2 — CONTRACT §B — execution checklist (45 items spec'd; 37 machine-checked today)

> **Two numbers, one source.** CONTRACT.md §B lists **45 items** as of
> v1.0.0-rc.1 (count: `grep -cE '^#### B[0-9]' CONTRACT.md`).
> `engine.audit.contract_check` wires **36 of them as machine-checked
> rules** today. The delta is accounted for:
>
> - **9 items are spec'd but deliberately not machine-checked** —
>   `§B1.4` is subsumed by `§B1.3`'s AST scan; `§B5.1..§B7.3` close
>   post-v1.0 (per FREEZE §2 deferrals); the rule count auto-
>   increments when Phase-5/6/7 rules land per §2.2.7 below.
> - **Rule text is self-describing**. Each row names the `_r_*`
>   function that enforces it, so drift between spec text and
>   machine check is traceable in one hop. Treat
>   `contract_check.py` as authoritative for CURRENT thresholds;
>   changes there require a same-commit CONTRACT.md §B update
>   (§C6 enforces).
> - **§B1.7..§B4.7 backfill landed** per commit `d78d4b2` — earlier
>   drafts of this drift-note said those 8 items "exist in
>   contract_check.py but NOT in CONTRACT.md"; that gap is closed.

#### §2.2.1 — Phase 0: Ground truth + docs honesty (8 items)

| ID | What it guards | Machine check? |
|---|---|---|
| §B0.1 | `PRODUCT.md` canonical (§1-§9, terminology lock, 3-layer arch) | ✅ |
| §B0.2 | `ROADMAP.md` honest + phased (this doc; Part 1 ground truth + Part 2 phases + risks + actions) | ✅ |
| §B0.3 | `CONTRACT.md` (§A 12 rules + §B DoD/Inv/Compl/QS per item + §C-§E) | ✅ |
| §B0.4 | `SKILL.md` v2 in Anthropic Agent Skills format | ✅ |
| §B0.5 | `README.md` at repo root (≤100 lines + links) | ✅ |
| §B0.6 | CLAUDE memory pointer | ✅ |
| §B0.7 | `/benchmark/` audited — no stub tests | ✅ |
| §B0.8 | `.gitignore` covers machine-generated artefacts | ✅ |

#### §2.2.2 — Phase 1: Rails-style wiring (10 items)

| ID | What it guards | Machine check? |
|---|---|---|
| §B1.0 | `core.venous` copy-in distribution works | ✅ |
| §B1.0.1 | Adapter layer + framework-free primitives (ADR-0003) | ✅ |
| §B1.1 | `primitives_by_concern.yaml` registry synced with disk; no half-extracted dirs | ✅ |
| §B1.2 | Every primitive `.md` has `## Compose with:` with ≥3 bullets | ✅ |
| §B1.3 | ≥15 extend `add_*` tools import a registered primitive (CONTRACT text; machine floor = 22 non-regression) | ✅ |
| §B1.4 | MCP tool responses cite composed primitives (via `primitives_used`) | ✅ (covered by §B1.3 AST scan) |
| §B1.5 | No hardcoded `@mcp_app.tool` decorators — auto-discovery only | ✅ |
| §B1.6 | No orphan generators (`generate_*` / `scaffold_*` is MCP_TOOL OR internal helper) | ✅ |
| §B1.7 | FastAPI adapter coverage (every `<Name>Adapter.py` has `test_<Name>Adapter.py` + maps to registry; floor = 15) | ✅ |
| §B1.8 | Tier-lite eligibility (stateless, framework-free, no REPLACE_ME; vacuously green at 0 lite registered) | ✅ |

#### §2.2.3 — Phase 2: Discoverability (5 items: 3 CONTRACT.md + 2 added pre-freeze)

| ID | What it guards | Machine check? |
|---|---|---|
| §B2.1 | `find_primitive` MCP tool + BM25 quality gate (top-1 ≥ 80%, P@3 ≥ 90%) | ✅ |
| §B2.2 | `suggest_composition` MCP tool + recipe quality gate (top-1 ≥ 70%, P@3 ≥ 90%) | ✅ |
| §B2.3 | Reference docs site idempotent build | ✅ |
| §B2.4 | Catalog manifest synced + deterministic (`stable_hash` idempotent across two builds) | ✅ (added pre-freeze) |
| §B2.5 | SKILL.md v2 Anthropic Agent Skills contract | ✅ (added pre-freeze) |

#### §2.2.4 — Phase 3: Benchmark (5+2 items)

| ID | What it guards | Machine check? |
|---|---|---|
| §B3.1 | 20 benchmark specs (5 baseline / 10 mid / 5 adversarial) — `# title` + `## Requirements` + `## Acceptance criteria` + `## Non-requirements` | ✅ |
| §B3.2 | Scoring rubric implemented + tested | ✅ |
| §B3.3 | Benchmark runner + stub Maestro + report JSON | ✅ |
| §B3.4 | Nightly benchmark CI workflow | ✅ |
| §B3.5 | Baseline score published; plan-level ≥ 90 on 20/20 (currently 100.00) | ✅ |
| §B3.6 | Code-level harness perfect on covered, ≥25% coverage (currently 100.00 / 20/20) | ✅ (added pre-freeze) |
| §B3.7 | Blind benchmark harness + specs + stub fixtures | ✅ (added pre-freeze) |

#### §2.2.5 — Phase 4: Productisation (5+2 items)

| ID | What it guards | Machine check? |
|---|---|---|
| §B4.1 | `install.sh` + fresh-Docker CI green | ✅ |
| §B4.2 | `/examples/` populated (≥5 with README + MAESTRO_SESSION + cross-link; currently 20) | ✅ |
| §B4.3 | Docs site v1 (top-level + per-tool pages) | ✅ |
| §B4.4 | CHANGELOG + VERSION semver cite benchmark score | ✅ |
| §B4.5 | `CONTRIBUTING.md` complete (primitive + tool + recipe + dev setup) | ✅ |
| §B4.6 | VERSION triplet sync (repo-root + skill + STATUS.md frontmatter) | ✅ (added pre-freeze) |
| §B4.7 | Canonical counts in INVENTORY reconcile against CLAUDE / STATUS / ROADMAP / CHANGELOG | ✅ (added pre-freeze) |

#### §2.2.6 — Phases 5-7: Post-v1.0 (not machine-checked until activated)

| ID | Intent | Status |
|---|---|---|
| §B5.1 | Code-level score ≥ 50% | ✅ met (100.00) |
| §B5.2 | Code-level score ≥ 70% (v1.0 ship criterion) | ✅ met (100.00) |
| §B6.1 | SKILL-002 choice by demand signal | Post-v1.0 (Phase 6) |
| §B6.2 | ≥ 30 shared primitives across skills | Post-v1.0 (Phase 6) |
| §B6.3 | Multi-skill Maestro example | Post-v1.0 (Phase 6) |
| §B7.1 | External PR lands a primitive via gate | Post-v1.0 (Phase 7) |
| §B7.2 | Public benchmark scoreboard | Post-v1.0 (Phase 7) |
| §B7.3 | SDK docs for external Maestro authors | Post-v1.0 (Phase 7) |

#### §2.2.7 — How §B items become machine rules

New §B items require, in the SAME commit:

1. DoD + Invariants + Completeness + Quality (SOTA) block in CONTRACT.md.
2. `Rule(...)` entry added to `engine/audit/contract_check.py#RULES`.
3. The rule function returns `(bool, str)` — exit-0 in CI requires `True`.
4. Count in `engine.audit.contract_check` output goes up by 1 (e.g.
   36 → 37).

§C6 CI gate enforces this: merging to `main` without the corresponding
`Rule(...)` fails CI.

### §2.3 — Pool discipline (§A12 + §A12(b))

- `_extracted/<ns>/<Name>/` — staged primitives surfaced with `status="staged"`.
- `_extracted/_quarantine/<Name>/` — primitives rejected by extraction gate.
- **Promotion trigger (§A12):** benchmark gap OR a registered tool's
  `imports_primitives` references the staged name OR a ratified triage
  pass (like Wave 1.5) explicitly approves the promotion.
- **Deletion trigger:** verdict = REDUNDANT in `engine/promotion/ledger.json`,
  executed via `engine.promotion.promote --delete <Name>`.
- **No silent upgrade.** A staged item that looks ready but has no §A12
  trigger stays staged. The ledger tracks the blocker.

### §2.4 — Namespace canonicity (vs. Domain canonicity)

**Namespace ≠ Domain.** These are two overlapping-but-distinct locked sets:

- **Namespace** = directory under `core/venous/<ns>/`. Home of registered
  primitives. 16 closed values; full list in §9.1.
- **Domain** = the `<domain>` slot in a canonical tool name
  `fastapi_<domain>_<verb>_<noun>`. 10 closed values; full list in §9.2.

A namespace may or may not appear as a domain (e.g. `billing` is a
namespace but not a domain; `auth` is both).

**Adding a new namespace** = additive schema change, allowed at MINOR
bump, must update in SAME commit:

1. `engine/primitives_by_concern.yaml` (at least one primitive entry
   exists under the new namespace, or CI rejects).
2. This doc's §9.1 namespace list.
3. `/PRODUCT.md §8` terminology lock (if the namespace name ships as
   user-facing vocab).

**Adding a new domain** (tool naming slot) = additive, must update:

1. `engine/index/schemas.py#DOMAINS` (the authoritative tuple).
2. This doc's §9.2 domain list.
3. At least one Maestro-facing tool that uses the new domain slot
   (orphan domains are rejected).

**Removing** a namespace OR domain = MAJOR semver bump (v2.0.0+).

### §2.5 — Per-primitive invariants (domain-specific)

Every registered primitive declares its invariants in its `<Name>.py`
module docstring with named IDs (`<PREFIX>_INV_NN`). Behavioural tests
name the invariant they witness in the test function name
(`test_inv_NN_*` inside `behavioral_<Name>.py`).

**Invariant acceptance test (§4.1):** every new primitive MUST ship ≥3
named invariants with ≥1 behavioural-test witness each.

**Enumerated invariant families at v1.0** (prefix → primitive):

| Prefix | Primitive | Namespace | Count | Witnesses |
|---|---|---|---:|---|
| BH_INV_* | `Bulkhead` | resiliency | 5 | capacity ceiling, wait-deadline, anti-retry ledger, partition isolation, rejection metering |
| TB_INV_* | `TopicBus` | events | 5 | at-least-once delivery, per-key exclusive dispatch, nack-never-drops, partition-local ordering, durable append before fanout |
| PS_INV_* | `PubSub` | events | 5 | fanout correctness, per-subscriber ordering, topic isolation, subscriber cleanup, active-window delivery |
| BILL_INV_* | `Billing` | billing | 5 | HMAC webhook mandatory, lifecycle monotonicity, plan-change id preservation, opaque-id checking, no-PII errors |

**Pending documentation** (registered primitives whose invariant family
prefix isn't yet enumerated in this table): the remaining 120
registered primitives carry invariants in their `<Name>.py` module
docstrings (machine-verifiable — every motor module has at least one
`INV_` block per §4.1 DoD). A tracking task lives as a process item
in §6.1 Wave 2: while promoting tier-lite candidates, backfill this
table with their INV prefixes.

**Rule:** this table MUST be updated in the SAME commit that promotes
a new primitive whose invariant family prefix is not yet listed.
Checklist §7.A step 14 enforces this at commit time.

### §2.6 — Adapter isolation

- Framework-specific code lives in `core/venous/_adapters/<framework>/`.
- Framework directories currently: `fastapi/` (17 adapters), `redis/` (1),
  `stripe/` (1). New framework dir allowed when a motor needs a new
  provider — see Checklist §7.C.
- Adapter MUST lazy-import its SDK. The motor module + adapter module
  must be importable without the SDK installed. Missing-SDK error is
  raised only when a method that needs the SDK is actually called.
- Adapter MUST translate provider errors into the motor's error
  hierarchy (matched by `type(exc).__name__` when the SDK exceptions
  are not importable without the SDK).

### §2.7 — Test isolation

- **Hermetic > Docker** when possible. Tests inject fakes via
  `sys.modules` (redis) or constructor kwargs (`stripe_module=`) instead
  of requiring a live service.
- PostgreSQL-dependent tests skip gracefully when Docker is unavailable;
  nightly CI covers them with `./ci.sh`.
- Every primitive's test directory has `conftest.py` that redirects
  pytest cache + hypothesis DB out of the primitive dir (§4.1 gate).

### §2.8 — Delivery contract (Pydantic-validated)

Every tool's output conforms to `adapt/contracts/delivery_contract.py`.
The contract is inviolable — tools that return malformed `ToolResult`
fail at runtime. Delivery contract fields:

- `status`: `"success" | "error" | "no_op"`
- `files_created` / `files_modified`: list[str]
- `notes` / `next_steps`: list[str]
- `error`: str | None (present iff `status == "error"`)
- `execution_time_ms`: int (on EVERY return path)

### §2.8b — Tool input contract (ToolInput Pydantic shape)

Counterpart to §2.8 — every extend/verify/operate/evolve tool accepts
a single `ToolInput` argument:

- `project_dir: str` — absolute path (validated by `validate_project_dir`).
- `dry_run: bool = False` — if True, return before any write.
- Extra fields are tool-specific and defined in the tool's module;
  the base `ToolInput` is the MINIMUM contract.

Tools reject:
- Relative paths — `validate_project_dir` returns an error.
- Paths outside the project root — enforced per-tool.
- Missing prerequisites — `ensure_prerequisites()` returns actionable
  errors listing the missing files / config keys.

### §2.9 — Commit hygiene + PR discipline

**Per-commit invariants:**

- Every commit leaves the tree CONTRACT ALL GREEN (rule count bumps
  whenever a new §B rule lands per §2.2.7).
- Every commit leaves the tree pytest-green for the primitives it
  touches (motor + adapter + tool).
- Commit messages: imperative mood, ≤70-char subject, body explains
  WHY not WHAT.
- Co-authored-by Claude Opus 4.7 (1M context) when AI-assisted.
- Never `--no-verify`. Never `--amend` a pushed commit. Never
  `--no-gpg-sign` unless Gustavo explicitly asks.
- Thematic slices: one concern per commit. Don't batch unrelated fixes.

**Pre-commit hook (`.githooks/pre-commit`):**

Activate once per clone:

```bash
git config core.hooksPath .githooks
```

The hook runs:

```bash
cd skills/SKILL-001-fastapi-production
PYTHONPATH=. python3 -m engine.audit.contract_check
```

Hook failure = commit rejected. Fix the underlying issue, don't bypass.

**PR discipline (per CONTRACT §C2):** every PR description MUST include
six blocks:

1. `Phase: N.K` — which §B item this closes.
2. `§A compliance:` — list of §A rules touched and verified.
3. `DoD:` — copy of the DoD block from CONTRACT §B.N.K; each item
   marked ✓ or N/A with reason.
4. `Invariants:` — same shape.
5. `Completeness:` — same.
6. `Quality (SOTA):` — same.

PRs missing any of the six = **REJECTED** (not "fix on review" — the
author MUST self-audit before opening the PR).

### §2.10 — CONTRACT §C / §D / §E — what they are

This ROADMAP summarizes §A + §B. The remaining CONTRACT sections live
at `/CONTRACT.md` and govern:

- **§C — Enforcement (C1-C7):** how the rules bind. C1 session-opening
  audit, C2 PR discipline (above), C3 quarterly ratification by
  Gustavo, C4 amendment log format, C5 machine-check on every commit,
  C6 phase-gate CI, C7 pre-commit hook sample.
- **§D — Explicit non-promises:** HuGR does NOT promise Maestro
  success rates > 70% (target, not guarantee). Does NOT commit
  SKILL-003/004 timelines. Does NOT forbid experiments (branches
  only). Does NOT replace PRODUCT.md. Does NOT tolerate "temporary"
  §A violations.
- **§E — Amendment log:** only place ratification blocks land. Format:
  `### Ratified YYYY-MM-DD by Gustavo` + bullet list of what changed.

### §2.11 — Audit agent policy (§A11 derived)

- **Opus** — correctness-critical audits, architecture decisions,
  review of generated code, catching subtle bugs. Full-context (1M)
  Opus 4.7 is the default for audits on this repo.
- **Sonnet** — bulk spec authoring, mechanical refactors with clear
  specs, parallelizable searches. Never delegate architecture
  judgement to Sonnet.
- **Evidence:** early Sonnet runs hallucinated a race condition (a
  false positive that would have caused wasted refactoring); Opus
  caught 30 real bugs in the same session.
- **Rule of thumb:** if the question is "is this right?", use Opus.
  If the question is "implement this spec", Sonnet is fine.

### §2.12 — stable_hash protocol (consumer-facing)

`engine/index/catalog.json` carries a top-level `stable_hash` field —
SHA-256 hash of the catalog's deterministic content (sorted keys,
canonical JSON, no timestamps). Purpose: let Maestro consumers pin a
session to a specific catalog version.

- **Producer (us):** `engine.index.manifest build` re-computes the
  hash; §B2.4 requires idempotence (same disk → same hash).
- **Consumer (Maestro):** on session open, read `stable_hash`; pin
  the session's tool catalog to it. If the hash changes during a
  session, prompt the user (or abort — caller's choice).
- **CHANGELOG cite:** every `[X.Y.Z]` block cites the `stable_hash`
  at release — consumers that don't have real-time access to the
  catalog can verify the version they're serving matches the
  release notes.
- **Never manually edit `stable_hash`.** It's regenerated; editing
  by hand fails §B2.4 on the next CI run.

---

## Part 3 — Quality standards

### §3.1 — Code style

- **Python target:** 3.11+ (3.11 / 3.12 / 3.13 supported per `pyproject.toml`
  classifiers). 3.11 is the MIN — PEP 604 union syntax and `dict[...]`
  generics are used throughout.
- **Formatter + linter:** `ruff` is the single tool — formatter and
  linter both, configured in `pyproject.toml` `[tool.ruff]` /
  `[tool.ruff.lint]` / `[tool.ruff.lint.per-file-ignores]`. No `black`,
  no `flake8`, no `isort` (ruff subsumes all three).
- **Type hints:** required on all public surface. Type-checking is
  enforced by `ruff` lint rules + runtime `isinstance` guards in
  constructors; there is no `mypy --strict` gate today (revisit in
  Phase 7 if needed).
- **Imports:**
  - `from __future__ import annotations` at top of every `.py` file
    (avoids runtime eval of string annotations).
  - Lazy-import optional SDKs INSIDE function bodies (`# noqa: PLC0415`).
  - No `import *` ever.
  - Absolute imports (`from core.venous.events.PubSub import ...`).

### §3.2 — Comments / docstrings

- **Module docstring** — required on every `.py`; states purpose +
  invariant IDs (if applicable).
- **Class / function docstrings** — required on public surface.
  Sections: `Args:`, `Returns:`, `Raises:` (pep257).
- **Inline comments** — only for WHY, never WHAT. No "this function
  does X" comments — the name says that. Comments explain non-obvious
  constraints / subtle invariants / workarounds with issue refs.
- **Never write planning / decision / analysis docs** unless Gustavo
  asks. Those belong in the PR description, not the codebase.

### §3.3 — Error handling

- **Fail fast at boundaries.** Invalid inputs at the start of a public
  function raise immediately with a specific error.
- **No silent fallbacks.** Every fallback is logged at WARNING with
  actionable context (why the fallback, what the degraded behaviour is).
- **Error hierarchy per domain.** Every primitive has a `<Name>Error`
  base class; sub-errors derive from it so callers can catch one type.
- **No PII in error messages.** Tests assert this where relevant
  (BILL_INV_05 pattern).
- **No bare `except Exception`.** Use `except SpecificError` with
  `# noqa: BLE001` only when the broad catch is intentional (e.g.
  at the DLQ routing boundary).

### §3.4 — Test standards

- **Unit test** (`test_<Name>.py`) — API surface, API contract, invalid
  inputs, introspection. NO I/O, NO network, NO Docker.
- **Behavioural test** (`behavioral_<Name>.py`) — one `test_inv_NN_*`
  function per named invariant. The test function name names the
  invariant it witnesses.
- **E2E test** (`test_<tool>_behavior.py` for adapt tools) — run the
  tool against a fixture project, assert the project actually works
  (imports clean, routes respond, etc.).
- **Hermetic over Docker.** Fake injection via `sys.modules` or
  constructor DI beats `testcontainers`.
- **Coverage floor:** every public function has at least one test path.
- **Test isolation:** each primitive's `conftest.py` redirects caches.
  No `.pytest_cache` or `.hypothesis` in the primitive directory.

### §3.5 — Commits

- **Subject:** `<type>(<scope>): <imperative subject>`, ≤70 chars.
  Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.
- **Body:** WHY the change, not WHAT. Include invariant IDs affected,
  test counts, contract-check result.
- **Trailer:** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
  when AI-assisted.
- **Thematic slices.** One change theme per commit. Don't batch
  unrelated fixes.
- **Never bypass hooks** (`--no-verify`, `--no-gpg-sign`) without
  explicit Gustavo direction.

### §3.6 — Documentation

- **Canonical counts:** live in INVENTORY.md; every narrative doc
  references via B4.7 token-match.
- **Never write a README.md inside a primitive / adapter directory.**
  The `<Name>.md` is THE doc; more files = noise.
- **Examples docs:** every `/examples/<NN>-<name>/` has README +
  MAESTRO_SESSION + cross-link table per §B4.2.
- **ADRs:** `docs/decisions/NNNN-<slug>.md` for architectural choices
  (not every PR).

### §3.7 — Semver policy (semver 2.0.0 + HuGR-specific rules)

- **MAJOR (X.0.0):**
  - Removing a registered primitive OR registered adapter OR
    catalog tool.
  - Renaming a primitive / adapter / tool (even a canonical rename).
  - Removing a namespace from the §2.4 list.
  - Any breaking change to `ToolInput` / `ToolResult` shape.
  - Removing a §A rule (requires a new ratification block first).
  - `stable_hash` consumers MUST re-pin on a MAJOR.
- **MINOR (1.X.0):**
  - Adding a registered primitive, adapter, tool, module, example,
    benchmark spec, namespace (additive only).
  - Adding a new optional field to `ToolInput` / `ToolResult`.
  - Adding a new §B rule (requires same-commit CONTRACT.md update
    per §2.2.7).
  - Broadening `status` values, `tags`, or any other catalog enum
    (additive only).
  - Wave 2 / 3 / 4 progress typically lands as MINOR bumps.
- **PATCH (1.0.X):**
  - Bug fixes with no surface change.
  - Template text improvements in existing tools.
  - Documentation fixes.
  - Performance improvements that do not change observable behaviour.
  - Security fixes (flagged in CHANGELOG with severity).
- **Pre-release suffixes:** `-rc.N` / `-beta.N` / `-alpha.N` allowed;
  `+build.N` metadata allowed (regex validated by §B4.4).

### §3.8 — Dependency policy

- **Python:** 3.11 / 3.12 / 3.13 supported (`pyproject.toml` classifiers).
  3.11 is the MIN — PEP 604 union syntax and `dict[...]` generics are
  used throughout and aren't backportable.
- **Core deps** (required at install): `fastapi`, `pydantic>=2`,
  `sqlalchemy>=2`, `alembic`, `pytest`, `ruff`, `mypy`. Versions pinned
  in `pyproject.toml` + `requirements.txt`.
- **Optional SDKs** (lazy imports — §A7 / §2.6):
  - `redis>=5` (for `RedisPubSubBackend`)
  - `stripe>=8` (for `StripeBillingAdapter`)
  - `celery>=5` (for task generators)
  - `boto3>=1.28` (for AWS-adjacent tools)
  - `opentelemetry-*>=1.25` (for observability tools)
  Each must: (a) remain uninstalled without breaking app boot;
  (b) surface a `<Provider>NotInstalled` error with pip hint on first
  call; (c) have a hermetic fake in its test suite.
- **Version bumps:** minor / patch of a dep → normal PR. MAJOR of a
  dep → ADR at `docs/decisions/` explaining the migration + test
  coverage for the upgrade.
- **Security alerts:** `gh api repos/:owner/:repo/vulnerability-alerts`
  is checked before every release; critical alerts block the cut.
- **Lockfile strategy:** repo ships `requirements.txt` pinned to
  exact versions; installers may override via constraints file.

### §3.9 — CI/CD pipeline overview

All workflows live in `.github/workflows/`. Current set (verified on
disk via `ls .github/workflows/`):

| Workflow | Trigger | What it runs |
|---|---|---|
| `skill-001-ci.yml` | Every push / PR touching `skills/SKILL-001-*` | Full contract check + full pytest + property tests |
| `install-docker.yml` | Nightly + on `pyproject.toml` / `VERSION` / `requirements-mcp.txt` change | Fresh `python:3.12-slim` Docker; `install.sh`; smoke every tool |
| `benchmark-nightly.yml` | Nightly (cron) + workflow_dispatch | `engine.bench.plan_level --publish` + `engine.bench.code_level --publish`; upload artefacts |
| `blind-bench-stub.yml` | On demand + scheduled | Blind benchmark harness against pinned stub fixtures |
| `docs-site.yml` | On main-branch push that touches docs | Rebuilds `engine/docs/build.py` output; deploys docs site |

**Future workflow (post-v1.0):** `release.yml` on `v*` tag push —
publishes GitHub release with CHANGELOG body + attaches `install.sh`
tarball. Not shipped at v1.0 (Gustavo cuts releases manually per
GOLIVE §6).

**Branch strategy:** trunk-based on `main`. Feature branches allowed
but short-lived. No long-lived release branches — hotfixes cut from
tags (see POST_RELEASE.md §2a). Never force-push `main`.

### §3.10 — Performance SLOs

Machine-enforced via `tests/test_performance_baseline.py` (5 tests).
Bounds are the `BOUND_*` constants in that file; this table is a
read-only mirror — the file wins on drift.

| Surface | SLO (upper bound) | Source constant |
|---|---|---|
| `engine.index.manifest build` — catalog load + parse | < 1.0 s | `BOUND_CATALOG_LOAD` |
| `engine.promotion.classify` — full classifier run | < 60.0 s | `BOUND_CLASSIFIER_RUN` |
| `engine.promotion.ledger` — LEDGER.md render | < 5.0 s | `BOUND_LEDGER_RENDER` |
| `engine.audit.contract_check` — full run | < 90.0 s | `BOUND_CONTRACT_CHECK` |
| `engine.index.manifest verify` — idempotent rebuild | < 30.0 s | `BOUND_MANIFEST_VERIFY` |

**Per-tool SLO** (enforced by each tool's behaviour test):

- Every `adapt/extend/add_*` tool completes on a fixture project in
  < 5 s wall clock. `execution_time_ms` is emitted on every
  `ToolResult` return path (§A4 + §2.8); the behaviour test asserts
  it's ≥ 0 and below a per-tool ceiling when one is declared.
- `tests/test_soak.py` — 5-minute sustained load with 10 concurrent
  tool invocations. Asserts zero memory-growth regressions vs the
  baseline snapshot.

**Drift rule:** bumping a `BOUND_*` constant requires same-commit
justification in the test file + CHANGELOG note. Lowering a bound =
free; raising = architecture review (signals perf regression).

**Surfaces NOT yet SLO-gated** (tracked for Wave-2 hardening):

- `fastapi_meta_search` query latency.
- `fastapi_meta_describe` single-id lookup latency.
- `fastapi_meta_compose` plan-generation latency.

These have real p95 budgets conceptually but no enforcement test yet.
Wave 2 will add `tests/test_meta_latency_baseline.py` to close the gap.

### §3.11 — Security posture

Full policy at `/SECURITY.md`. Key points:

- **Disclosure channel:** `security@humangr.com` (see SECURITY.md §Reporting).
- **Response SLA ladder:** Critical 24h / High 48h / Medium 5 days /
  Low best-effort.
- **Supply chain:** lazy SDK imports reduce attack surface (§A7);
  no build-time code from third-party servers.
- **Secrets handling:** tools NEVER commit secrets; generated code
  uses `settings.SECRET_KEY` reads from env.
- **Generated-code audit:** every tool is reviewed for: auth-bypass
  paths, SQL injection, shell injection, secrets leakage to logs.
- **BILL_INV_05-style PII rule generalises** — no primitive's error
  message echoes caller-supplied payload bytes.

### §3.12 — License compliance

- **Repo license:** see `/LICENSE` (proprietary — HumanGR Labs).
- **Attribution footers:** every file copied from the skill into a
  generated project via `scaffold_venous.copy_*` carries a footer
  citing source path + skill commit. Users MUST retain these footers
  unless a separate license agreement supersedes.
- **Third-party deps:** permissive licenses only (MIT / Apache 2.0 /
  BSD). GPL-family dependencies are rejected by review.
- **Copyleft inside emitted templates:** NEVER. Every template
  must be original or under a permissive license compatible with
  downstream proprietary use.

### §3.13 — Project observability (how we measure ourselves)

We dog-food our own discipline:

- **Contract score** — `engine.audit.contract_check` green/total.
  Publicly visible.
- **Benchmark score** — plan + code-level, per-release, in CHANGELOG.
- **Wave progress** — ledger state (staged / quarantined / ready).
- **Drift events** — `git log --grep="drift"` — deliberately low
  frequency means §B4.7 is doing its job; spikes mean we're losing
  discipline.
- **Test counts per release** — archived in
  `benchmarks/history/YYYY-MM-DD.json`.
- **Rails-wiring floor** — §B1.3 count over time; MUST monotonically
  increase or stay flat.

No dashboards yet; GitHub Actions status pages + `engine.audit.*`
command outputs are the current surface. Adding a minimal dashboard
is a Phase 7 item (§6.5).

### §3.14 — Disaster recovery (named scenarios)

These are rare events with binding runbooks; review quarterly.

| Scenario | First action | Authority |
|---|---|---|
| **Compromised CI credentials** (secrets leak from workflow run) | Rotate all GitHub Action secrets; force-expire any tokens referenced in the last 90 days of workflow runs; investigate root cause in a private issue. | Gustavo |
| **Lost / corrupted release tag** | Do NOT re-tag under the same name (§3.7 MAJOR rules forbid it). Instead cut a PATCH bump (`vX.Y.Z+1`) whose CHANGELOG cites the recovery + explains the loss. | Gustavo |
| **Lost main branch** (force-push by mistake) | Recover from a signed tag + every contributor's fork/clone. `git reflog` on Gustavo's local clone is authoritative if remote is gone. Force-push restored state; open a post-mortem ADR. | Gustavo |
| **CHANGELOG or VERSION drift vs released tag** | Treat as a §B4.6 drift bug; ship a PATCH with a `docs(release-drift): …` commit that reconciles the files to the tag. | Claude (driver) + Gustavo (tag) |
| **`stable_hash` collision** (extremely unlikely SHA-256 collision) | Regenerate via `manifest build`; if collision persists, investigate non-deterministic input to the hash function (clock, order). Open a `drift:` commit; file a §B2.4 amendment if the fix changes invariants. | Claude (driver) + Gustavo |
| **Silent ledger corruption** (classifier output disagrees with disk) | Delete `engine/promotion/ledger.json`, rerun `engine.promotion.classify` from scratch, diff old vs new, commit both with the diff in the commit body for audit. | Claude |
| **Benchmark regression > 10 points in a single commit** | Auto-triage: revert the offending commit, open an issue, root-cause on a branch. Re-merge only when benchmark returns to baseline. | Claude (detection) + Gustavo (merge gate) |

**Recovery SLO:** any of the above gets a first response within 24h,
full runbook execution within 72h. Longer requires a POST_RELEASE
amendment.

---

## Part 4 — Definitions of Done (per surface)

A surface is "done" when every bullet below is ✅. Partial = not done.

### §4.1 — Registered primitive DoD

Location: `core/venous/<ns>/<Name>/`

- [ ] Directory name == primitive name (`<Name>`).
- [ ] `<Name>.py` — motor implementation, framework-free.
- [ ] `<Name>.md` — purpose + invariants + `## Compose with:` ≥3 bullets.
- [ ] `__init__.py` — re-exports public names matching `__all__`.
- [ ] `conftest.py` — cache redirect (§3.4).
- [ ] `test_<Name>.py` — unit tests: API surface, Protocol membership,
      construction validation, error hierarchy, frozen dataclasses if any.
- [ ] `behavioral_<Name>.py` — one `test_inv_NN_*` per named invariant;
      ≥3 invariants total.
- [ ] Module docstring lists all invariant IDs.
- [ ] Entry added to `engine/primitives_by_concern.yaml` with ≥3
      `compose_with` bullets.
- [ ] `engine.index.manifest build` passes; catalog reflects the new
      primitive.
- [ ] `engine.audit.contract_check` ALL GREEN (count currently 36; floor
      bumps on each new §B rule per §2.2.7).

Optional (Wave 2+):
- [ ] `<Name>.contract.json` — JSON spec for external consumers.
- [ ] `<Name>.tla` — TLA+ model for concurrency-heavy motors.
- [ ] `dashboard.json` — Grafana dashboard shape.
- [ ] `observability_schema.json` — log / metric emission contract.
- [ ] `persona_reviews.json` — multi-role review artefact.
- [ ] `proposed_invariants.json` — pre-freeze invariant brainstorm.
- [ ] `state_machine_<Name>.py` — explicit state-machine tests.

### §4.2 — FastAPI adapter DoD

Location: `core/venous/_adapters/fastapi/<Name>Adapter.py`

- [ ] File ends in `Adapter.py` (convention for §B1.7 check).
- [ ] Wraps exactly one registered primitive (`<Name>` stem); OR
      listed in `family_map` of §B1.7 rule.
- [ ] Thin wiring only — all invariants enforced by the motor.
- [ ] If middleware: inherits `BaseHTTPMiddleware`, does NOT mutate
      global state.
- [ ] `test_<Name>Adapter.py` in same directory — ≥10 behavioural tests
      covering config validation + every public method + error path.
- [ ] Lazy import for any optional dep inside function bodies.
- [ ] No PII leak in error paths (when applicable).
- [ ] Registered in every relevant `adapt/extend/*.py`'s
      `MCP_TOOL.imports_adapters`.

### §4.3 — Provider adapter DoD (new framework dir)

Location: `core/venous/_adapters/<framework>/<Name>Adapter.py`

All §4.2 bullets plus:

- [ ] `core/venous/_adapters/<framework>/__init__.py` re-exports public
      names (so `from core.venous._adapters.<framework> import X` works).
- [ ] Provider SDK import is LAZY (inside `_get_<sdk>` method or
      first-call site), not at module top.
- [ ] Missing-SDK error (`<Provider>NotInstalled`) raised ONLY at
      call-time, with an actionable install hint.
- [ ] Maps provider errors into motor's error hierarchy by
      `type(exc).__name__` (survives the provider being un-importable).
- [ ] Returns motor value types (`Customer`, `Subscription`, etc.) —
      never leaks raw provider objects.
- [ ] Tests inject a fake provider module via constructor DI or
      `sys.modules` — no live service, no Docker.
- [ ] `scaffold_venous.copy_adapter` picks up the new framework dir
      without additional changes (verify by test).

### §4.4 — Adapt tool DoD (extend)

Location: `adapt/extend/<bucket>/add_<feature>.py`

- [ ] Module docstring: purpose, files created, files modified, design
      decisions, idempotency fingerprint.
- [ ] `MCP_TOOL` dict with:
  - [ ] `name`: `fastapi_<domain>_<verb>_<noun>`
  - [ ] `description`: what the tool does
  - [ ] `tags`: closed vocab
  - [ ] `entry`: function name
  - [ ] `imports_primitives`: registered primitives used (if any)
  - [ ] `imports_adapters`: adapters used (if any)
- [ ] Entry function `add_<feature>(inp: ToolInput) -> ToolResult`.
- [ ] Input validation — `validate_project_dir(inp.project_dir)` first.
- [ ] Prerequisite check — `ensure_prerequisites(...)` with relevant
      `Prereq.*` constants.
- [ ] Idempotency guard — fingerprint detection in the target file;
      returns `status="no_op"` on re-run.
- [ ] `dry_run` branch — returns before any write.
- [ ] `ensure_primitives(...)` call shipping every motor + adapter the
      generated code imports.
- [ ] `ast.parse` validation loop on every created `.py` file.
- [ ] `execution_time_ms` on EVERY return path.
- [ ] Lazy imports for optional SDKs inside emitted templates.
- [ ] `test_add_<feature>.py` — unit tests covering dry_run, idempotency,
      prerequisite errors, file shape.
- [ ] `test_add_<feature>_behavior.py` — E2E against a fixture project;
      imports clean + routes respond.
- [ ] Spec at `specs/TOOL-<NNN>-add_<feature>.md` with DoD + CCs.

### §4.5 — Adapt tool DoD (verify / operate / evolve)

Same as §4.4 except:

- [ ] `verify` tools return `ValidationReport` with per-check pass/fail
      + actionable messages.
- [ ] `operate` tools accept a running-project context; no scaffolding.
- [ ] `evolve` tools are idempotent migrations; dry_run shows the diff.

### §4.6 — Generator DoD

Location: `generators/<category>/<name>.py`

- [ ] Stateless scaffolder — emits files from templates; no hidden
      state between calls.
- [ ] `MCP_TOOL` metadata same as §4.4 (name, description, tags,
      entry, imports_primitives, imports_adapters).
- [ ] Entry function returns `ToolResult` (§2.8) with
      `execution_time_ms` on every return path.
- [ ] Input validation — reject invalid `output_dir` / missing required
      params with a clear `status="error"` + actionable message.
- [ ] Idempotency — rerun against a populated target is a `no_op`
      OR a deterministic overwrite (documented per-generator).
- [ ] `dry_run` branch — returns before any write.
- [ ] `ast.parse` validation loop on every created `.py` file.
- [ ] Lazy imports for optional SDKs inside emitted templates (§A7).
- [ ] `test_<name>.py` — unit tests: runs the generator, asserts
      emitted files AST-parse, idempotency, dry_run, error paths.
- [ ] No orphan `generate_*` / `scaffold_*` function (§B1.6 machine-check).

### §4.7 — Module package DoD

Location: `modules/<category>/<name>/`

- [ ] Pre-built feature bundle — multiple tools orchestrated.
- [ ] README describes composition.
- [ ] Integration test asserts all child tools run clean.

### §4.8 — Example app DoD

Location: `/examples/<NN>-<name>/` (repo-root, NOT skill-internal)

- [ ] Named `<NN>-<kebab-case-name>` with two-digit NN (01-99).
- [ ] `README.md` — purpose + maestro prompt summary + file tree.
- [ ] `MAESTRO_SESSION.md` — the actual prompt + the actual response
      transcript (one complete turn minimum).
- [ ] `app/` — working FastAPI project; `python -m app.main` imports
      cleanly.
- [ ] `tests/` — pytest suite; `pytest -q` passes with 0 failures.
- [ ] Cross-link table in README: which primitives + adapters + tools
      this example exercises (linked by name to the registry).
- [ ] If the example maps to a benchmark spec: the spec's
      `expected_primitives` + `expected_tools` match the cross-link
      table.
- [ ] Listed in `/examples/README.md` index (title + one-line summary).
- [ ] `requirements.txt` pins exactly what `app/main.py` imports — no
      unused deps, no missing deps.
- [ ] No `.env` / secrets committed; `.env.example` only.

### §4.9 — Benchmark spec DoD

Location: `benchmarks/specs/<tier>/<NN>_<slug>.md` where `<tier>` ∈
`{baseline, mid, adversarial}` and `<NN>` is zero-padded (01..20
across tiers).

- [ ] `# <title>` top-level heading naming the scenario.
- [ ] `## Requirements` — bulleted functional requirements the
      scaffold must satisfy. Plain English, NO primitive / tool
      name hints (§B3.1 Invariant).
- [ ] `## Acceptance criteria` — bulleted testable outcomes (status
      codes, request shapes, concurrency claims, …). Each bullet
      must be verifiable against a running app.
- [ ] `## Non-requirements` — explicit scope exclusions so the
      Maestro doesn't over-build. "Out of scope" > "undefined".
- [ ] Tier directory matches the `<tier>` filename component
      (`baseline/`, `mid/`, `adversarial/`).
- [ ] Spec surfaces in both plan-level and code-level rubrics
      (referenced in `benchmarks/latest_score.json` +
      `benchmarks/code_level_score.json`).
- [ ] Code-level coverage: spec has a matching fixture app +
      pytest suite under `benchmarks/code_level/<tier>/<NN>_<slug>/`
      that scores the tool-generated output.
- [ ] `_r_bench_specs` (§B3.1) validates every bullet above in
      machine form.

---

## Part 5 — Ship gate to v1.0.0

Everything below runs BEFORE we tag `v1.0.0`. Operational commands for
each item are in `/GOLIVE.md §1-§6`.

### §5.1 — Ratifications (Gustavo-side) — 5 items

- [ ] `/FREEZE.md §4` signed with a real date (`Ratified YYYY-MM-DD by Gustavo`).
- [ ] `CONTRACT.md §A12` amended per `docs/decisions/0004-tier-lite.md §3`
      (triage-pass clause added as an alternative §A12 trigger).
- [ ] `CONTRACT.md §E` block appended with today's date citing the
      ratification of §A12 amendment + §B1.8 tier-lite + §B1.7 adapter
      coverage.
- [ ] `docs/decisions/0004-tier-lite.md` status flipped from "Proposed"
      to "Ratified YYYY-MM-DD".
- [ ] This ROADMAP.md §11 signed (see §11 below).

### §5.2 — Promotion pipeline verify (Claude) — 3 items

- [ ] `engine.promotion.classify` runs clean; ledger.json reflects
      post-Wave-1.5 state (219 entries, needs_review=0).
- [ ] `engine.promotion.ledger` regenerates LEDGER.md byte-identical
      on re-run (idempotent).
- [ ] No ledger entry with `PROMOTE_AS_*` verdict + zero blockers is
      unactioned — every such entry is either executed OR listed in
      `/FREEZE.md §2` as an explicit deferral.

### §5.3 — Full test pass (Claude) — 15 suites

- [ ] Unit tests: `pytest skills/SKILL-001-fastapi-production -q` — 0 failures.
- [ ] Promotion module tests: 38/38 pass.
- [ ] Boot test (100-tool smoke): `python tests/test_boot.py` exits 0.
- [ ] Boot chain tests (forward + reverse).
- [ ] E2E hardcore (SQLite, 12 scenarios).
- [ ] E2E PostgreSQL (via `./ci.sh` if Docker available).
- [ ] Behavior scenarios (12 domain archetypes, requires PostgreSQL).
- [ ] Cross-composition (200+ scenarios).
- [ ] Property tests (8 properties × ≥120 tools).
- [ ] Stress test (100-tool).
- [ ] Soak test (5-min, 10 concurrent).
- [ ] Mutation runner (≥10-module sample).
- [ ] All `/examples/*/` pass `pytest -q` — 20/20 clean.
- [ ] Performance baseline: `pytest tests/test_performance_baseline.py` — 5/5.
- [ ] Install-Docker workflow green for the 48h pre-freeze window
      (2 consecutive nightly runs green, per POST_RELEASE.md §1).

### §5.4 — Benchmark gate (Claude) — 5 items

- [ ] Plan-level benchmark ≥ 90 (§B3.5 machine-check threshold; current 100.00).
- [ ] Code-level benchmark ≥ 70 on 20/20 covered specs (§B3.6 machine-check; current 100.00).
- [ ] Freeze-day benchmark artefacts committed to
      `benchmarks/history/YYYY-MM-DD.json`.
- [ ] No per-spec regression — every spec scored ≥ 50.
- [ ] CHANGELOG [1.0.0] cites both scores + 20/20 coverage + stable_hash.

### §5.5 — Release artefacts (Claude) — 8 items

- [ ] INVENTORY.md regenerated; `git diff INVENTORY.md` empty.
- [ ] `catalog.json stable_hash` idempotent across two builds.
- [ ] `VERSION` bumped to `1.0.0` (both repo-root + skill-dir + STATUS.md frontmatter).
- [ ] CHANGELOG [1.0.0] block complete per §5.4 bullet 5.
- [ ] README.md score line + phase badge show `v1.0.0`.
- [ ] SKILL.md v2 counts reconcile against INVENTORY.md (manual audit;
      §B2.5 machine-check asserts the doc's shape but not its numbers
      — counts propagate via the INVENTORY → narrative-docs chain that
      §B4.7 enforces).
- [ ] CONTRACT.md §E updated per §5.1 bullet 3.
- [ ] This ROADMAP.md post-v1.0 state reflected (Phase 5 ✅, waves scheduled).

### §5.6 — Tag + push + release (Gustavo-side) — 3 items

- [ ] Signed tag `v1.0.0` using `GOLIVE.md §6.1a` template.
- [ ] Push `main` + tag.
- [ ] GitHub release draft with body pointing to CHANGELOG [1.0.0].

### §5.7 — 72h post-release monitoring — 6 items

- [ ] Install.sh validated on release tag nightly for 48h (green 2x in a row).
- [ ] POST_RELEASE.md §1 audit commands pass every morning for 72h
      (contract_check + manifest verify + classify).
- [ ] No legitimate user reports of `fastapi_meta_*` tool-not-found
      within 6h post-tag.
- [ ] No benchmark regression < 95 on any spec within 12h post-tag.
- [ ] No unresolved `security@humangr.com` message within 24h (per
      SECURITY.md §Response SLA).
- [ ] No `37/37 ALL GREEN` regression on `main` within 72h.

### §5.8 — Rollback decision tree (if critical surfaces)

Full runbook at `/POST_RELEASE.md §2`. Decision path:

1. Bug is security-Critical or severity-High, fix < 1 day? → **§2a
   hotfix** (branch from `v1.0.0`, bump PATCH, ship `v1.0.1`).
2. Consumers cannot run v1.0.0 at all, no same-day fix? → **§2b yank**
   (mark pre-release + "Do not install" banner; never delete tag).
3. Freeze commit itself is broken, no surgical patch viable? →
   **§2c emergency revert** (revert-merge on `main`, tag as `v1.0.1`).
4. Else (Medium / Low) → standard PR cycle; land in next MINOR.

**Never** `git tag --force` a published tag. Never `git push --force`
`main`. Never delete a published tag.

**Ship gate total: 5 + 3 + 15 + 5 + 8 + 3 + 6 = 45 items.**

> **The ship gate above cuts the tag. The tag alone does NOT launch
> the product.** Post-tag, the public rollout follows `LAUNCH.md` —
> the zero-risk launch protocol (belt + suspenders + tailored
> pants: evidence package + phased rollout + rollback-ready ops).
> That is a SEPARATE doc binding at the same tag cut; see `/LAUNCH.md`
> for evidence-package requirements, the alpha → beta → public
> phase ladder, and launch-phase exit criteria.

### §5.9 — What a "stable v1.0.0" call looks like

Day 7 post-tag: if all §5.7 items stayed green AND no `v1.0.1` or
`v1.0.2` shipped, Gustavo marks `v1.0.0` "stable" via:

- A new `/docs/releases/v1.0.0-day7-stable.md` entry (Gustavo's
  one-pager summary).
- `GOLIVE.md §6.4` check flipped to ✅.
- Day-14 retro in `/docs/releases/v1.0.0-retro.md`.

---

## Part 6 — Post-v1.0 waves (ordered)

Ordered by dependency + risk. Earlier wave reduces surface before later
wave adds to it.

### §6.1 — Wave 2 — Tier-lite middleware (pool harvest)

- **Goal:** register ~40-60 stateless HTTP middleware from `_extracted/`
  as tier-lite primitives (new tier per §B1.8).
- **Source of truth:** `engine/promotion/LEDGER.md` — filter verdict
  `promote_lite` OR `promote_as_primitive` with `stateless` + `framework-free`
  signals present.
- **Candidates (initial sample, not exhaustive):** `RequestId`,
  `Deprecation`, `CORS`, `JsonError`, `RequestSigning`, `Sanitize`,
  `SchemaEnforcer`, `AnomalyMiddleware`, `ChaosMiddleware`,
  `CostMiddleware`, `DLPMiddleware`, `RecorderMiddleware`,
  `ResponseArmorMiddleware`. Full list: regenerate ledger, grep
  `verdict="promote_lite"`.
- **Criteria (§B1.8):** stateless, framework-free, no REPLACE_ME
  markers, ≤30 LOC motor body, no concurrency, no mutable class state.
- **Skeleton per primitive:**
  - `<Name>.py` (lite-tier: motor only, no invariant_bindings / dashboard).
  - `<Name>.md` with ≥3 `## Compose with:` bullets.
  - `test_<Name>.py` with ≥3 behavioural tests.
  - Entry in `primitives_by_concern.yaml` with `tier: "lite"`.
  - Optional `<Name>Adapter.py` under `_adapters/fastapi/`.
- **Numeric exit criteria:**
  - `_r_tier_lite_eligibility` (§B1.8) reports **≥ 40 lite primitives
    registered** with all checks green.
  - Staged count drops by ≥ 40 (from 176 → ≤ 136).
  - Ledger `promote_lite` verdict count drops by ≥ 40.
  - §B4.7 narrative-doc reconciliation auto-updated per Wave-2
    batch commit.
- **Wave 2 CHANGELOG entry** cites: lite-count, staged-count
  delta, list of newly-registered primitives.
- **Esforço:** 3-5h (batch-promote ~20/week → 2-3 weeks wall-clock).
- **Checklist:** §7.F.

### §6.2 — Wave 3 — EXTRACT_MOTOR_PAIR (~118 items)

- **Goal:** split each framework-coupled staged primitive into
  (framework-free motor + FastAPI adapter), mirroring the Bulkhead /
  PubSub / Billing templates.
- **Source of truth:** `engine/promotion/LEDGER.md` — filter verdict
  `extract_motor_pair` (118 entries as of v1.0 freeze).
- **Per-item work:**
  1. Read the inline coupling in the staged `<Name>.py`.
  2. Write motor `core/venous/<ns>/<Motor>/Motor.py` + shell (§4.1).
  3. Write adapter `core/venous/_adapters/fastapi/<Motor>Adapter.py` (§4.2).
  4. Write ≥3 behavioural tests per invariant (§3.4).
  5. Rails-connect the caller tool (§7.D).
  6. Delete the staged source + quarantined twin (§A12 pool discipline).
  7. Regenerate LEDGER + catalog.
- **Numeric exit criteria:**
  - Ledger `extract_motor_pair` verdict count: **118 → 0**
    (or Gustavo signs an explicit "defer N items" amendment).
  - Staged count: **≤ (176 - 40 Wave-2) - 118 ≈ 18** by end of Wave 3.
  - §B1.7 adapter count goes **17 → ≥ 80** (assuming roughly 2/3
    of pairs need a fastapi adapter).
  - §B1.3 Rails-wiring floor: **24 → ≥ 50** (Wave 3 Rails-wires every
    refactored caller tool).
- **Esforço:** ~2-4h per item × 118 = 1-2 weeks full-time (feasible as
  per-commit work over a quarter).
- **Checklist:** §7.G.

### §6.3 — Wave 4 — NEEDS_CALLER triage (~101 items)

- **Goal:** for each staged primitive with no §A12(b) trigger, either
  (a) wire it into a new/existing tool (promote), or (b) mark redundant +
  delete, or (c) write a `STAGING.md` one-liner explaining why it's
  still staged.
- **Source of truth:** `engine/promotion/LEDGER.md` — filter verdict
  `needs_caller` (101 entries at v1.0 freeze).
- **Per-item decision tree:**
  1. Does any `adapt/extend/*` tool currently inline this logic? If
     YES → reclassify as `extract_motor_pair`, handle in Wave-3 lane.
  2. Does a benchmark spec exercise the domain? If YES → write the
     missing tool that imports this primitive (tool-signal = §A12
     trigger satisfied); follow §7.E.
  3. Is it a clean duplicate of a registered primitive? If YES →
     `engine.promotion.promote --delete <Name>` (after reclassifying
     to REDUNDANT).
  4. Else → write `_extracted/<ns>/<Name>/STAGING.md` with one-line
     rationale (process item preserved from old ROADMAP Phase-5 #30).
- **Numeric exit criteria:**
  - Ledger `needs_caller` verdict count: **101 → 0**.
  - Every remaining staged entry has either a `STAGING.md` file OR
    a new contract rule §B1.4.X validating "every staged entry has
    rationale".
  - Staged count: trending toward **≈ 0** (those that remain have
    documented rationale).
- **Esforço:** 1-2 days wall-clock (decision per item is ~5 min;
  bulk of work is the "YES → Wave-3" reclassifications).
- **Checklist:** §7.H.

### §6.4 — Phase 6 — SKILL-002 (post all waves)

- **Goal:** second framework skill that reuses HuGR's primitive shell +
  benchmark harness.
- **Candidates (choose by demand):** Django REST, Next.js (frontend +
  API routes), LLM-agent backend.
- **Exit criteria for "second skill done":**
  - 70%+ code-level benchmark on the second skill's 20-spec corpus.
  - Shared primitives across SKILL-001 and SKILL-002 documented as
    cross-skill registry entries.
  - Multi-skill Maestro session works (one session, two skills).

### §6.5 — Phase 7 — Ecosystem

- Community contributions with T0-T9 extraction gate + Opus audit.
- Public benchmark scoreboard (per-release, code-level).
- SDK for Maestro authors (shipping against the skill's MCP surface).

---

## Part 7 — Operational checklists

Copy-pasteable. Each checklist is self-contained — you don't need to
read the rest of this doc to use one.

### §7.A — Checklist: Promoting a new registered primitive

**Use when:** pool has a staged primitive you want to make production.

1. [ ] Decide motor name (framework-free noun; no `Manager` / `Backend`
       suffix unless the registered parent already has that shape).
2. [ ] Choose namespace from §2.4. Add namespace if needed (rare).
3. [ ] `mkdir core/venous/<ns>/<Motor>/`
4. [ ] Write `<Motor>.py` — Protocol + reference backend + error
       hierarchy + module docstring listing invariant IDs.
5. [ ] Write `<Motor>.md` — purpose + invariants + ≥3 `## Compose with:`.
6. [ ] Write `__init__.py` re-exporting `__all__`.
7. [ ] Write `conftest.py` (cache redirect — copy from Bulkhead for template).
8. [ ] Write `test_<Motor>.py` — ≥5 unit tests (surface, Protocol,
       construction, slots, error hierarchy).
9. [ ] Write `behavioral_<Motor>.py` — one `test_inv_NN_*` per named
       invariant; ≥3 total.
10. [ ] Add entry to `engine/primitives_by_concern.yaml` with ≥3
        `compose_with` bullets.
11. [ ] Run `PYTHONPATH=. .venv/bin/python -m pytest core/venous/<ns>/<Motor>/ -q`
        — 0 failures.
12. [ ] Run `PYTHONPATH=. .venv/bin/python -m engine.index.manifest build`.
13. [ ] Run `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check`
        — all rules green (output ends with `N/N ALL GREEN`).
14. [ ] Commit with `feat(SKILL-001/<ns>): promote <Motor> motor primitive`.

### §7.B — Checklist: Promoting a FastAPI adapter

**Use when:** a registered motor needs FastAPI-specific wiring.

1. [ ] File at `core/venous/_adapters/fastapi/<Motor>Adapter.py`.
2. [ ] Module docstring cites the motor + invariants it honours.
3. [ ] `__all__` lists public names.
4. [ ] Config dataclass with `__post_init__` validation.
5. [ ] Re-entrant context manager if motor uses `@asynccontextmanager`.
6. [ ] `BulkheadMiddleware`-style middleware: inherits
       `BaseHTTPMiddleware`, translates motor errors → HTTP responses.
7. [ ] Write `test_<Motor>Adapter.py` — ≥10 behavioural tests covering
       config validation + every method + error path.
8. [ ] Update `family_map` in `engine/audit/contract_check.py#_r_adapter_coverage`
       IF adapter name doesn't match a registered primitive (rare).
9. [ ] If the motor just got its adapter: update affected
       `adapt/extend/*.py` to declare `imports_adapters` (see §7.D).
10. [ ] Contract check all rules green.
11. [ ] Commit `feat(SKILL-001): promote <Motor>Adapter (Nth FastAPI adapter)`.

### §7.C — Checklist: Promoting a provider adapter (new framework dir)

**Use when:** a motor needs a Redis/Stripe/etc. backend.

1. [ ] `mkdir core/venous/_adapters/<framework>/`
2. [ ] Write `__init__.py` re-exporting the adapter class +
       `<Provider>NotInstalled` error.
3. [ ] Write `<Motor>Adapter.py`:
   - Lazy SDK import inside `_get_<sdk>` method.
   - Constructor accepts `<sdk>_module: Any = None` for test DI.
   - Translates provider errors by `type(exc).__name__` match.
   - Returns motor value types, never raw provider objects.
4. [ ] Write `test_<Motor>Adapter.py` — inject fake module via
       constructor DI; cover lazy-import, missing-SDK error, every method,
       error translation, no-PII assertions.
5. [ ] Verify `generators/scaffold_venous.copy_adapter` ships the
       framework's `__init__.py` (already does since Wave 1.5 fix).
6. [ ] Update relevant `adapt/extend/*.py` to declare both the primitive
       and the adapter in `MCP_TOOL`; also `ensure_primitives(adapters=[...])`.
7. [ ] Update `_adapters/<framework>/__init__.py` in the source to
       re-export the adapter (so generated projects get the re-export).
8. [ ] Update this ROADMAP §1.1 "Provider adapters" count.
9. [ ] Contract check green.
10. [ ] Commit.

### §7.D — Checklist: Rails-connecting an existing extend tool

**Use when:** an extend tool emits inline code that a registered
primitive + adapter could replace.

1. [ ] Identify the primitive + adapter the tool duplicates.
2. [ ] Add to `MCP_TOOL`:
   - `imports_primitives: ["core.venous.<ns>.<Motor>"]`
   - `imports_adapters: ["core.venous._adapters.<framework>.<Name>Adapter"]`
3. [ ] Early in the tool body, call:
   ```python
   from generators.scaffold_venous import ensure_primitives
   manifest = ensure_primitives(
       str(project),
       names=["core.venous.<ns>.<Motor>"],
       adapters=["core.venous._adapters.<framework>.<Name>Adapter"],
   )
   files_created.append(manifest.path)
   ```
4. [ ] Replace inline class definitions in the emitted template with
       `from core.venous.<ns>.<Motor> import ...`.
5. [ ] Keep a compat alias function (e.g. `def StripeBilling(): return get_stripe_billing()`)
       so legacy callers still work.
6. [ ] Update idempotency fingerprint check to accept BOTH the new
       fingerprint (`get_<thing>`) AND the legacy fingerprint.
7. [ ] Update tool docstring, notes, and next_steps lines to reflect
       motor + adapter wiring.
8. [ ] Update `test_add_<feature>.py` expectations:
   - Assert `from core.venous.<ns>.<Motor> import` in the emitted file.
   - Assert motor + adapter files shipped into project tree.
   - Reject module-level `import <sdk>` (enforce lazy-import).
9. [ ] Update `test_add_<feature>_behavior.py`:
   - Purge cached `core.venous.*` modules before `importlib.import_module`
     so the project-local copy loads.
   - Drive the fanout / billing call through the new factory
     (`get_<thing>()`).
10. [ ] Contract check all rules green; §B1.3 Rails-wiring count goes up by 1.
11. [ ] Commit `feat(SKILL-001): Rails-connect add_<feature>`.

### §7.E — Checklist: Adding a new extend tool

**Use when:** a benchmark gap or user ask demands new slice generation.

1. [ ] Name follows `fastapi_<domain>_<verb>_<noun>` — reserve in
       `engine/index/schemas.py#VERBS`/`DOMAINS` if new.
2. [ ] File at `adapt/extend/<bucket>/add_<noun>.py`.
3. [ ] Write spec first at `specs/TOOL-<NNN>-add_<noun>.md`:
   - CCs (completeness criteria) — what "done" looks like.
   - DoD — ≥ 18 machine-checkable items.
   - QS (quality standards) — ≥ 12 items.
   - INVs — ≥ 10 invariants the tool upholds.
4. [ ] Write the tool per §4.4 DoD.
5. [ ] Every `ToolResult` return path emits `execution_time_ms`.
6. [ ] Lazy imports for any optional SDK inside emitted templates.
7. [ ] Idempotency fingerprint check.
8. [ ] `ast.parse` validation loop on every created `.py`.
9. [ ] `test_add_<noun>.py` — ≥ 20 unit tests covering CCs.
10. [ ] `test_add_<noun>_behavior.py` — ≥ 10 E2E scenarios.
11. [ ] Wire into `tests/test_boot.py` + `tests/test_stress.py` +
        `tests/property_tests.py`.
12. [ ] Regenerate catalog + ensure contract green.
13. [ ] Commit with `feat(SKILL-001/<bucket>): add_<noun>`.

### §7.F — Checklist: Wave 2 tier-lite candidate promotion

**Use when:** promoting a stateless middleware from `_extracted/` to a
registered tier-lite primitive.

1. [ ] Run `engine.promotion.classify`; confirm candidate verdict is
       `promote_lite` or `promote_as_primitive` with "stateless" signal.
2. [ ] Confirm §B1.8 criteria — no concurrency, no mutable class state,
       no REPLACE_ME, ≤30 LOC motor body.
3. [ ] `mkdir core/venous/<ns>/<Name>/`
4. [ ] Copy `<Name>.py` from `_extracted/<ns>/<Name>/<Name>.py`; scrub
       framework coupling (imports + types).
5. [ ] Shrink to motor-only (lite tier doesn't need TLA+, dashboard, etc.).
6. [ ] Write `<Name>.md` (≥3 compose_with).
7. [ ] `__init__.py` + `conftest.py`.
8. [ ] `test_<Name>.py` — ≥ 3 behavioural tests.
9. [ ] Add to `primitives_by_concern.yaml` with `tier: "lite"`.
10. [ ] If a FastAPI adapter is useful → §7.B; else skip.
11. [ ] Regenerate LEDGER via `engine.promotion.classify` + `ledger`.
12. [ ] Delete the `_extracted/<ns>/<Name>/` + quarantined twin (if present).
13. [ ] Contract check green; `_r_tier_lite_eligibility` reports the
        new lite entry.
14. [ ] Commit: `feat(SKILL-001/<ns>): promote <Name> tier-lite`.

### §7.G — Checklist: Wave 3 motor+adapter split (EXTRACT_MOTOR_PAIR)

**Use when:** staged primitive is framework-coupled and needs splitting.

1. [ ] Read the staged primitive's body + identify the framework
       coupling (FastAPI / Starlette / APIRouter / Mapped imports).
2. [ ] Design the motor API (framework-free Protocol + reference backend
       + invariant IDs).
3. [ ] Follow §7.A to land the motor.
4. [ ] Follow §7.B to land the FastAPI adapter.
5. [ ] Identify the caller tool(s) in `adapt/extend/`. Follow §7.D for
       each.
6. [ ] Delete the `_extracted/<ns>/<Name>/` + quarantined twin.
7. [ ] Regenerate LEDGER; staged count goes down by 1-2 (depending on
       if there's a quarantined twin).
8. [ ] Contract check all rules green.
9. [ ] Update this ROADMAP §1.1 counts when batch completes (every
       10-20 items).

### §7.H — Checklist: Wave 4 NEEDS_CALLER decision

**Use when:** staged primitive has no §A12(b) trigger.

1. [ ] Check: any `adapt/extend/*.py` inlines this logic today?
   - YES → mark as `extract_motor_pair` (Wave 3) and exit.
2. [ ] Check: benchmark spec exercises the domain?
   - YES → write the missing tool that imports the primitive; follow §7.E.
3. [ ] Check: clean duplicate of a registered primitive?
   - YES → `engine.promotion.promote --delete <Name>` (after classifier
     marks it REDUNDANT).
4. [ ] Else: write `_extracted/<ns>/<Name>/STAGING.md` with one-line
       rationale (process item from old ROADMAP Phase-5 #30).
5. [ ] Regenerate LEDGER.
6. [ ] Contract check green.

### §7.I — Checklist: Release engineer's pre-tag checklist

**Use when:** cutting v1.0.0 (or any semver release).

1. [ ] Verify tree is clean: `git status` shows nothing.
2. [ ] On `main` branch, up to date with `origin/main`.
3. [ ] Run §5.1-§5.5 checklists — all 36 items (5 + 3 + 15 + 5 + 8) green.
4. [ ] `cat VERSION` == target version (e.g. `1.0.0`).
5. [ ] `jq -r .stable_hash engine/index/catalog.json` cited in CHANGELOG.
6. [ ] CHANGELOG block header has real date (not `YYYY-MM-DD`).
7. [ ] `PYTHONPATH=. .venv/bin/python -m engine.index.manifest verify`
       exits 0 (idempotent stable_hash).
8. [ ] `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check`
       reports `N/N ALL GREEN` (N is the current §B rule count).
9. [ ] Rehearsal tag in a throwaway branch; verify tag message renders.
10. [ ] On final commit, `git tag -s <version> -F .git/TAG_MSG`.
11. [ ] `git push origin main <version>`.
12. [ ] Create GitHub release with body = CHANGELOG [version] block.

### §7.J — Checklist: 72h post-release monitoring

**Use when:** first 72h after a tag lands.

1. [ ] Morning day 1: run POST_RELEASE.md §1 audit commands; log
       results.
2. [ ] Morning day 2: same.
3. [ ] Morning day 3: same.
4. [ ] Monitor `install-docker.yml` nightly runs — all green against
       the release tag.
5. [ ] Any red signal → follow POST_RELEASE.md §2 rollback runbook.

### §7.K — Checklist: Deprecating a primitive / adapter / tool

**Use when:** a surface is being removed (v2.0.0 work, not v1.x).

1. [ ] Post a MAJOR-bump migration note in MIGRATION.md with the
       replacement path.
2. [ ] Mark the surface `@deprecated` in code (Python warning) +
       `status: "deprecated"` in catalog.
3. [ ] Keep the surface functional for at least one minor version.
4. [ ] Remove in the MAJOR release; update every narrative doc.
5. [ ] Update this ROADMAP's counts.

---

## Part 8 — Governance, risks, drift-fighting protocol

### §8.1 — Decision-making authority

- **Gustavo** is the final arbiter per CONTRACT §C3 (quarterly
  ratification) and §C4 (amendment log format).
- **Claude (Opus)** is the default audit + implementation collaborator
  for this repo (see §2.11).
- **External contributors** (post-Phase-7) submit PRs against the
  §C2 six-block template; review by Gustavo or a delegated reviewer.
- **No merges without §C2 compliance.** PRs missing any of the six
  mandatory blocks are closed without review.

### §8.2 — Risks (named honestly)

Preserved + expanded from the old ROADMAP Part 3.

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Maestro success ceiling.** If 70% code-level benchmark is unattainable with current LLM capability, the product thesis fails. | De-risked: v1.0 shipping at 100.00. Re-measure per release; if a major LLM regression drops us under 70, we hotfix or yank. |
| R2 | **Rails-analogy limits.** Rails had 20 years + human-first runtime. HuGR is LLM-first. Some ergonomic expectations won't transfer. | Treat analogy as design lodestar, not contract. Benchmark-driven iteration. |
| R3 | **Framework churn.** FastAPI / Pydantic / SQLAlchemy breaking releases are real cost. | Pin versions per release; nightly CI against pinned stack; dep-MAJOR bumps require ADR. |
| R4 | **Integration-discipline drift.** §B1.3 floor (currently 22; 24 Rails-connected) regresses if new tools ignore the rule. | Contract §B1.3 non-regression + §C6 phase-gate CI. |
| R5 | **Staging pool temptation.** 176 staged primitives tempt preemptive promotion. | §A12 discipline + ledger classifier + §7.H/§7.G checklists. Wave-1.5 set the precedent: promote only on signal. |
| R6 | **Drift between this doc and reality.** The doc becomes aspirational; the code is truth. | §B4.7 machine-check + §8.3 drift-fighting protocol. This doc freezes on ratification — amendments go through §8.5. |
| R7 | **Per-primitive invariant drift.** §2.5 table can't keep up with 124 primitives. | Per-commit gate (checklist §7.A); proposed §B rule to AST-scan every `core/venous/*/*.py` for `INV_` prefix + diff against §2.5 — Wave-2 follow-up. Until that rule lands, §2.5 is a best-effort index of the 4 fully-documented families. |
| R8 | **Dependency supply-chain compromise.** Lazy imports don't fully mitigate if a user installs the SDK. | Pin minor versions in `pyproject.toml`; security-alerts gate releases (§3.11). |
| R9 | **Single-person bus factor (Gustavo).** All ratifications currently go through one person. | Accept for v1.0-v1.x; delegation protocol is a Phase 7 item. |
| R10 | **Benchmark overfit.** 100.00 on 20 specs doesn't guarantee 100.00 on spec 21. | Blind benchmark harness (§B3.7) + new specs with every major use-case. |
| R11 | **Stale stable_hash in consumers.** Maestro sessions pin a hash that a patched release invalidates. | CHANGELOG cites `stable_hash` every release. §2.12 consumer protocol says: abort the session on hash change AND surface the new hash to the user with a pointer to the CHANGELOG entry. PATCH releases that change `stable_hash` MUST document the change explicitly in the `[X.Y.Z]` block (semver §3.7: PATCHes shouldn't surface-change, but bug-fix code edits regenerate the hash even when the tool catalog shape is identical). |
| R12 | **Wave fatigue.** 118 + 101 = 219 post-v1.0 items is a marathon. | Batch per-wave commits (20/week); accept that "done" for post-v1.0 waves is months not weeks. |

### §8.3 — Drift-fighting protocol

Drift = any divergence between this doc, CONTRACT.md, INVENTORY.md, or
the actual code on disk. Drift is the #1 enemy of a frozen roadmap.

**Preventive (machine-checked):**

- §B4.7 canonical counts — four narrative docs (CLAUDE / STATUS /
  ROADMAP / CHANGELOG) reconcile against INVENTORY.
- §B1.1 registry vs disk — every dir has an MD and vice versa.
- §B2.4 catalog stable_hash — idempotent across two consecutive builds.

**Detective (reviewer-enforced):**

- §8.4 doc-map audit quarterly (Gustavo) — each canonical doc is
  re-read for drift against its scope.
- §2.5 per-primitive table — §7.A step 14 forces same-commit update.
- §2.2 §B table — §2.2.7 forces same-commit `Rule(...)` registration.

**Corrective (when drift found):**

1. File the drift as a `drift:` prefix commit on `main`.
2. Add a new §B rule if the drift class is general (§2.2.7 process).
3. Update this ROADMAP §8.2 risk table if the drift class wasn't
   previously named.
4. Amendment log entry in §11 citing the drift commit.

**Success metric:** `git log --grep="drift:" --since="3 months ago" | wc -l`
trends toward zero between ratifications.

### §8.4 — Documentation map (which doc owns what)

> **Single-owner rule.** Each topic has exactly one canonical home.
> Every other doc that mentions it carries a link, not a copy.

| Topic | Canonical home | Cross-referenced in |
|---|---|---|
| Product contract (what HuGR promises) | `/PRODUCT.md` | CLAUDE.md, ROADMAP.md §0 |
| Machine-checked rules | `/CONTRACT.md` §A + §B | ROADMAP.md §2, GOLIVE.md §3 |
| v1.0 scope lock | `/FREEZE.md` §1 | ROADMAP.md §5, CHANGELOG.md [1.0.0] |
| Operational commands for the cut | `/GOLIVE.md` | ROADMAP.md §5 |
| Zero-risk launch protocol (evidence + phased rollout) | `/LAUNCH.md` | ROADMAP.md §5, FREEZE.md §2, POST_RELEASE.md §2 |
| 72h runbook + rollback | `/POST_RELEASE.md` | ROADMAP.md §5.7/§5.8, LAUNCH.md §4 |
| v0.x → v1.0 breaking changes | `/MIGRATION.md` | CHANGELOG.md, CONTRIBUTING.md |
| Security disclosure + SLA | `/SECURITY.md` | ROADMAP.md §3.11, POST_RELEASE.md §3 |
| Maestro / Forge consumer contracts | `/INTERFACES.md` | PRODUCT.md §2, ROADMAP.md §2.12 |
| Release notes + benchmark history | `/CHANGELOG.md` | ROADMAP.md §3.7, GOLIVE.md §5 |
| Contributor onboarding | `/CONTRIBUTING.md` | README.md |
| Machine-generated counts | `/skills/SKILL-001-fastapi-production/INVENTORY.md` | CLAUDE.md, ROADMAP.md §1, STATUS.md, CHANGELOG.md |
| Human-readable surface counts | `/skills/SKILL-001-fastapi-production/STATUS.md` | README.md |
| Skill contract (Maestro-facing) | `/skills/SKILL-001-fastapi-production/SKILL.md` | — |
| Architectural decisions | `/docs/decisions/NNNN-*.md` | ROADMAP.md (specific refs), CONTRACT.md §C |
| Promotion pipeline ledger | `/skills/SKILL-001-fastapi-production/engine/promotion/LEDGER.md` | ROADMAP.md §6 |
| This strategy doc | `/ROADMAP.md` (this file) | every doc points here |

**Rule:** a new cross-doc concept MUST be added to this map in the
same commit that introduces the doc/topic.

### §8.5 — Amendment process (how to change this frozen doc)

Once §11 is signed, this doc is read-only. Changes require:

1. **Write the amendment** as an edit to the relevant section.
2. **Add a dated line** to §11's amendment log:
   ```
   ### Amendment YYYY-MM-DD by Gustavo
   - <bullet summarizing the change>
   - <rationale>
   ```
3. **Tie to machine check** if the amendment adds/changes a rule —
   same-commit `Rule(...)` registration per §2.2.7.
4. **Regenerate dependents** — if the amendment changes counts /
   thresholds / namespaces, re-run `engine.inventory`,
   `engine.index.manifest build`, `engine.audit.contract_check`.
5. **Commit** with prefix `docs(roadmap-amendment): <short desc>`.

**Amendments that require re-ratification** (full new block, not just
an "Amendment" line):

- Removing a §A rule (never done; would require `v2.0.0`).
- Changing a §B machine-check threshold downward (e.g. lowering
  §B1.3 floor).
- Changing the freeze block's signing authority.
- Adding a new Part (beyond §11).

### §8.6 — Contribution SLAs (post-v1.0, Phase 7)

When external contributions open:

- **PR first review:** ≤ 5 business days from open.
- **PR final decision (merge / changes requested / rejected):**
  ≤ 14 business days from open.
- **Security disclosure (SECURITY.md):** per severity ladder, already
  binding.
- **Primitive / adapter acceptance rate:** no target; quality bar is
  §A-§B compliance full stop.

Until Phase 7 activates, this section is aspirational but binding
once the first external PR lands.

### §8.7 — Code of Conduct (Phase 7 activation)

When external contributions open, `/CODE_OF_CONDUCT.md` ships based on
the Contributor Covenant v2.1 (https://www.contributor-covenant.org/).
Placeholder here so the obligation is not forgotten:

- Enforcement contact: `conduct@humangr.com` (TBD — align with
  SECURITY.md disclosure channel if practical).
- Scope: every repo under `humangr-labs/`.
- Escalation: Gustavo has final authority on permanent bans.
- Transparency: enforcement actions logged in a private ledger; public
  summary in the first MAJOR release after any action.

Not binding pre-Phase-7, but MUST land in the commit that opens the
first external PR.

---

## Part 9 — Locked vocabularies

All identifier / name / taxonomy lists are LOCKED at v1.0.0.
Extensions require MINOR bump + same-commit update here.

### §9.1 — Namespaces (16)

Alphabetical, closed set:

```
api, auth, billing, cache, compliance, cost, data, events, extras,
flags, jobs, llm, obs, policy, resiliency, security
```

### §9.2 — Domains (10) — used in `fastapi_<domain>_<verb>_<noun>`

Canonical list in `engine/index/schemas.py#DOMAINS`:

```
api, auth, compliance, data, deployment, meta, observability,
realtime, resiliency, testing
```

### §9.3 — Verbs (9) — tool name slot `fastapi_<domain>_<verb>_<noun>`

Canonical tuple in `engine/index/schemas.py#VERBS` (order matches
source; list is a mirror — schemas.py wins):

```
add, generate, verify, operate, evolve, proactive, check, analyze, search
```

Not the same as `adapt/<verb>/` directory names (those categorize
tool files on disk: `extend/`, `verify/`, `operate/`, `evolve/`,
`contracts/`, `proactive/` — 6 categories). A single adapt-tool can
ship with a `verb` slot (§9.3) different from its `adapt/<category>/`
home.

### §9.4 — Tag vocabulary

Canonical frozenset in `engine/index/schemas.py#TAG_VOCABULARY`.
These are semantic tags (not tool categories) attached to each
`MCP_TOOL.tags` for searchability. Grouped by area:

```
identity + access:     oauth, jwt, rbac, mfa, session, password
data shape + patterns: crud, pagination, soft-delete, audit,
                       event-sourcing, idempotency, optimistic-lock,
                       outbox
api style:             graphql, rest, versioning, batch, cqrs,
                       deprecation
realtime:              websocket, sse, webhook, presence
resiliency:            rate-limit, bulkhead, circuit-breaker, retry,
                       graceful-shutdown, load-shedding,
                       causal-reorder
observability:         otel, prometheus, logging, tracing, metrics
compliance:            hash-chain, retention, consent, gdpr,
                       tamper-evident
infra / deployment:    docker, kubernetes, ci, compose, load-test
testing:               coverage, fuzz, property, soak, chaos
experimental / misc:   experimental, federated-identity, ml, workflow
```

Adding a tag = additive, MINOR bump + same-commit `TAG_VOCABULARY`
update.

**Don't confuse with tool-category tags.** Earlier drafts of this
table listed `extend`, `verify`, `operate`, `evolve`, `contracts`,
`proactive` as tags — those are `adapt/<verb>/` CATEGORIES, NOT
values of `TAG_VOCABULARY`. The two namespaces are disjoint.

### §9.5 — Primitive verdict taxonomy (promotion ledger)

Values produced by `engine.promotion.classify`:

| Verdict | Meaning | Action |
|---|---|---|
| `promote_as_adapter` | Framework-coupled, motor registered, adapter missing | Follow §7.B |
| `promote_as_primitive` | Framework-free, not yet registered | Follow §7.A |
| `promote_lite` | §B1.8-eligible tier-lite candidate | Follow §7.F |
| `extract_motor_pair` | Framework-coupled, motor not registered | Follow §7.G |
| `fill_and_promote` | Has REPLACE_ME markers; fill then promote | Custom per-item |
| `redundant` | Duplicate of registered primitive | `promote --delete` |
| `needs_caller` | No §A12(b) trigger yet | Follow §7.H |
| `needs_review` | Ambiguous; Opus-audit required | Manual |

### §9.6 — Ledger signal kinds

Values attached to ledger entries to justify verdicts:

```
generator_ref, framework_import, framework_token, duplicate_of_registered,
motor_exists, concurrency_present, mutable_state, staged_ambiguity,
benchmark_gap, tool_import
```

Full definitions in `engine/promotion/classify.py` docstring.

### §9.7 — Primitive shell file types (§4.1 reference)

```
<Name>.py               # motor
<Name>.md               # docs (≥3 compose_with)
__init__.py             # re-exports
conftest.py             # cache redirect
test_<Name>.py          # unit tests
behavioral_<Name>.py    # invariant witnesses

Optional (tier-full):
<Name>.contract.json    # external consumer spec
<Name>.manifest.json    # build manifest
<Name>.tla              # TLA+ concurrency model
<Name>.cfg              # TLA+ config
chaos_<Name>.py         # chaos scenarios
concurrent_<Name>.py    # concurrency tests
metamorphic_<Name>.py   # metamorphic property tests
state_machine_<Name>.py # explicit state-machine tests
observability_<Name>.py # log/metric emission tests
dashboard.json          # Grafana dashboard
invariant_bindings.json # invariant→test mapping
observability_schema.json
persona_reviews.json    # multi-role review artefact
proposed_invariants.json
```

### §9.8 — ToolResult status values

```
success   # tool ran, made changes
error     # tool failed; `error` field populated
no_op     # idempotent short-circuit; no changes made
```

### §9.9 — Primitive status values (catalog)

```
stable       # registered + production-ready
beta         # registered + feature-complete + needs hardening
deprecated   # registered + scheduled for removal in next MAJOR
experimental # registered + explicitly non-stable API
staged       # in `_extracted/` — discoverable, NOT production
quarantined  # in `_extracted/_quarantine/` — hidden from catalog
```

Only `stable` and `staged` are cited in v1.0 narrative docs. Other
values reserved for post-v1.0.

### §9.10 — Tier values

```
full  # registered primitive with complete shell (§9.7)
lite  # registered primitive with minimal shell (§B1.8 criteria)
none  # staged / quarantined (not registered)
```

---

## Part 10 — Glossary

**Core surface:**

- **Skill:** a framework-specific kit (e.g. SKILL-001-fastapi-production)
  that plugs into Maestro (consumer) and Forge (host editor). One
  `SKILL.md` + catalog + primitives + adapters + tools.
- **SkillKit:** the collection of skills + shared tooling at this repo.
- **Primitive (motor):** framework-free implementation under
  `core/venous/<ns>/<Name>/`. Protocol + reference backend + named
  invariants.
- **Adapter:** framework/provider-specific wiring under
  `core/venous/_adapters/<framework>/`. Thin glue; zero invariant logic.
- **Venous:** the HuGR term for the framework-free primitive layer
  (`core/venous/`). Named for how it carries domain concepts into any
  framework bloodstream. Originates from the biological analogy: the
  venous system feeds every organ without being specific to any one.
- **Concern:** the top-level domain grouping used in
  `engine/primitives_by_concern.yaml` — synonym for namespace in most
  contexts. Every primitive entry carries a `concern:` field matching
  its namespace.
- **Slice:** one feature's worth of code added by a single extend
  tool (e.g. an `auth` slice = models + schemas + CRUD + routes +
  migration for authentication). Extend tools produce slices;
  generators produce entire subsystems.

**Tools:**

- **Adapt tool:** lives under `adapt/<verb>/<bucket>/<name>.py`. Verbs:
  `extend` (add a slice), `verify` (validate), `operate` (run-state
  actions), `evolve` (idempotent migrations), `contracts` (shared
  helpers, no MCP), `proactive` (suggestions).
- **Extend tool (slice):** `adapt/extend/*` that adds one feature
  slice (auth, payments, caching, …) to an existing project.
- **Generator:** `generators/<category>/<name>.py` — stateless
  scaffolder (emits files from templates). Unlike extend tools,
  generators scaffold whole subsystems, not slices.
- **Module (package):** `modules/<category>/<name>/` — pre-built
  feature bundle orchestrating multiple tools.
- **Tier-1 meta tool:** one of the seven always-loaded Maestro tools
  (`fastapi_meta_home/search/describe/scaffold/compose/audit/verify`);
  operates ON the catalog, not IN it.
- **Tree dispatcher:** one of nine domain-scoped tools
  (`fastapi_auth/data/api/realtime/resiliency/observability/compliance/deployment/testing`);
  surfaces a menu of scope-relevant tools.
- **Rails-connected tool:** an `adapt/extend/*` tool whose `MCP_TOOL`
  declares `imports_primitives` + `imports_adapters` AND whose emitted
  code actually imports those.

**Data shapes:**

- **`MCP_TOOL`:** module-level dict on every tool file; auto-discovered
  by `engine.index.manifest`. Keys: `name`, `description`, `tags`,
  `entry`, `imports_primitives`, `imports_adapters`.
- **`ToolInput`:** Pydantic model; every extend/verify/operate/evolve
  tool's input argument. Min shape: `project_dir: str`, `dry_run: bool`.
- **`ToolResult`:** Pydantic model; every tool's return value. Shape
  in §2.8.
- **Delivery contract:** the `ToolResult` Pydantic schema that every
  tool output conforms to (`adapt/contracts/delivery_contract.py`).
- **Catalog:** `engine/index/catalog.json` — machine-generated
  manifest of every registered tool + primitive + recipe.
- **Manifest:** either the catalog itself, OR the per-project
  `.venous_manifest.json` (copied adapters + primitives tracker).
- **Recipe:** a `## Compose with:` entry parsed from a primitive's
  `<Name>.md`; surfaces in `fastapi_meta_search_composition`.
- **Fingerprint:** a string a tool looks for in the target file to
  detect "already installed" state (idempotency anchor per §A4).
- **Prerequisite:** a `Prereq.*` enum value passed to
  `ensure_prerequisites()`; documents what the tool needs the project
  to already have. Canonical enum in
  `adapt/contracts/prerequisites.py#Prereq`. Values include
  `BASE_MODEL`, `MODELS_INIT`, `CONFIG_SETTINGS`, `ROUTES_INIT`,
  `ALEMBIC_VERSIONS`, `REQUIREMENTS_TXT`, and so on. Every tool
  declares its prereqs explicitly; `ensure_prerequisites` returns
  the list of failures so the tool can stop before any write.
- **`manifest build` vs `manifest verify`:** the build command
  (`engine.index.manifest build`) regenerates `catalog.json` from disk
  — writes the file + computes a fresh `stable_hash`. The verify
  command (`engine.index.manifest verify`) runs build TWICE and
  asserts the hashes are identical, catching non-determinism in the
  scan order or content. CI runs `verify`; developers run `build` to
  update after adding a primitive/tool.

**Pool + promotion:**

- **Staged primitive:** `_extracted/<ns>/<Name>/` — discoverable via
  `status="staged"` but not production-ready.
- **Quarantined primitive:** `_extracted/_quarantine/<Name>/` — rejected
  by extraction gate; not surfaced in catalog.
- **Ledger entry:** row in `engine/promotion/ledger.json` with verdict
  (see §11.5). Rendered human-readably in `engine/promotion/LEDGER.md`.
- **Verdict:** the classifier's decision per ledger entry (§9.5).
- **Signal:** evidence backing a verdict (§9.6).
- **Blocker:** a reason an otherwise-promotable entry can't land
  automatically (e.g. ambiguous naming requires `--staged`/`--quarantined`).
- **Wave:** post-v1.0 work batch. Waves 1-1.5 landed pre-freeze; Waves
  2-4 are deferred per §6.

**Invariants + contracts:**

- **Invariant (domain):** named per-primitive guarantee with ID
  (e.g. `PS_INV_01`, `BILL_INV_03`). Every invariant has a
  witness test.
- **Invariant (process):** a CONTRACT §A or §B rule.
- **Witness test:** a `test_inv_NN_*` function in `behavioral_<Name>.py`
  that fails iff the named invariant is violated.
- **CONTRACT §A:** the 12 inviolable rules — never changed silently.
- **CONTRACT §B:** the machine-checked phase-ordered execution checklist.
- **CONTRACT §C:** enforcement — PR discipline, quarterly ratification,
  machine-check-every-commit.
- **CONTRACT §D:** explicit non-promises.
- **CONTRACT §E:** amendment log.

**Release + ops:**

- **Ship gate:** §5 checklist — what runs before we tag a release.
- **Stable hash:** SHA-256 of the deterministic catalog.json content;
  pinned in CHANGELOG for session consistency.
- **Triplet sync (§B4.6):** repo-root `VERSION` == skill-dir `VERSION` ==
  `STATUS.md` frontmatter version.
- **Hotfix (§2a of POST_RELEASE):** PATCH bump cut from a release tag,
  not from `main`.
- **Yank (§2b of POST_RELEASE):** release marked "do not install" with
  banner; tag never deleted.

**Meta:**

- **Drift:** any divergence between this doc, CONTRACT.md, INVENTORY.md,
  or actual code. Caught by §B4.7 machine-check AND §8.3 detective
  process.
- **Ratification:** Gustavo-signed block in §11 (or CONTRACT.md §E)
  that makes an amendment binding.
- **Phase:** a coarse time-ordered band of work (Phase 0-7). Different
  from a Wave (§6) which is a post-v1.0 batch of work within Phase 5/6/7.
- **ADR:** Architecture Decision Record at `docs/decisions/NNNN-*.md`.

---

## Part 11 — Freeze block

This document is **PROPOSED** until signed below.

Until the sign-off line below is filled with a real date, this
document is a proposal and no freeze action is binding. After
ratification, all amendments follow §8.5.

### Ratified YYYY-MM-DD by Gustavo

- [ ] ROADMAP consolidation ratified per §1-§10.
- [ ] Invariants (§2) locked — changes require a new dated
      ratification block in this section.
- [ ] Quality standards (§3) locked — semver, dependency, CI/CD,
      perf SLOs, security, license, observability policies all binding.
- [ ] Definitions of Done (§4) locked — 9 surface DoDs enforceable
      at PR-review time.
- [ ] Ship gate (§5) locked — 45 items across §5.1-§5.7 + §5.8
      rollback tree + §5.9 stable-call protocol.
- [ ] Post-v1.0 waves (§6) ratified IN ORDER; Wave 2 starts after
      `v1.0.0` tag. Numeric exit criteria per wave are binding.
- [ ] Operational checklists (§7) locked — amendments via new dated
      line in amendment log below.
- [ ] Governance + risks + drift (§8) accepted. R1-R12 risk table is
      authoritative until re-ratified.
- [ ] Locked vocabularies (§9) frozen — extension requires MINOR bump
      + same-commit §9 update.
- [ ] Glossary (§10) accepted.
- [ ] §A12 amendment + §B1.7 + §B1.8 formally ratified here as well
      (mirrors CONTRACT.md §E).

**How to sign.** Replace `YYYY-MM-DD` above with today's ISO date.
Then tick each `[ ]` to `[x]` only for blocks you have personally
re-read in the current sitting. Partial signing is allowed: an
honestly unchecked `[ ]` is worth more than a performatively ticked
`[x]` you didn't actually review. The sign-off counts as complete
when every checkbox is `[x]`.

**Semantics after ratification.** Once this block is dated + signed,
the checkboxes stop representing to-dos and start representing a
permanent audit trail ("I, Gustavo, confirmed §N on this date").
Future amendments do NOT uncheck these boxes; they append a new
dated block to the amendment log below.

### Amendment log

Append one block per amendment to this doc post-ratification. Format
per §8.5:

```
### Amendment YYYY-MM-DD by Gustavo
- <change summary>
- <rationale>
```

(no amendments yet — doc is still proposal)
