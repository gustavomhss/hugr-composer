---
name: fastapi-production
description: HuGR SKILL-001 — scaffolds AND customizes production-grade FastAPI backends. Rails-style 3-layer kit (skill + slice tools + primitives) invokable via MCP.
version: 0.1.0-phase-0
---

# SKILL-001 — FastAPI Production

> **Architecture, philosophy, and success criteria live in
> [`/PRODUCT.md`](../../PRODUCT.md). Current state + roadmap live in
> [`/ROADMAP.md`](../../ROADMAP.md). Binding execution rules live in
> [`/CONTRACT.md`](../../CONTRACT.md).**
>
> This file describes what THIS skill contains, right now, verifiably.

## Skill scope

Production-grade FastAPI backend. The Maestro invokes this skill to
scaffold a project tree, then uses slice tools to add capabilities
(auth, CRUD, payments, realtime, ...), and composes primitives directly
when a capability doesn't match any slice tool.

## On-disk counts (machine-verified)

| Surface | Count | Verify |
|---|---:|---|
| Macro generators | 34 | `find generators -name '*.py' -not -name '__init__.py' \| wc -l` |
| Slice tools (`adapt/extend/`) | 100 | `find adapt/extend -name 'add_*.py' \| wc -l` |
| Production primitives | 97 | `find core/venous -name '*.manifest.json' \| grep -v _extracted \| wc -l` |
| Staged primitives (extracted pool) | 432 | `find core/venous/_extracted -maxdepth 2 -type d \| wc -l` (subtract namespace dirs) |
| Quarantined (domain-coupled extracts) | 122 | `find core/venous/_extracted/_quarantine -maxdepth 1 -type d \| wc -l` |
| Opus audits completed | 97 | audit batches 1-20 + misc (50+ real bugs fixed) |

Re-verify any number with the shown command. The contract-check tool
(below) automates it.

## How the Maestro uses this skill

1. **Discovery.** MCP client lists tools via `tools/list`. All slice
   tools under `adapt/extend/` carry an `MCP_TOOL` metadata block and
   are auto-discovered.
2. **Scaffold.** Maestro calls a macro generator (e.g.
   `fastapi_generate_project`) to lay down the tree.
3. **Capability adds.** Maestro calls one or more slice tools
   (`add_stripe_webhook`, `add_rbac`, ...) to mutate the scaffold.
4. **Customize.** Where no slice tool fits exactly, Maestro composes
   primitives directly — import `core.venous.<ns>.<Name>` into the
   generated code.

**Gap acknowledged:** as of Phase 0, slice tools do NOT yet import
primitives. The Rails-analogy promise (tools thin over primitives)
is Phase 1 work. See
[CONTRACT.md §B1.3](../../CONTRACT.md).

## Tool categories (adapt/extend)

| Folder | Tools | Example |
|---|---:|---|
| `auth_access/` | 14 | `add_rbac`, `add_oauth2_provider`, `add_mfa`, `add_social_login` |
| `crud_data/` | 9 | `add_cursor_pagination`, `add_event_sourcing`, `add_soft_delete` |
| `api_design/` | 7 | `add_api_versioning`, `add_graphql`, `add_long_running_task` |
| `infrastructure/` | 52 | `add_stripe_webhook`, `add_rate_limiting`, `add_saga`, `add_retry_budget` |
| `realtime/` | 5 | `add_sse`, `add_websocket_chat`, `add_presence` |
| `testing_tools/` | 10 | `add_data_seeder`, `add_schema_evolution_guard`, `add_api_fuzzer` |

## Primitives (core/venous/<ns>/)

Each primitive directory contains:
- `<Name>.py` — impl (mypy --strict + ruff curated-ALL clean)
- `<Name>.contract.json` — verbatim catalog PrimitiveSpec
- `<Name>.md` — narrative spec with invariant citations
- `<Name>.tla` + `.cfg` — TLA+ formal spec (stateful primitives)
- `<Name>.manifest.json` — signed delivery manifest (10-tier gate pass)
- `invariant_bindings.json`, `observability_schema.json`, `dashboard.json`
- `test_<Name>.py`, `behavioral_<Name>.py`, `metamorphic_<Name>.py`,
  `chaos_<Name>.py`, plus `state_machine_`/`concurrent_` for stateful

Full index by namespace/concern ships in
`engine/primitives_by_concern.yaml` (Phase 1 deliverable).

## Running the MCP server

```bash
cd skills/SKILL-001-fastapi-production
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mcp.txt
PYTHONPATH=. python3 -m mcp_tools.server
```

A hermetic installation flow for an end user is a Phase 4 deliverable
([CONTRACT.md §B4.1](../../CONTRACT.md)).

## Contract enforcement

```bash
# Run the contract checker from skill root
PYTHONPATH=. python3 -m engine.audit.contract_check

# Or one phase at a time
PYTHONPATH=. python3 -m engine.audit.contract_check --phase 0
```

Exits 0 iff every machine-checkable CONTRACT.md item passes. CI
integration mandatory from Phase 0 onward.

## Tests

Per-primitive: `pytest core/venous/<ns>/<Name>/`.
Cross-skill aggregate tests (integration, soak, cross-composition) are
Phase 3 deliverables — the test files that claim 3000+ tests / 200+
cross-composition scenarios in prior README drafts are aspirational and
currently do not have a passing run on record. See
[ROADMAP.md Phase 0 §6](../../ROADMAP.md).

## What this file used to say (for the record)

Prior SKILL.md versions claimed 175 MCP tools, 3000+ tests, 35/35 audit,
200+ cross-composition scenarios. Those claims outran the code on disk
by a 1.5-2× margin. As of 2026-04-19, numbers in this file are
machine-verifiable via the commands shown above.

---

Signed: Gustavo Schneiter — 2026-04-19 — Phase 0 ground-truth pass.
