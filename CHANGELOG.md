# Changelog

All notable changes to HuGR SkillKit are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every release cites its benchmark score, primitive count, and tool count
so a reader can tell — in one glance — whether to upgrade.

---

## [Unreleased] — v0.3.0-dev

Phase 6 — **blind benchmark harness** (third-party-credibility-first).
In development; not yet versioned as a minor release because live
runs (naked vs kit on real Claude CLI subagent) have not executed.

### Ships (harness + pre-registration)

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

### Known open (does not ship in v0.3.0 — tracked as v0.3.1+)

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
