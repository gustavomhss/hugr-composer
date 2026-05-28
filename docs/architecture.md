# Architecture

HuGR Arsenal is a **code-generation toolkit / meta-framework** delivered over MCP and
gated by a license API. The architecture mirrors mature code generators (JHipster,
Yeoman, OpenAPI Generator), not the apps it emits. See [ADR-0001](adr/0001-architecture.md).

> **Status: TARGET STATE.** The per-tool directory layout (`<tool>/__init__.py` +
> `templates/*.py.tmpl`) and the shared `adapt/_base/` phases below describe where the
> refactor (Work Packages in [`wp/`](wp/)) lands the code. The current tree still uses
> flat tool modules with inline emitted code (e.g. `add_multi_tenancy.py`). The
> hexagonal core + plugin model + modular-monolith packaging are already in place.

## Layers
```
┌──────────────────────────────────────────────────────────────┐
│ adapt/extend/<category>/<tool>/    plugin compose tools (99) │
│   discover() → plan() → write() → patch() → verify()         │
├──────────────────────────────────────────────────────────────┤
│ adapt/_base/                       shared discover/patch/render│
│ adapt/contracts/                   ToolInput / ToolResult     │
├──────────────────────────────────────────────────────────────┤
│ generators/                        scaffold pipeline          │
├──────────────────────────────────────────────────────────────┤
│ engine/audit/                      contract / compose verifier│
├──────────────────────────────────────────────────────────────┤
│ core/venous/<domain>/              HEXAGON: framework-agnostic│
│   _ports/                          port interfaces            │
│   _adapters/fastapi/               driven adapters            │
└──────────────────────────────────────────────────────────────┘
                              ▼
                  emitted FastAPI project
```
Separate service: `hugr_auth/` (license + MCP gate). Deploy: `deploy/`.

## Key invariants
- **Hexagonal**: `core/venous` knows nothing about FastAPI; only `_adapters/fastapi` does.
  This is what allows emitting other frameworks later (add an adapter, not a rewrite).
- **Plugin tools**: every `add_*` follows the single contract in [`tool-contract.md`](tool-contract.md).
- **Phased pipeline**: discover/plan/write/patch/verify — no per-tool ad-hoc discovery.
- **Templates externalized**: emitted code lives in `templates/*.py.tmpl`, never inline strings.
- **Modular monolith**: one repo, bounded modules, in-process. MCP+license is the one
  separate service.

## Composition is where bugs live
A "surgical" change to tool X can break tool Y when they compose. The product's value IS
composition, so the gates that matter are composition gates, not unit isolation:
- `tests/test_p0_regression_gates.py` — GATE 1 (emitted pytest stays green after compose) +
  GATE 2 (no raw-SQL interpolation in emitted code).
- `tests/test_boot_chains.py`, `tests/test_e2e_hardcore.py`, `tests/test_behavior_scenarios.py`.

These run via `scripts/verify.sh` in tiers (see [contributing.md](contributing.md)).
