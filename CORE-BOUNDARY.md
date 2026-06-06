# CORE-BOUNDARY — what becomes `hugr-core` (Phase 2)

> Drawn during the v1.0 standalone extraction (Phase 1). This file is the
> contract for Phase 2: promote the generic platform machinery out of this
> skill into a pinnable `hugr-core` package in the Arsenal, so thousands of
> skills share one source of truth instead of vendoring N diverging copies.
>
> Plug model: each skill repo depends on `hugr-core @ git+…@<tag>` (SemVer,
> explicit upgrade) and ships only its domain content + a thin manifest.

## Moves to `hugr-core` (generic, framework-free)

| Area | Paths | Notes |
|---|---|---|
| Engine framework | `engine/inventory.py`, `engine/index/manifest.py` (scanner + catalog builder), `engine/promotion/*`, `engine/bench/*` (runner + rubric + blind harness), `engine/gates/*` (10-tier primitive quality), `engine/llm/*`, `engine/briefings/*`, `engine/contracts/*` | Pure machinery; parameterised by the skill manifest |
| Contract runner | `engine/audit/contract_check.py` (runner), `engine/audit/contract_rules/_common.py` (Rule dataclass, REPO_ROOT/SKILL_ROOT resolution, `_exists`/`_grep_count`) + the **generic** rules (file-size cap, md-location, no-committed-venv, VERSION/CHANGELOG/CONTRIBUTING presence, counts-sync mechanism, §A inviolable rules) | Generic rules → core; **skill §B rules stay** (see below), registered via a plugin hook |
| MCP serving | `mcp_tools/discovery.py` (`discover()` entry), registration machinery, tier-1/tree **dispatcher base patterns**, `mcp_tools/auth_gate.py`, `mcp_tools/compose.py` engine, BM25 search | The generic registration/dispatch/search; not the concrete tools |
| Test/contract framework | `tests/common/fixture_factory.py`, `tests/common/tool_contract.py` (generic checks), `tests/contracts/delivery_contract*.py` | Reusable across any skill |
| Primitive conventions | primitive shell schema (contract.json/protocol/invariants), `.venous_manifest.json` provenance, `generators/scaffold_venous.py` copy-in mechanism | The convention + copy-in engine, not the primitives |

## Stays in this skill repo (domain content)

- `core/venous/<domain>/*` primitives (FastAPI) + `core/venous/_adapters/fastapi/`
- `adapt/extend/*` + `adapt/{verify,operate,evolve,contracts,proactive}/`
- `generators/*` (FastAPI scaffolders), `modules/*` (FastAPI packages)
- `specs/`, `app/`, `alembic/`, `infra/`, `benchmarks/`, `examples/`
- the **concrete** `fastapi_meta_*` tier-1 tools + `fastapi_*` tree dispatchers (the generic base goes to core; the FastAPI instantiation stays)
- the **FastAPI-specific §B contract rules** (the generic §A rules go to core)
- `engine/index/catalog.json`, `SKILL.md`, `manifest.yaml`, `VERSION`
- `requirements-mcp.txt`, `requirements-apps.txt`, `ci.sh`

## Mixed modules needing surgery in Phase 2

These are the only non-trivial splits — each is generic-runner + skill-config today:

1. **`engine/audit/contract_check.py` + `contract_rules/`** — generic runner & §A/file/counts rules → core; FastAPI §B tool/primitive rules → skill, loaded via a `register_skill_rules()` hook. (Phase 1 already made `_common.py` layout-aware as the first step.)
2. **`mcp_tools/tier1.py` + `tree/`** — dispatcher/registration framework → core; the `fastapi_*`-named tool definitions → skill.
3. **`engine/index/manifest.py` `TOOL_SCAN_ROOTS`** — generic scanner → core; the concrete roots/prefix config → skill manifest.

## The skill manifest (Phase 2 plug API)

Each skill declares (proposed `skill.toml` / extend `manifest.yaml`):
- `hugr_core_version` — pinned SemVer of the core dependency
- `tool_prefix` — e.g. `fastapi` (drives tier-1/dispatcher/catalog naming)
- `tool_scan_roots` — dirs the scanner indexes
- `primitive_namespaces` — the domain namespaces
- `skill_rules_module` — dotted path to the skill's §B contract rules

`hugr-core` consumes the manifest and provides engine + mcp serving + contract
running parameterised by it. Standalone-vs-monorepo layout detection (already in
`_common.py`) becomes a core concern.

## Phase 1 status (this extraction)

- ✅ Repo created with full history preserved (370 commits, `git subtree split`).
- ✅ Shared root docs brought in (CHANGELOG/CONTRIBUTING/CLAUDE/ROADMAP/CONTRACT).
- ✅ Hidden app-dep debt declared (`requirements-apps.txt`) — boot 0→95/100 clean venv.
- ✅ Contract framework made layout-aware (`_common.py`).
- ⏳ Remaining: last boot failures, contract 47/47 standalone, then Arsenal-side removal.
