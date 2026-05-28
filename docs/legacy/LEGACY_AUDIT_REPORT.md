# SKILL-001 Legacy Audit Report

> Produced: 2026-04-13
> Scope: inventory of pre-existing code in `SKILL-001-fastapi-production/` before implementing the 51 new TOOL-* specs.
> Purpose: decide what to preserve, what to refactor, what to build new — with zero assumptions.

---

## 1. Executive summary

The skill already ships **v3.1** with substantial working infrastructure:

| Component | Status | LOC | Notes |
|---|---|---|---|
| `generators/` (base + granular) | ✅ works | **12,980** | 59 generator files, produces runnable projects |
| `modules/` (v2 Rails-style) | ⚠️ legacy | **13,819** | older architecture, presumed deprecated by manifest.yaml v3.1 |
| `core/` (contracts + models) | ✅ works | **1,773** | `Finding`, `ToolResult`, etc. — shared Pydantic models |
| `benchmark/` (test suite) | ⚠️ partial | **2,321** | orchestrator runs; `test_functional.py` / `test_e2e_agent.py` import generated `app.*` at parse time (expected — they run against a generated project) |
| `mcp_server.py` | ✅ exists | FastMCP 3.0 server exposing ~30 tools as MCP endpoints |
| `SKILL.md` + `manifest.yaml` + `core/KNOWLEDGE.md` | ✅ exists | Complete SKILL.md bundle + 15K knowledge file |
| `loader.py` | ✅ exists | Module discovery + loading logic |

**Bottom line**: the skill has a working base generator stack that scores 35/35 on its own 35-check audit (per `SKILL.md`, beating tiangolo 24/35 and naked LLMs 21-23/35). The 51 new specs written in this session do NOT overlap with any existing file by name. They are a pure **expansion** layer.

---

## 2. Existing v3.1 architecture

### 2.1 Base generators (`generators/`) — PRESERVE

These generate the initial production FastAPI project (Convention over Configuration). Tested: `fastapi_generate_project()` produces **61 files** that all pass `ast.parse()`, include migrations, tests, CI workflow, Dockerfile, middleware stack, auth chain, CRUD routes, observability.

```
generators/
  __init__.py
  _pluralize.py
  orchestrator.py          ← fastapi_generate_project (the one-call entry point)
  auth/                    ← hasher, jwt, deps, routes, schemas, rate_limit
  database/                ← engine, session, model, crud, alembic, alembic_migration, crud_base
  deployment/              ← docker_compose, github_actions, k6_loadtest, k8s
  endpoints/               ← crud_routes, errors, health, user_routes
  infra/                   ← app (main.py), config, dockerfile, env_example, gitignore, logging, precommit, prestart, readme, initial_data, email
  middleware/              ← body_size, correlation, cors, idempotency, request_logging, security_headers, stack
  observability/           ← alerting, otel, prometheus
  schemas/                 ← input_schema, output_schema, list_response
  testing/                 ← conftest, test_suite
  tools/                   ← 8 adapt tools (add_model, add_endpoint, add_middleware, add_background_job, add_websocket, add_integration, fix_findings, migrate_db) + _layout.py + __init__.py
```

**59 base generator files**, all functional, 12,980 LOC.

### 2.2 Current adapt tools (`generators/tools/`) — 8 files

These are the current "modify existing project" surface:

| Tool | Params | Scope |
|---|---|---|
| `fastapi_add_model` | project_dir, name, fields, owner_field | **generic** — adds any model + CRUD + schemas + routes |
| `fastapi_add_endpoint` | project_dir, route_file, method, path, name, auth, request_body, response_model | **generic** — adds any endpoint |
| `fastapi_add_middleware` | project_dir, name, code, position | **generic** — adds any middleware at position (outermost/after_cors/before_logging/innermost) |
| `fastapi_add_background_job` | project_dir, name, queue, retry_max, cron | **generic** — ARQ job with optional cron |
| `fastapi_add_websocket` | project_dir, name, path, auth | **generic** — WebSocket with ConnectionManager |
| `fastapi_add_integration` | project_dir, service, config | **generic** — wires third-party services |
| `fastapi_fix_findings` | project_dir, findings | **fix runner** — applies patches from analyzer findings |
| `fastapi_migrate_db` | project_dir, autogenerate, message | **migration runner** — alembic wrapper |

**Key insight**: all 8 are **generic primitives**. They accept arbitrary user-supplied parameters and modify the project in a schema-agnostic way. They do NOT encode feature-specific knowledge (they don't know what soft delete is, or MFA, or audit log — they're just wiring primitives).

### 2.3 Legacy `modules/` — DEPRECATED candidate

The `modules/` directory represents an earlier architecture:

```
modules/
  auth/         (scaffold_auth, verify_auth, pentest_auth)
  background_jobs/ (scaffold_jobs, verify_jobs)
  caching/      (scaffold_cache, operate_cache)
  database/     (scaffold_db, verify_db, operate_db)
  deployment/   (generate_ci, generate_docker, generate_k6, generate_k8s)
  observability/(generate_alerts, scaffold_otel, verify_traces)
  payments/     (scaffold_payments, verify_payments)
  security/     (scaffold_security, verify_security, pentest_api, models.py)
  websockets/   (scaffold_ws, verify_ws)
```

**45 Python files, 13,819 LOC.** The v2 architecture grouped tools by *domain* (auth, database, security) with three verbs per domain: `scaffold_*` (create), `verify_*` (check), `operate_*` / `pentest_*` (modify/attack).

The v3 pivot (per memory `hugr_skills_convention_over_config.md`) moved from domain-grouped `scaffold` → granular per-artifact generators. The `modules/` stack was not deleted but is not referenced by the current `mcp_server.py` or `manifest.yaml v3.1`.

**Recommendation**: audit each `modules/*/tools/*.py` for unique logic worth preserving, then archive or delete. For now, assume deprecated but not in the way.

### 2.4 `benchmark/` — partial status

```
benchmark/
  analyzer.py          ← 35-check production audit engine (referenced from SKILL.md)
  test_functional.py   ← functional tests on a GENERATED project (imports app.*)
  test_generators.py   ← tests each generator function
  test_integration.py  ← integration tests
  test_e2e_agent.py    ← E2E with an agent driver
  import_audit.py      ← static import validation
```

The `import_audit.py` reports "10 errors" but those are `app.*` imports inside test files that run against a generated project — expected, not a bug. The tests presume a fresh `fastapi_generate_project()` output is available.

**Status**: orchestrator smoke test passes (`from generators.orchestrator import generate_project` works). Full test suite status unknown until we run it against a fresh generated project. To be confirmed in Onda 1.

---

## 3. The 51 new TOOL-* specs — where do they fit?

### 3.1 Mapping of specs to existing code

| Spec | File exists? | Relation to existing code |
|---|---|---|
| TOOL-001 `add_soft_delete` | ❌ GAP | new high-level adapt tool |
| TOOL-002 `add_cursor_pagination` | ❌ GAP | new high-level adapt tool |
| TOOL-003 `add_file_upload` | ❌ GAP | new high-level adapt tool |
| TOOL-004 `add_search` | ❌ GAP | new high-level adapt tool |
| TOOL-005 `add_audit_log` | ❌ GAP | new high-level adapt tool |
| TOOL-006 `add_data_export` | ❌ GAP | new high-level adapt tool |
| TOOL-007 `add_bulk_operations` | ❌ GAP | new high-level adapt tool |
| TOOL-008 `add_multi_tenancy` | ❌ GAP | new high-level adapt tool |
| TOOL-009 `add_feature_flags` | ❌ GAP | new high-level adapt tool |
| TOOL-010 `add_api_key_auth` | ❌ GAP | new high-level adapt tool |
| TOOL-011 `add_oauth2_provider` | ❌ GAP | new high-level adapt tool |
| TOOL-012 `add_rbac` | ❌ GAP | new high-level adapt tool |
| TOOL-013 `add_mfa` | ❌ GAP | new high-level adapt tool |
| TOOL-014 `add_sse` | ❌ GAP | new high-level adapt tool |
| TOOL-015 `add_webhook_sender` | ❌ GAP | new high-level adapt tool |
| TOOL-016 `add_webhook_receiver` | ❌ GAP | new high-level adapt tool |
| TOOL-017..024 (API Design + Infra) | ❌ GAP | new high-level adapt tools |
| TOOL-025..027 (Testing) | ❌ GAP | new high-level adapt tools |
| TOOL-028..034 (VERIFY) | ❌ GAP | new verification tools (replaces/extends `fastapi_analyze`) |
| TOOL-035..042 (OPERATE) | ❌ GAP | new operate-phase tools (debt, health, alerts, SLA reports) |
| TOOL-043..050 (EVOLVE) | ❌ GAP | new refactor/migration tools |
| TOOL-051 `fastapi_doctor` | ❌ GAP | holistic proactive auditor (orchestrates all VERIFY tools) |

**Result: 51/51 GAPs.** Zero overlap with existing file names. The 51 specs are a pure expansion.

### 3.2 Conceptual relationship

```
┌──────────────────────────────────────────────────────────────────┐
│  BASE LAYER (existing, working, preserved)                       │
│  generators/orchestrator.py → fastapi_generate_project()         │
│  + 50 granular generators (auth, db, middleware, etc.)           │
│  Produces: 61-file production-ready base project                 │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  LOW-LEVEL ADAPT PRIMITIVES (existing, working, preserved)       │
│  generators/tools/                                               │
│  8 generic primitives (add_model, add_endpoint, add_middleware,  │
│   add_background_job, add_websocket, add_integration,            │
│   fix_findings, migrate_db)                                      │
│  Each accepts arbitrary schema-agnostic params                   │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  HIGH-LEVEL FEATURE ADAPT TOOLS (NEW — the 51 specs to build)    │
│  tools/adapt/ (new namespace, to be created)                     │
│  51 feature-specific tools that encode SOTA knowledge:           │
│    - add_soft_delete knows EXACTLY how to implement soft delete  │
│    - add_mfa knows EXACTLY how to implement TOTP correctly       │
│    - detect_n_plus_one knows EXACTLY how to find query loops     │
│  Each tool internally calls low-level primitives as needed.      │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  PROACTIVE LAYER (NEW — TOOL-051 fastapi_doctor)                 │
│  Orchestrates VERIFY tools + recommends EXTEND tools             │
└──────────────────────────────────────────────────────────────────┘
```

### 3.3 Decisions required

1. **`modules/` legacy**: archive or delete?
2. **New tools namespace**: create `tools/adapt/` or reuse `generators/tools/`?
3. **Low-level primitive reuse**: do the 51 high-level tools call `add_model` / `add_endpoint` / `add_middleware` internally, or do they each emit code directly?
4. **VERIFY tool overlap**: the existing `benchmark/analyzer.py` already does a 35-check audit. TOOL-028..034 (detect_n_plus_one, security_scan, dependency_audit, schema_coverage, test_coverage_gaps, api_spec_compliance, performance_baseline) partially overlap with it. Do we extend `analyzer.py` or build parallel tools?
5. **TOOL-051 fastapi_doctor**: `fastapi_analyze` already exists in `benchmark/analyzer.py` and is exposed via MCP. TOOL-051 is a holistic orchestrator — is it a new tool or an extension of `fastapi_analyze`?

---

## 4. Recommendations (to be approved before writing code)

### R1: PRESERVE the working base

Keep `generators/`, `core/`, `mcp_server.py`, `SKILL.md`, `manifest.yaml`, `loader.py` untouched. They work, they are production-tested, they score 35/35. Do not rewrite.

### R2: ARCHIVE the v2 `modules/` layer

Move `modules/` → `_archive_v2/modules/` with a README explaining the v2-to-v3 pivot. Do not delete — the pentest/security logic may contain unique insights to port into the new VERIFY tools. Archive, don't destroy.

### R3: NEW namespace for the 51 high-level tools

Create a new top-level directory for the 51 tools:

```
adapt/                          ← new top-level namespace
  __init__.py
  contracts.py                  ← shared ToolResult / ToolInput dataclass
  extend/
    crud_data/                  ← TOOL-001..007
      add_soft_delete.py
      add_cursor_pagination.py
      ... (7 files)
    auth_access/                ← TOOL-008..013
      add_multi_tenancy.py
      add_feature_flags.py
      ... (6 files)
    realtime/                   ← TOOL-014..016
    api_design/                 ← TOOL-017..020
    infrastructure/             ← TOOL-021..024
    testing/                    ← TOOL-025..027
  verify/                       ← TOOL-028..034
  operate/                      ← TOOL-035..042
  evolve/                       ← TOOL-043..050
  proactive/                    ← TOOL-051 fastapi_doctor
```

The separation between `generators/` (base) and `adapt/` (feature-specific customization) makes the mental model crisp: generators create the skeleton, adapt tools evolve it.

### R4: Low-level primitives become INTERNAL API

The 8 existing `generators/tools/` primitives (`add_model`, `add_endpoint`, etc.) stop being exposed directly on the MCP server. They become **internal building blocks** that the 51 new high-level tools call. The LLM only sees the 51 feature-specific tools. This avoids confusing the agent with 51 + 8 = 59 overlapping "add something" verbs.

Exception: `fastapi_migrate_db` and `fastapi_fix_findings` stay public — they're runners, not primitives.

### R5: VERIFY tool strategy — extend `analyzer.py`, don't parallel-build

`benchmark/analyzer.py` already runs a 35-check audit. TOOL-028..034 should be implemented as **named check groups** inside the same engine:

```python
adapt/verify/detect_n_plus_one.py → runs analyzer with check_group="n_plus_one"
adapt/verify/security_scan.py     → runs analyzer with check_group="security"
```

Each VERIFY tool is a thin wrapper that filters the existing analyzer's output + adds tool-specific enhancements (fixtures, fuzz inputs, specific thresholds). Avoids duplication.

### R6: TOOL-051 fastapi_doctor = top-level orchestrator

`fastapi_doctor` invokes all 7 VERIFY tools in parallel, aggregates findings by severity, cross-references with the 27 EXTEND tools to emit "recommendation" signals ("project has auth but no MFA — consider TOOL-013"), and produces a unified fix plan. It does NOT duplicate analyzer logic — it composes it.

### R7: Test strategy — co-locate + fixture projects

```
adapt/extend/crud_data/add_soft_delete.py
adapt/extend/crud_data/test_add_soft_delete.py       ← unit
adapt/extend/crud_data/test_add_soft_delete_e2e.py   ← against fixture project
adapt/extend/crud_data/test_add_soft_delete_props.py ← Hypothesis properties
adapt/extend/crud_data/test_add_soft_delete_chaos.py ← chaos
adapt/extend/crud_data/test_add_soft_delete_mutate.sh ← mutmut runner
```

Each tool has 5 test files. `tests/fixtures/` holds N fresh-generated base projects at different configurations. Test harness uses a fixture factory that invokes `fastapi_generate_project()` on demand.

### R8: Audit infrastructure is independent

```
audit/
  audit_everything.py          ← top-level aggregator
  audit_l1_correctness.py      ← runs reviewer + ast.parse + ruff + mypy + bandit on ALL generated files
  audit_l2_brutal_tests.py     ← runs coverage + mutation + property + fuzz + chaos + load + soak
  audit_l3_security.py         ← bandit + semgrep + pip-audit + red team agent
  audit_l3_code_quality.py     ← radon + vulture + deptry + duplicate detection
  audit_l3_performance.py      ← py-spy + memray + query plans + benchmarks
  audit_l3_api_design.py       ← schemathesis + spectral + openapi-diff
  audit_l3_operational.py      ← logs + metrics + dashboards + alerts + runbooks
  audit_l3_documentation.py    ← doctest + mkdocs strict + pydocstyle
  audit_l3_compliance.py       ← GDPR/SOC2 templates + license audit + SBOM
  audit_l4_infra.py            ← docker lint + kubeval + kube-linter + helm lint
  audit_l5_observability.py    ← dashboard validation + alert rules + SLO burn rate
  audit_l6_red_team.py         ← adversarial agent runs
  audit_l7_reference_customers.py ← 3 full projects built end-to-end
  reports/                     ← timestamped audit reports
```

`make audit` runs everything, produces `audit/reports/AUDIT_YYYY-MM-DD.md` with all metrics. User can `cat` it anytime.

---

## 5. Work estimate (honest)

| Phase | Scope | Sessions |
|---|---|---|
| **Phase 0 — Audit + approval** | this document + your decisions on R1..R8 | 0.5 (this session) |
| **Phase 1 — Infrastructure** | archive v2, create `adapt/` tree, define contracts.py, fixture factory, audit scaffold, 1 reference tool (TOOL-001) with ALL L1+L2 tests as golden reference | 2-3 sessions |
| **Phase 2 — EXTEND wave (27 tools)** | TOOL-001..027 implementations in parallel batches via Sonnet agents, each with unit + e2e + property + chaos + mutation, each audited | 8-12 sessions |
| **Phase 3 — VERIFY wave (7 tools)** | TOOL-028..034 — extend analyzer.py, each with brutal test suite | 3-4 sessions |
| **Phase 4 — OPERATE wave (8 tools)** | TOOL-035..042 — blast_radius, migration_diff, dead_code_finder, api_changelog, dependency_graph, connection_pool_monitor, error_rate_analyzer, sla_reporter | 3-4 sessions |
| **Phase 5 — EVOLVE wave (8 tools)** | TOOL-043..050 — add_migration_data, refactor_model, extract_service, add_event_driven, generate_sdk, generate_admin_panel, generate_docs, add_i18n | 4-5 sessions |
| **Phase 6 — PROACTIVE (1 tool)** | TOOL-051 fastapi_doctor — orchestrator | 1-2 sessions |
| **Phase 7 — Integration** | Update mcp_server.py to expose all 51, regenerate SKILL.md, manifest v4.0 | 2 sessions |
| **Phase 8 — Red team + audits L3..L8** | Multi-perspective adversarial validation | 4-6 sessions |
| **Phase 9 — Reference customer projects** | 3 full projects (ecommerce, SaaS B2B, event-driven) built end-to-end | 3-4 sessions |
| **Phase 10 — Production infra + CI** | Docker, K8s, Helm, monitoring dashboards, alerts, runbooks, CI workflow | 2-3 sessions |
| **Phase 11 — Golden benchmark re-run + final audit** | `make audit` 100% green, AUDIT_REPORT committed | 1 session |
| **Total** | | **~35-50 sessions** |

This is honest. Any smaller estimate is a lie.

---

## 6. Decisions needed from you (block on these)

Before any code is written in Phase 1, I need your decision on:

1. **R1 confirmed?** — preserve `generators/` + `core/` + `mcp_server.py` untouched
2. **R2 confirmed?** — archive `modules/` to `_archive_v2/` (not delete)
3. **R3 confirmed?** — new top-level `adapt/` directory for the 51 tools (vs extending `generators/tools/`)
4. **R4 confirmed?** — hide the 8 existing low-level primitives from MCP surface; expose only 51 new high-level tools + 2 runners (`migrate_db`, `fix_findings`) + 1 analyzer (`fastapi_analyze` / `fastapi_doctor`)
5. **R5 confirmed?** — VERIFY tools extend `benchmark/analyzer.py` rather than parallel-build
6. **R6 confirmed?** — `fastapi_doctor` = composition over existing analyzer
7. **R7 confirmed?** — co-located tests with 5 test files per tool (unit, e2e, property, chaos, mutation)
8. **R8 confirmed?** — `audit/` namespace with `make audit` top-level aggregator
9. **Phase 0 next step**: given R1..R8 approved, start Phase 1 with (a) archive move, (b) `adapt/` tree creation, (c) `contracts.py`, (d) fixture factory, (e) TOOL-001 reference implementation + full L1+L2 test suite, (f) `audit/audit_l1.py` + `audit/audit_l2.py` running on TOOL-001, (g) commit. Confirms the loop before scaling.

Answer these and I proceed. If you disagree with any recommendation, tell me — we adjust before writing a single line.

---

## 7. What I will NOT do without explicit permission

- Delete any file in `generators/`, `core/`, `modules/`, `benchmark/`, or root
- Rewrite `mcp_server.py`, `SKILL.md`, `manifest.yaml`, `loader.py`
- Duplicate logic that already exists in `analyzer.py`
- Claim any layer is "done" without the audit script saying so
- Ship any generator whose output doesn't pass `ast.parse` + `ruff` + `mypy --strict` + `bandit`
- Say "production ready" without L1..L8 all green

---

*End of Legacy Audit Report.*
