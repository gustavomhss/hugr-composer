# Changelog

All notable changes to HuGR SkillKit are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every release cites its benchmark score, primitive count, and tool count
so a reader can tell — in one glance — whether to upgrade.

---

## [1.0.0] — YYYY-MM-DD (template — fill in YYYY-MM-DD at freeze commit)

> **This block is release-ready** except the `YYYY-MM-DD` placeholder
> which Gustavo fills on the freeze day. Every count below is
> machine-verified (2026-04-21 audit) and `stable_hash` is the literal
> hash at HEAD. Re-verify with `engine.inventory` + `jq -r .stable_hash
> engine/index/catalog.json` before tagging.

### Summary

First stable release. Skill surface frozen; MAJOR bumps required for
tool / primitive renames going forward (CONTRACT §A10).

### Highlights

- **Plan-level benchmark:** 100.00 (methodology `plan_level_v3_best_of_ensemble`).
- **Code-level benchmark:** 100.00 on 20/20 specs.
- **217 Maestro-facing tools** total:
    - 201 catalog tools (`engine/index/catalog.json`)
    - 7 tier-1 meta tools (`mcp_tools/tier1.py` + `mcp_tools/compose.py`)
    - 9 tree dispatchers (`mcp_tools/tree/`)
- **122 registered primitives** (full shell: contract + protocol + tests +
  TLA+ + dashboard + invariants + observability).
- **17 FastAPI adapters** (`core/venous/_adapters/fastapi/`). The 17th,
  `BulkheadAdapter`, landed in the Wave-1 pre-freeze sprint (see
  FREEZE §1.6) along with motor extension `InMemoryBulkhead.acquire()`.
- **179 staged primitives** (`_extracted/`, `status="staged"`) — discoverable,
  not promoted.
- **20 complete examples** at `/examples/` (5 baseline + 10 mid + 5 adversarial).
- **36/36 CONTRACT rules green.** (34 pre-freeze + §B4.6 VERSION
  triplet sync + §B4.7 canonical counts sync, both added as
  drift-guard rules during the pre-freeze rigor audit.)
- **Catalog `stable_hash`: `50338fa37aa2...`** (full 64-char value in
  `engine/index/catalog.json`) — consumers pin this for session
  reproducibility. Verify with `jq -r .stable_hash
  skills/SKILL-001-fastapi-production/engine/index/catalog.json`.

### Added

- **Tier-lite (§B1.8)** — new registered tier for stateless primitives;
  no TLA+ required. Machine-checked by `_r_tier_lite_eligibility`.
  Vacuously green at v1.0 (0 lite primitives registered).
- **Promotion pipeline** — `engine/promotion/`: classifier, ledger,
  atomic executor with rollback, ambiguity-safe CLI
  (`--staged` / `--quarantined`). 38 unit tests.
- **Catalog `stable_hash`** now embedded in `engine/index/catalog.json`
  (was stdout-only in v0.x).
- **`LICENSE`** — proprietary (HumanGR Labs).
- **`SECURITY.md`** — disclosure policy + SLA tiers.
- **`MIGRATION.md`** — v0.x → v1.0 breaking changes.
- **`FREEZE.md` / `GOLIVE.md` / `INTERFACES.md`** — release triad.
- **`pyproject.toml`** in the skill dir for tooling compatibility
  (install path remains `install.sh` + `requirements-mcp.txt`).
- **`.githooks/pre-commit`** — canonical pre-commit gate running
  contract + promotion tests (install with `git config core.hooksPath .githooks`).
- **ADR 0001** — retroactive record of SKILL-001 scope + FastAPI choice.
- **`POST_RELEASE.md`** — rollback runbook + first-72h monitoring.

### Changed

- **§A12** amended to recognise a ratified triage-pass as a valid
  promotion trigger (beside benchmark gap + registered-tool import).
  See `/docs/decisions/0004-tier-lite.md` §3.
- **Ledger verdicts** renamed from delete-heavy to action-focused:
  PROMOTE_AS_ADAPTER / PROMOTE_AS_PRIMITIVE / EXTRACT_MOTOR_PAIR /
  FILL_AND_PROMOTE / REDUNDANT / NEEDS_CALLER / NEEDS_REVIEW.
- **Contract count** 33 → 36. Added: §B1.7 (FastAPI adapter coverage
  formally defined in CONTRACT — rule was already implemented pre-v1.0
  but not spec'd), §B1.8 (tier-lite eligibility), §B4.6 (VERSION
  triplet sync), §B4.7 (canonical counts sync). §B4.6 and §B4.7
  were added during the pre-freeze rigor audit after Gustavo's
  demand for brutal transparency.

### Security

- No advisories at release. Disclosure channel live per `SECURITY.md`.

### Migration notes

See `MIGRATION.md`. Short version: rename any legacy tool calls to the
canonical `fastapi_<domain>_<verb>_<noun>` form; update primitive
imports to include the adapter when framework glue is needed;
check staged primitives via `status="staged"` filter.

### Known issues

- **2 pre-existing bulkhead API divergence tests** fail in
  `test_add_bulkhead_isolation_behavior.py` (B-02 and B-04). Root
  cause: test assumes a `Bulkhead(BulkheadConfig)` constructor that
  predates the current `InMemoryBulkhead(name, *, max_concurrent_calls,
  max_wait_duration_ms)` API. Not caused by v1.0 work; will be fixed
  alongside the deferred `BulkheadAdapter.py` promotion sprint.
  Documented in `FREEZE.md §2.8`.

All other v1.0 gates green. Post-v1.0 items tracked in
`FREEZE.md §2` (explicitly deferred) and `ROADMAP.md` (phase plan).

### Breaking changes

Tool and primitive names are frozen at this release. Future MAJOR
bumps (v2.0+) may rename or remove; v1.x will only add.

---

## [1.0.0 pre-release sprint log] — archived 2026-04-21

> This block is the engineering narrative for the three sprints that
> fed into [1.0.0]. Each intermediate claim below (contract counts,
> verdict names, staged totals) was accurate **at the moment of that
> sprint's commit**. The consolidated final state — 36/36 contract,
> action-focused verdict taxonomy, 179 staged + 45 quarantined, 17
> FastAPI adapters — is canonical in the [1.0.0] block above.
> Intermediate discrepancies are preserved for audit provenance, not
> for consumption by release readers.

Three parallel tracks contributed to v1.0.0:

### Track B — Promotion pipeline for the staged pool (2026-04-21 overnight)

Tooling to triage and selectively promote the 315 staged+quarantined
primitives in `core/venous/_extracted/` without silently amending §A12
(the inviolable rule: promote only when benchmark gap demands).

**Ships:**

- **`docs/decisions/0004-tier-lite.md`** — formal proposal for a
  second registered tier ("lite") that skips the `.tla` specification
  for stateless primitives where TLA+ adds zero verification value
  (pure middleware, value objects, format validators). Includes the
  §A12 amendment text recognising a ratified triage-pass as §A12(c).
  Status: awaiting Gustavo ratification.
- **`engine/promotion/`** module (7 files + 23 unit tests):
  - `schemas.py` — Pydantic contracts for Verdict / Signal / StateFlags /
    LedgerEntry / Ledger; self-validating, round-trip safe.
  - `state.py` — deterministic file-based inspection: REPLACE_ME count,
    TLA+ presence, concurrency detection (AST walk), mutable state
    detection (AST walk), framework-coupling detection (explicit imports
    + implicit tokens like `Mapped[`, `APIRouter(`, etc.), duplicate-of-
    registered detection.
  - `signals.py` — §A12(b) signal detection: scans catalog.json for
    `primitives_used` matches, walks source trees for `from core.venous`
    imports, reads benchmark specs for name mentions.
  - `classify.py` — 8-rule decision tree, first-match-wins:
    duplicate → DELETE; framework-coupled → KEEP_STAGED(re-extract);
    quarantined → KEEP_STAGED; no signal → KEEP_STAGED; signal + stub
    shell → NEEDS_REVIEW; signal + concurrent → PROMOTE_FULL; signal
    + lite-eligible → PROMOTE_LITE; fallthrough → NEEDS_REVIEW.
    *Taxonomy redesigned before v1.0 cut — see [1.0.0] §Changed for
    the action-focused verdicts (PROMOTE_AS_ADAPTER /
    PROMOTE_AS_PRIMITIVE / EXTRACT_MOTOR_PAIR / FILL_AND_PROMOTE /
    REDUNDANT / NEEDS_CALLER / NEEDS_REVIEW) that shipped.*
  - `promote.py` — atomic executor with automatic rollback. Refuses
    non-ready entries and §B1.7-unratified lite promotions. Rebuilds
    catalog + runs contract gate per promotion; any failure triggers
    snapshot restore. Dry-run verified against refusal paths.
  - `ledger.py` — `ledger.json` → `LEDGER.md` (242 entries, 1751 lines)
    with approve/reject checkboxes and copy-paste run commands.
  - `tests/` — 23 unit tests covering schema validation, state
    inspection AST walkers (threading/asyncio/mutable detection),
    each of the 8 classifier rules, and the weak-signal negative case.
- **`engine/promotion/HANDOFF.md`** — overnight summary for the
  ratifying session: current ledger split (13 DELETE / 229 KEEP_STAGED /
  0 PROMOTE_*), what to do in the morning, and the honest finding that
  zero primitives are currently promotable without either re-extraction
  or new benchmark signals.

**Discipline:**

- Zero primitives promoted. Tree clean at handoff.
- Contract 33/33 green across every commit in the track.
- No §A12 amendment merged — only a proposal doc awaiting signature.

### Track A — Catalog wiring + Rails-connection discipline (2026-04-21 sprint)

Surfaced + enforced the library the Maestro is supposed to consume. Every
machine-verified, every commit lands `33/33 ALL GREEN`.

**Ships (Maestro-facing surface):**

- **Canonical naming enforcement** — `fastapi_<domain>_<verb>_<noun>` with
  closed vocabularies (10 domains × 9 verbs). Manifest canonicalizer
  trusts author-declared names when they match the scheme; infers only
  for legacy. Fixed a regression where 173 catalog tools had
  double-prefix names (`fastapi_api_add_api_add_api_deprecation` — every
  `add_*` tool was affected, breaking BM25 search and adapter lookup).
- **+28 catalog tools** (173 → 201) — recovered meta/audit_tool,
  core/tools/{check_health,check_headers,analyze_project_v2},
  generators/testing/test_suite, adapt/verify/test_coverage_gaps, and
  20 module-level tools (modules/{auth,background_jobs,caching,
  database,deployment,observability,payments,security,websockets}/tools/)
  that were registered at the MCP layer but invisible to the catalog.
  All now carry canonical `MCP_TOOL` dicts.
- **180 staged primitives surfaced** (`status="staged"`) — the
  `core/venous/_extracted/` HuGR-shelled pool (PascalCase-filtered,
  deduped vs the registered 122) is now discoverable via
  `fastapi_meta_search`. Opt-in promotion via the extraction pipeline
  stays Phase-5 work; surfacing them is benchmark-gap-driven.
- **`fastapi_meta_compose` 4-tier fallthrough** — new `tool_delegate`
  tier between adapter_reuse and recipe_template. If an indexed tool
  already emits the caller's exact primitive set, compose points at
  that tool (zero files written, `mode_quality=HIGH`) instead of
  duplicating its output. Example: `{AuditEvent, TamperEvidentAuditLog}`
  now delegates to `fastapi_data_add_audit_log`.
- **`primitives_used` authoritative detection** — manifest precedence
  is now (0) explicit `MCP_TOOL.imports_primitives` declaration,
  (1) real AST imports, (2) `(from|import) core.venous.*` inside
  non-docstring string constants only. Docstring mentions no longer
  create false positives; the signal now matches Rails-style wiring
  reality.
- **3 extend refactors Rails-connected** — `add_bulkhead_isolation`,
  `add_adaptive_timeouts`, `add_outbox_pattern` now copy-in the
  matching primitive (Bulkhead / TimeoutBudget / TransactionalOutbox)
  and emit ≤20-line glue. All three primitive APIs used are
  pre-existing (no invention). Bumps §B1.3 connected count from 18 →
  19/100 extend `add_*` tools.
- **`fastapi_auth` dispatcher bug fixed** — bundle action was returning
  0/8 installed because `_call_slice` passed raw `output_dir` kwarg
  where the adapt slices expect `ToolInput(project_dir=...)`.
  Translation added; auth bundle now installs 8/8 slices cleanly.
- **Contract §B1.3 rewritten** — was a loose `grep -E "from
  core.venous"` over adapt/extend (counted docstring mentions).
  Now reads `catalog.json` and counts tools whose `primitives_used`
  actually populated (authoritative). Floor set at 19 as a
  non-regression guarantee; any PR that lowers trips the audit.

**Ships (ground-truth docs):**

- **`engine.inventory`** — single machine-verified inventory script
  (→ `INVENTORY.md`) that is THE source of truth for counts. Every
  number in CLAUDE.md / STATUS.md / SKILL.md / ROADMAP.md reconciles
  against it; drift = audit bug. CLAUDE.md, STATUS.md, SKILL.md,
  ROADMAP.md all resynced against fresh inventory.
- **ROADMAP v2** — earlier ROADMAP claimed Phase-3 benchmark + Phase-5
  code-level rubric were "future work". Running the existing code
  (`engine/bench/code_level.py`) proved code-level 100.00 across 20/20
  specs with 100% coverage. Narrative now matches §B3.6 reality.
- **Phase-4 #20 ghost closed** — 5 "empty" scaffolds under
  `skills/SKILL-001-fastapi-production/examples/` were duplicate noise;
  the 20 populated examples live at repo-root `/examples/`. Deleted
  the duplicate; `engine.inventory.examples_dir` now resolves to the
  canonical path.

### Track B — Phase 6 blind benchmark harness (pre-registered)

Third-party-credibility-first harness. Not yet versioned as a minor
release because live runs (naked vs kit on real Claude CLI subagent)
have not executed.

#### Ships (harness + pre-registration)

- **PROTOCOL.md** — pre-registered 2026-04-20. Declares H1/H2, trajectory
  schema, contamination guards, two-arm condition design (naked vs kit),
  and fine-tuning-grade artefact emission (DPO pairs, SFT records,
  process-reward rows).
- **Harness modules** under `engine/bench/blind/`:
  `spec.py` (loader + validator), `adapter.py` (StubAdapter + streaming
  ClaudeCliAdapter with per-turn snapshots + tool_use/tool_result capture
  + precise latency_ms), `judge.py` (multi-layer pytest runner w/
  json-report), `snapshots.py` (tar.zst workdir archive), `attribution.py`
  (primitive-import scan), `static_scan.py` (YAML-rules AST detector),
  `runner.py` (orchestrator), `publish.py` (aggregator + DPO pairs +
  SFT records + anti-pairs).
- **Seed spec** `hard/01_financial_ledger` with 13-test sealed judge
  across layers A/B/C/D/E (acceptance smoke, property-based conservation,
  asyncio concurrency stress, tamper-evidence, AST static scan).
- **Stub fixtures** (`_stub_fixtures/`) — deliberately-flawed "naked"
  emission + SOTA "kit" emission. End-to-end plumbing validated:
    naked → 69.23%   kit → 100.00%   margin 30.77pts → DPO pair emitted.
- **21 unit tests** (`engine/tests/test_blind_harness.py`) covering
  spec loader, judge aggregator, pytest-json parser, publish aggregator,
  attribution, static scan, and snapshot creation. All green.
- **Contract rule B3.7** — blind harness + authored specs + stub
  fixtures + importability smoke. 30/30 → **31/31 ALL GREEN**.

#### Known open (does not ship in v0.3.0 — tracked as v0.3.1+)

Each of the following is an honest gap the current code calls out
explicitly in PROTOCOL.md, comments, or `_stub_fixtures/README.md`:

- **Live runs not yet executed.** ClaudeCliAdapter is wired for real
  (streaming, per-turn snapshots) but v0.3.0 only proved the harness
  plumbing with stubs. First live naked-vs-kit run will produce the
  first real aggregate.json under `results/<run_id>/`.
- **Spec count = 1.** Protocol targets 2 calibration + 10 hard +
  3 impossible; currently 1 hard. Extending the surface is the
  authoring sprint that precedes the first full run.
- **Process-reward per-turn re-judging.** Snapshots per turn work;
  computing a reward per snapshot requires re-running a cheap Layer-A
  smoke per snapshot. Deferred — current `pairs.jsonl` / `sft.jsonl`
  remain fine-tuning-grade at the run level.
- **Rubric trace generation.** Per-test "why it passed/failed" prose
  beyond the stderr snippet we already capture — added in v0.3.1.
- **Chaos log file.** Layer-D currently runs via pytest fixtures
  inside the judge; a separate `chaos_log.jsonl` is listed in PROTOCOL
  §5 as v0.3.1.
- **CI wiring.** Harness stub run + unit tests will move into
  `.github/workflows/blind-bench-stub.yml` in v0.3.1 (cheap; runs on
  every push).

These are not silent TODOs — they are declared gaps.

---

## [0.2.0] — 2026-04-20

Close-v0.1.0 sprint + Phase 5 code-level benchmark harness. The
honest limitation admitted in the v0.1.0 notes ("benchmark is
plan-level, not code-level") is now closed.

### Ships

- **Code-level benchmark harness (B3.6)** — new MCP-adjacent pipeline
  (`engine/bench/code_level.py`) that runs pytest against executable
  targets declared in `benchmarks/spec_code_level_map.json` and
  publishes `benchmarks/code_level_score.json`. Coverage and score
  are reported separately (never conflated).
- **20 examples** (5 → 20) — every benchmark spec now has a tier-
  appropriate, self-contained, stdlib-only example that asserts the
  spec's acceptance criteria via pytest. Previously 5/20 covered,
  now 20/20.

### Benchmark

| Methodology                          | Score   | Coverage     |
| ------------------------------------ | ------- | ------------ |
| `plan_level_v3_best_of_ensemble`     | 100.00  | 20/20 specs  |
| `code_level_pytest_direct`           | 100.00  | 20/20 specs  |

Two methodologies, two different failure modes — never conflated.
A regression in either fails `engine.audit.contract_check` on the
commit that introduces it.

### Contract

- 29/29 → **30/30** ALL GREEN. New rule: **B3.6** code-level harness
  published + perfect on covered specs + ≥25% coverage floor.
- Four tightenings landed in the close sprint (still v0.1.0-labelled):
  - **B1.1** now rejects half-extracted dirs under production
    namespaces (caught 12 orphan candidate dirs from pre-Phase-1;
    all deleted).
  - **B1.2** now enforces ≥3 Compose-with bullets per primitive
    (§A5). Presence alone no longer passes.
  - **B1.7** (new) — FastAPI adapter coverage: ≥15 adapters, every
    adapter has a test, every adapter maps to a registered
    primitive (direct prefix or family-tag table).
  - **B3.5** now enforces a live non-regression floor via
    `benchmarks/baseline_floor.json` (currently 90.0), on top of
    the schema hard floor of 30.

### Polish

- `SKILL.md` — full rewrite for ground-truth. Prior version still
  claimed "Phase 0" and "gap: slice tools do not import primitives".
- `.github/workflows/skill-001-ci.yml` — stale MCP discovery floor
  (`>= 105` → `>= 170`), legacy `run_finhealth.py` reference
  replaced with the Phase-3 schema check, CI test fixtures
  centralized in a single `env:` block.
- Archived pre-Phase-3 benchmark surfaces (`benchmark/test_*.py`,
  `benchmarks/run_finhealth.py`, `benchmarks/HARDCORE_BENCHMARK.md`);
  `benchmark/analyzer.py` retained for the live `fastapi_analyze`
  MCP tool with a new `benchmark/README.md` disambiguating the two
  directories.
- `install.sh` — fixed ANSI escape rendering + updated tool count
  from 100 to 180 in the success banner.

### Upgrade notes

- Any in-flight PR touching `core/venous/<ns>/<Name>/` must include
  the `<Name>.md` in the same commit (B1.1 strict).
- New FastAPI adapters must ship with `test_<Name>Adapter.py` (B1.7).
- When adding a benchmark spec, also add its entry to
  `benchmarks/spec_code_level_map.json` with either a
  `code_level_target` path or an honest `pending_reason`.

---

## [0.1.0] — 2026-04-20

First public release. All five phases 0-4 green per `CONTRACT.md`.

### Ships

- **1 skill:** `SKILL-001-fastapi-production` — production-grade FastAPI
  scaffolding + slice generators.
- **122 primitives** (framework-agnostic Lego blocks in `core/venous/`),
  all 10-tier gated, 100% registered in `engine/primitives_by_concern.yaml`,
  100% carrying `Compose with:` recipes.
- **183 MCP tools** — 180 slice tools + 2 discovery tools
  (`fastapi_find_primitive`, `fastapi_suggest_composition`) + 1 audit
  tool.
- **20 benchmark specs** (5 baseline / 10 mid / 5 adversarial).

### Benchmark

- **Score: 100.00** on `plan_level_v3_best_of_ensemble` methodology
  across 20 specs / 3 tiers.
- Methodology: plan-level mapping (requirement → primitive/tool) with
  best-of ensemble across 3 independent Maestro runs per spec. No
  scorer softening; every gap closed by shipping a real primitive.

### Discoverability

- `find_primitive(query)` — BM25 + Porter-light stemming; top-1 85%,
  P@3 100%, latency <50ms.
- `suggest_composition(intent)` — 290 recipes indexed; top-1 90%,
  P@3 100%.
- Reference docs site — 124 pages, idempotent static build.

### Quality

- 28/28 machine-enforced contract items green
  (`engine/audit/contract_check.py`).
- Nightly benchmark CI publishing `benchmarks/latest_score.json`.
- Docker-validated `install.sh` flow.

### Honest limitations

- One skill only (FastAPI). Second skill gated on v1.0 per ROADMAP §6.
- Benchmark is plan-level, not code-level. Code-level evaluation is
  deferred to Phase 5+.
- `_extracted/` staging area holds 430+ pre-audited primitives; they
  are pulled on demand only, never preemptively.

---

## Versioning policy

- **MAJOR** — removes or renames a primitive / tool that is registered
  in `primitives_by_concern.yaml` or carries an `MCP_TOOL` entry.
- **MINOR** — adds a primitive, tool, recipe, or benchmark spec;
  raises the benchmark score; extends the contract with new rules.
- **PATCH** — fixes a bug in a primitive / tool without changing its
  public signature or invariants.

Breaking changes are never silent: any rename of a registered primitive
or MCP tool ships in a MAJOR release with a deprecation shim kept for
one MINOR cycle.

---

## Release checklist (maintainers)

1. `contract_check` reports `N/N ALL GREEN`.
2. `benchmarks/latest_score.json` regenerated; score moved forward or
   held (never regressed silently).
3. `CHANGELOG.md` `## [Unreleased]` entries migrated into the new
   version section.
4. `VERSION` file bumped.
5. Git tag `vX.Y.Z` created; release notes link to this changelog.
6. Docs site rebuilt and versioned at `/vX.Y.Z/`.
