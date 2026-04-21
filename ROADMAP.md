# ROADMAP — HuGR SkillKit

> **Status:** PROPOSED (awaits ratification — see §9).
> **Post-ratification, this document is read-only.** Amendments require a
> new dated ratification line at the bottom of §9.
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

| If you are… | Read |
|---|---|
| First-time contributor | §1 (state) → §2 (invariants) → §3 (quality) → Checklists §7.A or §7.D |
| Release engineer cutting v1.0 | §5 (ship gate) → `/GOLIVE.md` (commands) → Checklist §7.I |
| Wave-2/3/4 worker | §6 (waves) → Checklist §7.F / §7.G / §7.H |
| Auditor / reviewer | §2 (invariants) → §4 (DoDs) → `engine.audit.contract_check` output |
| Future-us debugging drift | §1 (state) vs. INVENTORY.md + `engine.inventory` |

Counts cited here reconcile against `skills/SKILL-001-fastapi-production/INVENTORY.md`.
Drift between this doc and INVENTORY = audit bug (caught by CONTRACT §B4.7).

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
| Recipes | 393 | Parsed from primitive `.md` `## Compose with:` sections |
| Benchmark specs | 20 | 5 baseline / 10 mid / 5 adversarial |
| Ledger entries | 219 | Post-Wave-1.5 triage state |
| Contract rules passing | 36/36 | Machine-verified by `engine.audit.contract_check` |
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
- **Wave 2 / 3 / 4** — post-v1.0 deferrals per §6.

---

## Part 2 — Invariants (inviolable across every phase)

An invariant is a statement that MUST be true for any valid commit on
`main`. A commit that violates an invariant is rejected (machine-checked
where possible; reviewer-enforced where not).

### §2.1 — CONTRACT §A — inviolables (12 rules)

Full text in `skills/SKILL-001-fastapi-production/CONTRACT.md §A`. Named summary:

| ID | Summary |
|---|---|
| §A1 | Every primitive ships a framework-free motor. Framework glue is in an adapter. |
| §A2 | Every Maestro-facing tool has `MCP_TOOL` metadata + tests + behavioural test. |
| §A3 | Tool names follow `fastapi_<domain>_<verb>_<noun>` (closed vocab: 10 domains × 9 verbs). |
| §A4 | Every primitive namespace is locked (api, auth, billing, cache, compliance, cost, data, events, extras, flags, jobs, llm, obs, policy, resiliency, security). |
| §A5 | Every primitive `.md` has ≥3 `## Compose with:` bullets. |
| §A6 | No hardcoded `@mcp_app.tool` decorators — auto-discovery only. |
| §A7 | Lazy imports for optional SDKs (stripe, redis, celery, boto3, …). |
| §A8 | INVENTORY.md is canonical; narrative docs reconcile against it. |
| §A9 | `primitives_used` in `MCP_TOOL` reflects real imports (AST-verified). |
| §A10 | Semver 2.0.0 commitment from v1.0.0 onwards. |
| §A11 | No manual counts in CLAUDE.md / STATUS.md / ROADMAP.md / CHANGELOG.md — all reconcile against INVENTORY. |
| §A12 | Pool discipline — `_extracted/` items promote ONLY when a benchmark gap OR registered-tool import OR ratified triage pass demands it. |

### §2.2 — CONTRACT §B — machine-checked gates (36 rules)

Full list at `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check`.
Key gates:

| ID | What it guards |
|---|---|
| §B1.0 | `core.venous` copy-in distribution works (scaffold a project, import a primitive). |
| §B1.0.1 | Adapter layer + framework-free primitives (ADR-0003). |
| §B1.1 | Registry synced with disk; no half-extracted dirs. |
| §B1.2 | Every primitive `.md` has `## Compose with:` with ≥3 bullets. |
| §B1.3 | ≥ 22 extend `add_*` tools import a registered primitive (Rails-style). |
| §B1.5 | No hardcoded `@mcp_app.tool` decorators. |
| §B1.6 | No orphan generators (`generate_*` is either MCP_TOOL or internal helper). |
| §B1.7 | Every FastAPI adapter has `test_<Name>Adapter.py` + maps to a registered primitive. Floor ≥ 15. |
| §B1.8 | Tier-lite eligibility (stateless, framework-free, no REPLACE_ME). |
| §B2.1 | `fastapi_meta_search_primitive` quality gate (BM25 top-1 ≥ 80%). |
| §B2.2 | `fastapi_meta_search_composition` quality gate (BM25 top-1 ≥ 70%). |
| §B2.3 | Docs site build is idempotent (same inputs → same hash). |
| §B2.4 | Catalog manifest synced + deterministic (`stable_hash` idempotent across two builds). |
| §B2.5 | SKILL.md v2 Anthropic Agent Skills format. |
| §B3.1 | 20 benchmark specs (5 baseline / 10 mid / 5 adversarial). |
| §B3.5 | Plan-level benchmark ≥ 90 on 20/20 specs. |
| §B3.6 | Code-level benchmark ≥ 70 on ≥ 25% covered specs. |
| §B4.1 | `install.sh` + fresh-Docker CI green. |
| §B4.2 | `/examples/` has ≥ 5 populated (README + MAESTRO_SESSION + cross-link). |
| §B4.3 | Docs site v1 (top-level + per-tool pages). |
| §B4.4 | CHANGELOG + VERSION semver cite benchmark score. |
| §B4.6 | VERSION triplet sync (repo-root + skill + STATUS.md frontmatter). |
| §B4.7 | Canonical counts in INVENTORY reconcile against CLAUDE/STATUS/ROADMAP/CHANGELOG. |

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

### §2.4 — Namespace canonicity

- 16 closed namespaces (alphabetical):
  `api, auth, billing, cache, compliance, cost, data, events, extras,
  flags, jobs, llm, obs, policy, resiliency, security`.
- Adding a new namespace = additive schema change, allowed, but must
  update:
  - `engine/primitives_by_concern.yaml` (a primitive entry exists).
  - `engine/index/schemas.py#DOMAINS` (if Maestro-facing tools need it).
  - This doc's §2.4 list.
- Removing a namespace = MAJOR semver bump (v2.0.0+).

### §2.5 — Per-primitive invariants (domain-specific)

Every registered primitive declares its invariants in its `<Name>.py`
module docstring with named IDs. Behavioural tests name the invariant
they witness in the test function name (`test_inv_NN_*`).

Examples at v1.0:

- **Bulkhead (BH_INV_01..05):** capacity ceiling, wait-deadline,
  anti-retry ledger, partition isolation, rejection metering.
- **TopicBus (TB_INV_01..05):** at-least-once delivery, per-key
  exclusive dispatch, nack-never-drops, partition-local ordering,
  durable append before fanout.
- **PubSub (PS_INV_01..05):** fanout correctness, per-subscriber
  ordering, topic isolation, subscriber cleanup, active-window delivery.
- **Billing (BILL_INV_01..05):** HMAC webhook verification mandatory,
  lifecycle monotonicity, plan-change id preservation, opaque-id
  checking, no-PII errors.

**Invariant acceptance test (§4.1):** every new primitive MUST ship ≥3
named invariants with ≥1 behavioural test each.

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

### §2.9 — Commit hygiene

- Every commit leaves the tree CONTRACT 36/36 green.
- Pre-commit hook (`.githooks/pre-commit`) runs `engine.audit.contract_check`.
- Commit messages: imperative mood, ≤70-char subject, body explains
  WHY not WHAT.
- Co-authored-by Claude Opus 4.7 (1M context) when AI-assisted.
- Never `--no-verify`. Never `--amend` a pushed commit.

---

## Part 3 — Quality standards

### §3.1 — Code style

- **Python target:** 3.11+ (3.11 / 3.12 / 3.13 supported per `pyproject.toml`).
- **Formatting:** ruff + black (configured in `pyproject.toml`).
- **Type hints:** required on all public surface; `mypy --strict` clean.
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
- [ ] `engine.audit.contract_check` 36/36 green.

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

- [ ] Stateless scaffolder — emits files from templates.
- [ ] `MCP_TOOL` metadata same as §4.4.
- [ ] `test_<name>.py` — runs the generator, asserts emitted files AST-parse.

### §4.7 — Module package DoD

Location: `modules/<category>/<name>/`

- [ ] Pre-built feature bundle — multiple tools orchestrated.
- [ ] README describes composition.
- [ ] Integration test asserts all child tools run clean.

### §4.8 — Example app DoD

Location: `/examples/<NN>-<name>/` (repo-root, NOT skill-internal)

- [ ] `README.md` — purpose + maestro prompt summary + file tree.
- [ ] `MAESTRO_SESSION.md` — the actual prompt + the actual response transcript.
- [ ] `app/` — working FastAPI project.
- [ ] `tests/` — pytest suite; `pytest -q` passes.
- [ ] Cross-link table: which primitives + adapters + tools this example
      exercises.
- [ ] Listed in `/examples/README.md` index.

### §4.9 — Benchmark spec DoD

Location: `benchmarks/specs/SPEC-<NNN>-<slug>.md`

- [ ] 4 required sections: Scenario, Requirements, Expected primitives,
      Expected tools.
- [ ] Category marker in filename: `baseline` / `mid` / `adversarial`.
- [ ] Exists in both plan-level and code-level rubrics.
- [ ] Code-level: has a matching fixture app + pytest suite under
      `benchmarks/code_level/<NNN>/` that scores the tool-generated output.

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
- [ ] This ROADMAP.md §9 signed (see §9 below).

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
- [ ] Install-Docker workflow green ≥3 consecutive nights pre-freeze.

### §5.4 — Benchmark gate (Claude) — 5 items

- [ ] Plan-level benchmark ≥ 70 (current 100.00).
- [ ] Code-level benchmark ≥ 70 on 20/20 covered specs (current 100.00).
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
- [ ] SKILL.md v2 no stale counts (`engine.audit.skillmd_counts` exits 0).
- [ ] CONTRACT.md §E updated per §5.1 bullet 3.
- [ ] This ROADMAP.md post-v1.0 state reflected (Phase 5 ✅, waves scheduled).

### §5.6 — Tag + push + release (Gustavo-side) — 3 items

- [ ] Signed tag `v1.0.0` using `GOLIVE.md §6.1a` template.
- [ ] Push `main` + tag.
- [ ] GitHub release draft with body pointing to CHANGELOG [1.0.0].

### §5.7 — 72h post-release monitoring — 2 items

- [ ] Install.sh validated on release tag nightly for 48h.
- [ ] POST_RELEASE.md §1 audit commands pass every morning for 72h.

**Ship gate total: 5 + 3 + 15 + 5 + 8 + 3 + 2 = 41 items.**

---

## Part 6 — Post-v1.0 waves (ordered)

Ordered by dependency + risk. Earlier wave reduces surface before later
wave adds to it.

### §6.1 — Wave 2 — Tier-lite middleware (pool harvest)

- **Goal:** register ~40-60 stateless HTTP middleware from `_extracted/`
  as tier-lite primitives (new tier per §B1.8).
- **Candidates (initial sample):** `RequestId`, `Deprecation`, `CORS`,
  `JsonError`, `RequestSigning`, `Sanitize`, `SchemaEnforcer`.
- **Criteria (§B1.8):** stateless, framework-free, no REPLACE_ME
  markers, ≤30 LOC motor body.
- **Skeleton per primitive:**
  - `<Name>.py` (lite-tier: motor only, no invariant_bindings / dashboard).
  - `<Name>.md` with ≥3 `## Compose with:` bullets.
  - `test_<Name>.py` with ≥3 behavioural tests.
  - Entry in `primitives_by_concern.yaml` with `tier: "lite"`.
  - Optional `<Name>Adapter.py` under `_adapters/fastapi/`.
- **Exit criteria:**
  - `engine.audit.contract_check` §B1.8 reports ≥ 40 lite primitives.
  - Staged count drops proportionally; ledger regenerated.
- **Esforço:** 3-5h (batch-promote 20/week).
- **Checklist:** §7.F.

### §6.2 — Wave 3 — EXTRACT_MOTOR_PAIR (~118 items)

- **Goal:** split each framework-coupled staged primitive into
  (framework-free motor + FastAPI adapter), mirroring the Bulkhead /
  PubSub / Billing templates.
- **Classifier:** `engine.promotion.classify` already labels them
  `extract_motor_pair`.
- **Per-item work:**
  1. Read the inline coupling in the staged `<Name>.py`.
  2. Write motor `core/venous/<ns>/<Motor>/Motor.py` + shell (§4.1).
  3. Write adapter `core/venous/_adapters/fastapi/<Motor>Adapter.py` (§4.2).
  4. Write ≥3 behavioural tests per invariant (§3.4).
  5. Rails-connect the caller tool (§7.D).
  6. Delete the staged source + quarantined twin (§A12 pool discipline).
  7. Regenerate LEDGER + catalog.
- **Esforço:** ~2-4h per item × 118 = 1-2 weeks full-time (feasible as
  per-commit work over a quarter).
- **Checklist:** §7.G.

### §6.3 — Wave 4 — NEEDS_CALLER triage (~101 items)

- **Goal:** for each staged primitive with no §A12(b) trigger, either
  (a) wire it into a new/existing tool (promote), or (b) mark redundant +
  delete.
- **Classifier:** `engine.promotion.classify` labels them `needs_caller`.
- **Per-item decision tree:**
  1. Does any `adapt/extend/*` tool currently inline this logic? If
     YES → Wave-3 motor-pair extract instead.
  2. Does a benchmark spec exercise the domain? If YES → write the
     missing tool that imports this primitive (tool-signal = §A12
     trigger satisfied).
  3. Is it a clean duplicate of a registered primitive? If YES →
     delete as REDUNDANT.
  4. Else → write a STAGING.md one-liner explaining why it's still
     staged (process item from old ROADMAP §30).
- **Esforço:** 1-2 days wall-clock (decision per item is ~5 min).
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
        — 36/36 green.
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
10. [ ] Contract check 36/36 green.
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
10. [ ] Contract check 36/36 green; §B1.3 count goes up by 1.
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
8. [ ] Contract check 36/36 green.
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
3. [ ] Run §5.1-§5.5 checklists (all 31 items) green.
4. [ ] `cat VERSION` == target version (e.g. `1.0.0`).
5. [ ] `jq -r .stable_hash engine/index/catalog.json` cited in CHANGELOG.
6. [ ] CHANGELOG block header has real date (not `YYYY-MM-DD`).
7. [ ] `PYTHONPATH=. .venv/bin/python -m engine.index.manifest verify`
       exits 0 (idempotent stable_hash).
8. [ ] `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check`
       36/36 green.
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

## Part 8 — Glossary

- **Primitive (motor):** framework-free implementation under
  `core/venous/<ns>/<Name>/`. Protocol + reference backend + named
  invariants.
- **Adapter:** framework/provider-specific wiring under
  `core/venous/_adapters/<framework>/`. Thin glue; zero invariant logic.
- **Rails-connected tool:** an `adapt/extend/*` tool whose `MCP_TOOL`
  declares `imports_primitives` + `imports_adapters` AND whose emitted
  code actually imports those.
- **Tier-full:** registered primitive with the complete shell
  (contract.json + TLA+ + dashboard + …).
- **Tier-lite:** registered primitive with a minimal shell (§B1.8) —
  stateless, framework-free, no REPLACE_ME.
- **Staged primitive:** `_extracted/<ns>/<Name>/` — discoverable via
  `status="staged"` but not production-ready.
- **Quarantined primitive:** `_extracted/_quarantine/<Name>/` — rejected
  by extraction gate; not surfaced in catalog.
- **Ledger entry:** row in `engine/promotion/ledger.json` with verdict
  (`promote_as_adapter` / `promote_as_primitive` / `extract_motor_pair`
  / `fill_and_promote` / `redundant` / `needs_caller` / `needs_review`).
- **Wave:** post-v1.0 work batch. Waves 1-1.5 landed pre-freeze; Waves
  2-4 are deferred per §6.
- **Invariant (domain):** named per-primitive guarantee with ID
  (e.g. `PS_INV_01`, `BILL_INV_03`). Every invariant has a
  witness test.
- **Invariant (process):** a CONTRACT §A or §B rule.
- **Ship gate:** §5 checklist — what runs before we tag.
- **Stable hash:** SHA-256 of the deterministic catalog.json content;
  pinned in CHANGELOG for session consistency.

---

## Part 9 — Freeze block

```
This document is PROPOSED until signed below.

### Ratified YYYY-MM-DD by Gustavo
- ROADMAP consolidation ratified per §1-§8.
- Invariants (§2) locked; any change requires new dated ratification.
- Quality standards (§3) locked.
- Definitions of Done (§4) locked.
- Ship gate (§5) locked — no new items without ratification.
- Post-v1.0 waves (§6) ratified in ORDER; Wave 2 starts after v1.0 tag.
- Operational checklists (§7) locked — amendments via new dated line below.
- §A12 amendment + §B1.7 + §B1.8 formally ratified here as well
  (mirrors CONTRACT.md §E).

Amendment log (add new dated line per amendment):
(none yet)
```

Until the sign-off block above is filled with a real date, this
document is a **proposal** and no freeze action is binding.
