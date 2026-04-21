---
name: fastapi-production
description: HuGR SKILL-001 — scaffolds AND customizes production-grade FastAPI backends. Rails-style 3-layer kit (skill + slice tools + primitives) invokable via MCP.
version: 1.0.0-rc.1
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

Production-grade FastAPI backend. The Maestro invokes this skill to
scaffold a project tree, uses slice tools to add capabilities (auth,
CRUD, payments, realtime, compliance, ...), and composes primitives
directly when a capability doesn't match any slice tool. All three
surfaces are MCP-registered and JIT-discoverable via
`fastapi_meta_search_primitive` and `fastapi_meta_search_composition`.

## On-disk counts (machine-verified)

| Surface | Count | Verify |
|---|---:|---|
| Slice tools under `adapt/extend/` | 100 | `find adapt/extend -name 'add_*.py' ! -name 'test_*' \| wc -l` |
| Total tools in `adapt/` (all verbs + categories) | 127 | `find adapt -name '*.py' ! -name '__init__.py' ! -name 'test_*' \| wc -l` |
| FastAPI adapters (`core/venous/_adapters/fastapi/`) | 16 | `find core/venous/_adapters/fastapi -maxdepth 1 -name '*Adapter.py' ! -name 'test_*' \| wc -l` |
| Generator files (`generators/`) | 60 | `find generators -name '*.py' ! -name '__init__.py' ! -name 'test_*' \| wc -l` |
| MCP-registered tools (catalog) | 201 | `jq '.tools \| length' engine/index/catalog.json` |
| Maestro-visible surface (catalog + tier-1 + tree) | 217 | 201 catalog + 7 tier-1 + 9 tree dispatchers |
| Production primitives (registered) | 122 | `grep -c '^- name:' engine/primitives_by_concern.yaml` |
| Production primitive directories | 122 | `find core/venous -mindepth 2 -maxdepth 2 -type d ! -path '*_extracted*' ! -path '*_adapters*' ! -path '*__pycache__*' \| wc -l` |
| Staged primitives (PascalCase, promotable) | 181 | `jq '[.primitives[] \| select(.status=="staged")] \| length' engine/index/catalog.json` |
| Quarantined primitives (rejected by extraction gate) | 47 | `find core/venous/_extracted/_quarantine -mindepth 2 -maxdepth 2 -type d \| wc -l` |
| Benchmark specs (Phase 3) | 20 | `find benchmarks/specs -name '*.md' ! -name 'README.md' \| wc -l` |
| Contract items green | 36/36 | `PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check` |
| Extend tools primitive-connected | 22/100 | `jq '[.tools[] \| select(.verb=="add" and (.module_path \| startswith("adapt/extend/")) and (.primitives_used \| length > 0))] \| length' engine/index/catalog.json` |
| Benchmark score (plan-level, best-of ensemble) | 100.00 | `jq '.overall' benchmarks/latest_score.json` |
| Benchmark score (code-level, 20/20 specs) | 100.00 | `jq '.overall' benchmarks/code_level_latest.json` |

The 217 Maestro-visible surfaces decompose as: 201 auto-discovered catalog
tools (100 `adapt/extend/` slice + 27 other `adapt/` tools across
evolve/operate/verify/contracts/proactive + 60 generators + 9 module-tools
+ remainder = audit/discovery helpers) + 7 tier-1 meta tools
(`mcp_tools/tier1.py` + `mcp_tools/compose.py`) + 9 domain-tree
dispatchers (`mcp_tools/tree/`). All auto-discovered via `MCP_TOOL`
metadata scan — CONTRACT §B1.5 forbids manual `@mcp_app.tool` decorators.

## Maestro workflow

1. **Discovery.** MCP client lists tools via `tools/list`. JIT
   retrieval via `fastapi_meta_search_primitive(query, concern?)` +
   `fastapi_meta_search_composition(intent)` — BM25 + recipe index.
   Latency <50 ms cold; top-1 accuracy 85% (primitives), 90% (recipes).
2. **Scaffold.** Maestro calls a macro generator (e.g.
   `fastapi_generate_project`) to lay down the project tree.
3. **Capability adds.** Maestro invokes one or more slice tools
   (`fastapi_add_stripe_webhook`, `fastapi_add_rbac`, …). 64 of the
   19 slice tools emit code that imports from `core.venous.*` —
   the Rails-analogy connection is fully operative (Phase 1 complete).
4. **Customize.** Where no slice tool fits exactly, Maestro composes
   primitives directly — `from core.venous.<ns>.<Name>` into the
   generated code. Every production primitive carries a
   "Compose with:" section citing ≥3 sibling pairings.

## Tool categories (adapt/extend)

| Folder | Count | Example tools |
|---|---:|---|
| `auth_access/` | 15 | `add_rbac`, `add_oauth2_provider`, `add_mfa`, `add_social_login` |
| `crud_data/` | 12 | `add_cursor_pagination`, `add_event_sourcing`, `add_soft_delete`, `add_audit_log` |
| `api_design/` | 9 | `add_api_versioning`, `add_graphql`, `add_long_running_task` |
| `infrastructure/` | 38 | `add_stripe_webhook`, `add_rate_limiting`, `add_saga`, `add_retry_budget`, `add_graceful_shutdown` |
| `realtime/` | 8 | `add_sse`, `add_websocket_chat`, `add_webhook_receiver`, `add_presence` |
| `testing_tools/` | 9 | `add_data_seeder`, `add_schema_evolution_guard`, `add_api_fuzzer` |
| `performance/` + `proactive/` + others | 9 | `add_bulkhead`, `add_capacity_planner`, `add_n_plus_one_guard` |

Exact per-folder counts:
```bash
for d in adapt/extend/*/; do
  echo "$d $(find "$d" -name 'add_*.py' ! -name 'test_*' | wc -l)"
done
```

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
it scores the Maestro's requirement→primitive/tool map, not the
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
curl -fsSL https://raw.githubusercontent.com/humangr-labs/HuGR_Skills/main/install.sh | bash
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

Five real Maestro-built examples live under `/examples/`, each
tied to a benchmark spec and passing pytest end-to-end
(24/24 tests green). See `/examples/*/MAESTRO_SESSION.md` for
the plan-level transcript the Maestro used to build them.

---

Signed: Gustavo Schneiter — v1.0.0-rc.1 (Phase 5 complete, golive pending).
Every claim above is machine-verifiable via the commands shown.
Drift from this file is a §A8 bug to fix same-day.
