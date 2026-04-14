# HuGR Skills

Production-grade AI skill library. Each skill is a collection of MCP tools
that transform how LLMs write code — Convention over Configuration.

## What is a Skill?

A skill is an executable knowledge module: Method + Knowledge + Technique + Tools.
Instead of prompting an LLM to "write a FastAPI app," you call a skill tool that
produces verified, production-grade code. The LLM customizes only the business logic.

**Key insight:** Haiku + SKILL outperforms naked Opus at 25× lower cost.

## Skills

### SKILL-001: FastAPI Production

Convention over Configuration for FastAPI.
100 MCP tools (51 adapt + 49 generators) producing production-grade code.

| Metric | Value |
|--------|-------|
| Benchmark score | 100/100 (Grade A+) |
| vs. tiangolo (42.5K stars) | 100% vs 69% |
| Test suites | 18 suites |
| Unit tests | 1,280+ |
| Adapt tools | 51 (extend, verify, operate, evolve, proactive) |
| Generators | 49 |
| Generated project | 53 files, production-ready |
| LOC | 101,766 |

No FastAPI template in the ecosystem scores above 69%. This skill scores 100%.

```python
from mcp_server import fastapi_generate_project

fastapi_generate_project(
    output_dir="/tmp/my-api",
    name="my-api",
    models={"Product": {"name": "str", "price": "Decimal", "stock": "int"}},
    owner_models={"Product": "user"},
)
```

[Full details and tool catalog](skills/SKILL-001-fastapi-production/SKILL.md)

## Quick Start

```bash
# Install dependencies
cd skills/SKILL-001-fastapi-production
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mcp.txt

# Start the MCP server
PYTHONPATH=. python3 mcp_server.py

# Run the final audit (18 suites)
PYTHONPATH=. python3 audit/final_audit.py
```

## Verification

```bash
cd skills/SKILL-001-fastapi-production
source .venv/bin/activate

# All 18 suites + report
PYTHONPATH=. python3 audit/final_audit.py

# Unit tests only (1,280+)
PYTHONPATH=. python3 -m pytest adapt/ -q

# Benchmark (100-check compliance)
PYTHONPATH=. python3 benchmarks/run_finhealth.py
```

## Repository Layout

```
skills/
  SKILL-001-fastapi-production/
    SKILL.md          # Full skill spec and tool catalog
    adapt/            # 51 adapt tools + 1,280+ unit tests
    generators/       # 49 project generator tools
    benchmarks/       # 100-check compliance benchmark
    tests/            # Integration, E2E, property, boot tests
    audit/            # Audit layers + final_audit.py
    mcp_server.py     # MCP server entry point
tools/                # Shared tooling
```
