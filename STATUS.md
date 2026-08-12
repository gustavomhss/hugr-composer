---
name: fastapi-production
description: HuGR SKILL-001 — scaffolds AND customizes production-grade FastAPI backends. Rails-style 3-layer kit (skill + slice tools + primitives) invokable via MCP.
version: 1.0.0
---

# SKILL-001 — FastAPI Production

> **Architecture, philosophy, and success criteria live in
> [`/PRODUCT.md`](../../PRODUCT.md). Current state + roadmap live in
> [`/ROADMAP.md`](../../ROADMAP.md). Binding execution rules live in
> [`/CONTRACT.md`](../../CONTRACT.md). Contribution workflows live in
> [`/CONTRIBUTING.md`](../../CONTRIBUTING.md).**
>
> This file describes what THIS skill contains right now, verifiably.
> Every number carries the shell command a reader can run to
> reproduce it. CONTRACT §A8 binds us to a drift-of-zero.

## Skill scope

Production-grade FastAPI backend. The agent invokes this skill to
scaffold a project tree, uses slice tools to add capabilities (auth,
CRUD, payments, realtime, compliance, ...), and composes primitives
directly when a capability doesn't match any slice tool. All three
surfaces are MCP-registered and JIT-discoverable via
`fastapi_meta_search_primitive` and `fastapi_meta_search_composition`.

## On-disk counts (machine-verified)

| Surface | Count | Verify |
|---|---:|---|
| Slice tools under `adapt/extend/` | 105 | `PYTHONPATH=. .venv/bin/python -m engine.inventory` → §1 extend |
| Total tools in `adapt/` (all verbs + categories) | 135 | `PYTHONPATH=. .venv/bin/python -m engine.inventory` → §1 adapt |
| FastAPI adapters (`core/venous/_adapters/fastapi/`) | 18 | `find core/venous/_adapters/fastapi -maxdepth 1 -name '*Adapter.py' ! -name 'test_*' \| wc -l` |
| Generator files (`generators/`) | 61 | `PYTHONPATH=. .venv/bin/python -m engine.inventory` → §3 |
| MCP-registered tools (catalog) | 202 | `jq '.tools \| length' engine/index/catalog.json` |
| agent-visible surface (catalog + tier-1 + tree) | 219 | 202 catalog + 8 tier-1 + 9 tree dispatchers |
| Production primitives (registered) | 124 | `grep -c '^- name:' engine/primitives_by_concern.yaml` |
| Production primitive directories | 124 | `find core/venous -mindepth 2 -maxdepth 2 -type d ! -path '*_staging*' ! -path '*_adapters*' ! -path '*__pycache__*' \| wc -l` |
| Staged primitives (PascalCase, promotable) | 174 | `jq '[.primitives[] \| select(.status=="staged")] \| length' engine/index/catalog.json` |
| Quarantined primitives (rejected by extraction gate) | 41 | `find core/venous/_staging/_quarantine -mindepth 2 -maxdepth 2 -type d \| wc -l` |
| Provider adapters (`_adapters/{redis,stripe}/`) | 2 | `find core/venous/_adapters -maxdepth 2 -name '*Adapter.py' ! -path '*fastapi*' ! -name 'test_*' \| wc -l` |
| Benchmark specs (Phase 3) | 20 | `find benchmarks/specs -name '*.md' ! -name 'README.md' \| wc -l` |
| Contract items green | 47/47 | `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check` |
| Extend tools primitive-connected | 24/105 | `jq '[.tools[] \| select(.verb=="add" and (.module_path \| startswith("adapt/extend/")) and (.primitives_used \| length > 0))] \| length' engine/index/catalog.json` |
| Benchmark score (plan-level, best-of ensemble) | 100.00 | `jq '.overall' benchmarks/latest_score.json` |
| Benchmark score (code-level, 20/20 specs) | 100.00 | `jq '.overall' benchmarks/code_level_latest.json` |

The 219 agent-visible surfaces are: 202 auto-discovered catalog tools
(indexed in `engine/index/catalog.json`) + 8 tier-1 meta tools
(`mcp_tools/tier1.py`) + 9 domain-tree dispatchers (`mcp_tools/tree/`).
All auto-discovered via `MCP_TOOL` metadata scan — CONTRACT §B1.5 forbids
manual `@mcp_app.tool` decorators. Note: the catalog count (202 indexed
tools) and the file-based counts in `INVENTORY.md` §1 (135 adapt + 61
generators) use different methods and are not meant to sum — INVENTORY is
the single source of truth for each.

## agent workflow

1. **Discovery.** MCP client lists tools via `tools/list`. JIT
   retrieval via `fastapi_meta_search_primitive(query, concern?)` +
   `fastapi_meta_search_composition(intent)` — BM25 + recipe index.
   Latency <50 ms cold; top-1 accuracy 85% (primitives), 90% (recipes).
2. **Scaffold.** agent calls a macro generator (e.g.
   `fastapi_generate_project`) to lay down the project tree.
3. **Capability adds.** agent invokes one or more slice tools
   (`fastapi_add_stripe_webhook`, `fastapi_add_rbac`, …). 24 of the
   105 slice tools emit code that imports from `core.venous.*` (§B1.3,
   floor 22) — the Rails-analogy connection is operative (Phase 1 complete).
4. **Customize.** Where no slice tool fits exactly, agent composes
   primitives directly — `from core.venous.<ns>.<Name>` into the
   generated code. Every production primitive carries a
   "Compose with:" section citing ≥3 sibling pairings.

## Tool categories (adapt/extend)

| Folder | Count | Example tools |
|---|---:|---|
| `auth_access/` | 17 | `add_rbac`, `add_oauth2_provider`, `add_mfa`, `add_social_login` |
| `crud_data/` | 11 | `add_cursor_pagination`, `add_event_sourcing`, `add_soft_delete`, `add_audit_log` |
| `api_design/` | 7 | `add_api_versioning`, `add_graphql`, `add_long_running_task` |
| `infrastructure/` | 53 | `add_stripe_webhook`, `add_rate_limiting`, `add_saga`, `add_retry_budget`, `add_graceful_shutdown` |
| `realtime/` | 5 | `add_sse`, `add_websocket_chat`, `add_webhook_receiver`, `add_presence` |
| `testing_tools/` | 12 | `add_data_seeder`, `add_schema_evolution_guard`, `add_api_fuzzer` |

Total: 105 extend tools. Exact per-folder counts are machine-generated —
regenerate with `PYTHONPATH=. .venv/bin/python -m engine.inventory` (see
`INVENTORY.md` §1, `adapt/extend/ sub-domains`).

## Primitives (`core/venous/<concern>/<Name>/`)

16 concerns: `api, auth, cache, compliance, cost, data.modelling,
data.persistence, data.schema, events, extras, flags, jobs, llm,
observability, policy, resiliency, security`.

Each production primitive directory contains:
- `<Name>.py` — framework-free reference impl (no `fastapi` /
  `sqlalchemy` imports — §A1 enforced)
- `<Name>.protocol.py` — typed Protocol; the public interface
- `<Name>.md` — narrative spec with invariants + "Compose with:"
- `<Name>.contract.json` — machine-readable contract + T0-T9 tier record
- `test_<Name>.py` — ≥ 1 test per declared invariant
- `__init__.py` — exports Protocol + impl
- `_provenance.json` — OSS origin + license (or `"origin": "native"`)

Several primitives additionally carry `observability_schema.json`,
`dashboard.json`, `persona_reviews.json` (audit trail), and
TLA+ specs (`.tla` + `.cfg`) for state-machine primitives.

Registry + recipe index are machine-readable:

```bash
# By concern
cat engine/primitives_by_concern.yaml

# Reference docs site (deterministic static HTML)
PYTHONPATH=. .venv/bin/python -m engine.docs.build --verify
open docs_site/index.html
```

## Benchmark (Phase 3)

20 plain-English product specs under `benchmarks/specs/`:
- 5 **baseline** (crud, auth-only, webhook sink, rate-limited, multi-tenant)
- 10 **mid** (Stripe SaaS, realtime chat, event-sourced orders, RBAC+audit,
  LLM agent, mobile backend, compliance log, GraphQL, workflow, BI export)
- 5 **adversarial** (exactly-once on weak broker, stateless-but-session,
  lock-free AND serializable, ML inference pool, innocent counter)

Each run scored on a 4-dimension rubric (25% each):
scaffold_completeness · test_suite_pass · primitive_gate_pass ·
hand_editability.

Current score (methodology `plan_level_v3_best_of_ensemble`):

```json
{ "overall": 100.00,
  "by_tier": {"baseline": 100, "mid": 100, "adversarial": 100} }
```

**Known limitation (see `/CHANGELOG.md` v0.1.0):** this is *plan-level* —
it scores the the agent's requirement→primitive/tool map, not the
executable behaviour of the emitted code. Code-level evaluation is
Phase 5 work (tracked by a dedicated CONTRACT item added this sprint).

## Running the MCP server

```bash
cd skills/SKILL-001-fastapi-production
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-mcp.txt
PYTHONPATH=. .venv/bin/python -m mcp_tools.server
```

Or use the hermetic one-liner that installs system-wide into
`~/.hugr-skills/`:

```bash
curl -fsSL https://raw.githubusercontent.com/humangr-labs/HuGR-Arsenal/main/install.sh | bash
```

Validated nightly in a fresh `python:3.12-slim` container —
`.github/workflows/install-docker.yml`.

## Contract enforcement

```bash
# Run the full 36-rule check
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check

# Run a single phase (for PR work targeting one phase)
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check --phase 4

# Run a specific item (e.g. after a targeted fix)
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check --item B1.1
```

Exits 0 iff every machine-checkable CONTRACT.md item passes. CI
wires this into every push + PR under
`.github/workflows/skill-001-ci.yml`.

## Tests

| Suite | Count (current green run) | Runner |
|---|---:|---|
| Unit (`adapt/**/test_*.py`) | 3168 passed, 1 skipped | `PYTHONPATH=. .venv/bin/python -m pytest adapt/ -q` |
| Engine (`engine/tests/`) | 133 passed, 7 skipped | `PYTHONPATH=. .venv/bin/python -m pytest engine/tests/ -q` |
| Boot (every tool imports + basic run) | 100/100 | `PYTHONPATH=. .venv/bin/python tests/test_boot.py` |
| Property (8 properties × ~55 tools) | green | `PYTHONPATH=. .venv/bin/python tests/property_tests.py` |
| SQLite E2E (12 scenarios) | green | `PYTHONPATH=. .venv/bin/python tests/test_e2e_hardcore.py` |
| Postgres E2E (8 scenarios) | green (needs local PG) | `./ci.sh` (auto-starts PG via Docker) |
| Behaviour (12 domains) | green (needs PG) | `PYTHONPATH=. .venv/bin/python tests/test_behavior_scenarios.py` |
| Cross-composition (200+ scenarios) | green | `PYTHONPATH=. .venv/bin/python tests/test_cross_composition.py` |
| Primitive tests (`core/venous/**/test_*.py`) | green | `PYTHONPATH=. .venv/bin/python -m pytest core/venous/ -q` |

Local full CI (replicates GitHub Actions):

```bash
./ci.sh              # with PostgreSQL (Docker)
./ci.sh --no-pg      # without PostgreSQL (skips PG-dependent suites)
```

## Examples

20 real agent-built examples live under `/examples/`, each
tied to a benchmark spec and passing pytest end-to-end
(94 tests across 20 apps). See `/examples/*/AGENT_SESSION.md` for
the plan-level transcript the agent used to build them.

---

Signed: Gustavo Schneiter — v1.0.0 (Phase 5 complete, go-live 2026-06-05).
Every claim above is machine-verifiable via the commands shown.
Drift from this file is a §A8 bug to fix same-day.
