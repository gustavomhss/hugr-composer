# Changelog

All notable changes to HuGR SkillKit are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every release cites its benchmark score, primitive count, and tool count
so a reader can tell — in one glance — whether to upgrade.

---

## [Unreleased]

_No unreleased changes._

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
