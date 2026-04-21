# ADR 0001 — SKILL-001 identity: FastAPI production scaffolder

Status: Accepted (2026-04-19, retroactive)
Relates to: PRODUCT.md §1, §2; CONTRACT.md §A10 (terminology lock)
Supersedes: none

> **Retroactive ADR.** The decision was made and shipped across 2026-Q1
> but never captured as a standalone record. Creating it here so the
> decision log is contiguous from 0001 onward and any future reviewer
> can reconstruct the choice.

## Context

HuGR SkillKit's first skill had to answer two questions before any code
landed:

1. **What framework / stack does SKILL-001 target?** The Maestro-facing
   surface (`fastapi_<domain>_<verb>_<noun>` canonical names, every
   primitive `.md` citing FastAPI conventions, every example app built
   on FastAPI) only makes sense if that framework is a first-class
   choice, not an accidental default.
2. **What is "in scope" for SKILL-001 vs deferred to SKILL-002+?**
   Without this line the skill grows unboundedly and every cross-cutting
   feature gets crammed in.

## Decision

- **Stack:** FastAPI (Python 3.11+), SQLAlchemy 2.x (async), Pydantic 2.x,
  Alembic for migrations. Ancillary: httpx as HTTP client, fastmcp as
  the MCP protocol server runtime. These pins live in
  `skills/SKILL-001-fastapi-production/requirements-mcp.txt` +
  `pyproject.toml`.
- **Identifier:** `SKILL-001-fastapi-production`. The `-production`
  suffix is load-bearing: this skill targets the hard production path
  (observability, auth, compliance, resiliency, deployment) — not a
  starter / demo variant. Starter variants, if ever shipped, go to
  `SKILL-001a-fastapi-starter/` or similar, never diluting the
  production surface.
- **Maestro-facing naming:** all tools use
  `fastapi_<domain>_<verb>_<noun>` with closed vocabularies
  (10 domains × 9 verbs). Locked via CONTRACT §A10 terminology rule.
- **Out of SKILL-001's scope:**
  - Front-end stacks (Next.js, React) — future SKILL-002 territory.
  - Non-Python backends (Django explicitly deferred — same concerns,
    different ergonomics, worth its own skill).
  - Agent frameworks / LLM-backend-specific scaffolders — that's an
    orthogonal axis and a separate skill.
  - Ops-only concerns (pure Terraform / Kubernetes scaffolders without
    an application) — HuGR's thesis is application-first scaffolding;
    pure-infra lives in another tool.

## Why FastAPI first (not Django, not Flask, not Starlette bare)

- **Type fluency.** Pydantic + type hints map cleanly to invariants
  expressible in our primitive contract schema (`contract.json` +
  `protocol.py`). Django's auto-generated forms / ORM leak framework
  assumptions we would have to scrub at every primitive boundary.
- **Async-first.** HuGR primitives rely on async semantics for
  concurrency primitives (Bulkhead, LoadShedder, RetryBudget).
  Retrofitting async into Flask/Django would have cost half a
  namespace.
- **Dependency-injection as first-class.** FastAPI's `Depends`
  composes cleanly with our adapter pattern (`_adapters/fastapi/`).
- **Community momentum (2025-2026).** FastAPI adoption in production
  Python backends has tracked upward; benchmark target users are
  disproportionately on it.

## Consequences

- The SKILL-001 name is frozen forever. Even if we later rewrite the
  skill against Litestar or a successor framework, that becomes
  `SKILL-003-litestar-production`, not a SKILL-001 v2.
- Every primitive ships framework-free, with optional FastAPI adapter
  under `_adapters/fastapi/` — see ADR 0003. This keeps the door open
  for SKILL-002 to reuse ≥ 30 primitives (CONTRACT §B6.2).
- Examples under `/examples/` are all FastAPI apps. A Django counterpart
  example lives in its own skill when SKILL-002 ships.

## Alternatives considered

- **Start framework-agnostic, pick per scaffold.** Rejected: the skill
  would have zero opinions at its Rails-analogous scaffold level and
  couldn't offer meaningful composition recipes.
- **Start with Starlette bare.** Rejected: too close to FastAPI without
  the ecosystem dividends.
- **Start with Django.** Rejected per "Why FastAPI first" above;
  revisited in a future ADR when SKILL-002 candidates are scored.
