# HuGR Skills

Production-grade AI skill library. Each skill is a collection of MCP tools
that transform how LLMs write code — Convention over Configuration.

## What is a Skill?

A skill is an executable knowledge module: Method + Knowledge + Technique + Tools.
Instead of prompting an LLM to "write a FastAPI app," you call a skill tool that
produces verified, production-grade code. The LLM customizes only the business logic.

**Key insight:** Haiku + SKILL outperforms naked Opus at 25x lower cost.

## Skills

### SKILL-001: FastAPI Production

Convention over Configuration for FastAPI. 100 EXTEND tools covering every
production concern: auth, CRUD, payments, ML serving, policy engines,
real-time, background jobs, security, resiliency, observability, and more.

| Metric | Value |
|--------|-------|
| Benchmark score | 35/35 (100%) |
| vs. tiangolo (42.5K stars) | 100% vs 69% |
| EXTEND tools | 100 |
| Adapt tools total | 123 (extend + verify + operate + evolve + proactive) |
| Generators | 52 |
| MCP tools total | 175 |
| Unit + behavior tests | 3,000+ |
| Property checks | 984 (123 tools x 8 properties) |
| Formal specs | 73 (16 sections each) |
| E2E scenarios | 12 domain archetypes (real HTTP flows) |
| Cross-composition | 200+ tool combination scenarios |
| Soak test | 16K requests / 0 errors / 5 min |

No FastAPI template in the ecosystem scores above 69%. This skill scores 100%.

```python
# Generate a complete production project
fastapi_generate_project(
    output_dir="/tmp/my-api",
    name="my-api",
    models={"Product": {"name": "str", "price": "Decimal", "stock": "int"}},
    owner_models={"Product": "user"},
)

# Add features modularly
fastapi_add_stripe_subscription(project_dir="/tmp/my-api")
fastapi_add_ml_model_server(project_dir="/tmp/my-api")
fastapi_add_cedar_policies(project_dir="/tmp/my-api")
```

#### Tool Categories

| Category | Count | Examples |
|----------|-------|---------|
| CRUD & Data | 7 | soft_delete, pagination, search, bulk_ops, audit_log, export, upload |
| Auth & Access | 9 | tenancy, rbac, mfa, api_keys, oauth2, feature_flags/toggles, cedar, opa |
| Infrastructure | 16 | cache, circuit_breaker, rate_limit, celery, s3, health, stripe (3), email, notifications, scheduler, arq, temporal, sqladmin |
| Real-time | 5 | sse, webhook send/recv, websocket chat, presence |
| API Design | 5 | versioning, batch, graphql, long_running, graphql_subscriptions |
| ML Serving | 3 | model_server, gpu_inference, model_registry |
| Testing | 3 | contract_tests, factory, load_profile |

[Full details and tool catalog](skills/SKILL-001-fastapi-production/SKILL.md)

## Quick Start

```bash
cd skills/SKILL-001-fastapi-production
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mcp.txt

# Start the MCP server
PYTHONPATH=. python3 -m mcp_tools.server
```

## Verification

```bash
cd skills/SKILL-001-fastapi-production
source .venv/bin/activate

# Full CI (10 suites)
./ci.sh              # with PostgreSQL (Docker)
./ci.sh --no-pg      # without PostgreSQL

# Unit + behavior tests
PYTHONPATH=. python3 -m pytest adapt/ -q

# Property tests (8 properties x 123 tools)
PYTHONPATH=. python3 tests/property_tests.py

# E2E (12 scenarios, SQLite)
PYTHONPATH=. python3 tests/test_e2e_hardcore.py

# Cross-composition (200+ combos)
PYTHONPATH=. python3 tests/test_cross_composition.py

# Soak (5 min sustained load)
PYTHONPATH=. python3 tests/test_soak.py --duration 300

# Benchmark
PYTHONPATH=. python3 benchmarks/run_finhealth.py
```

## Repository Layout

```
skills/
  SKILL-001-fastapi-production/
    SKILL.md              # Skill spec + tool catalog
    EXPANSION_ROADMAP.md  # Expansion roadmap
    adapt/                # 123 adapt tools (100 EXTEND)
    generators/           # 34 project generators
    specs/                # 64 formal specifications
    tests/                # Full test infrastructure
    mcp_tools/            # MCP server + auto-discovery
    ci.sh                 # Local CI (10 suites)
    benchmarks/           # Compliance benchmark
tools/                    # Shared tooling
examples/                 # Usage examples
```
