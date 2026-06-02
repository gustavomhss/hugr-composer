# `core/venous/_ports/` — Formal Hexagonal Port Boundary

> Per ADR-0001 (hexagonal core + plugin pattern). WP-15 phase 1.
> This README is the **single source of truth** for the boundary.
> The machine-checkable counterpart is [`CATALOG.json`](./CATALOG.json).

## Purpose

`core/venous/_ports/` is a **type-only** package: every file under
this tree is a `typing.Protocol` definition with method bodies
limited to the `...` ellipsis stub. Concrete behaviour lives in
adapters (`core/venous/_adapters/`) and the registered primitives
(`core/venous/<ns>/<Name>/<Name>.py`). The port directory exists so
that:

1. **Adapters** can be type-checked against a stable Protocol surface
   instead of an auto-inferred stub that drifts when implementations
   change.
2. **Compose tools** in `adapt/_base/` and `adapt/extend/` can
   consume a Protocol-typed contract rather than importing a concrete
   primitive — restoring the inward-pointing arrow that ADR-0001
   promises (adapters depend on ports; ports depend on nothing).
3. **Tests** can use `@runtime_checkable` ports to assert adapter
   conformance with one line:
   `isinstance(my_adapter, CommandBusProtocol)`.

## Phase 1 scope (this WP) — what is here, what is not

| Deliverable | Status |
|---|---|
| `_ports/` directory + per-namespace `__init__.py` × 15 | shipped |
| Hand-authored port for `api/CommandBus` | shipped |
| Hand-authored port for `api/QueryBus` | shipped |
| Machine-checkable catalog of 124 registered primitives | shipped — [`CATALOG.json`](./CATALOG.json) |
| Catalog derivation procedure | shipped — [`docs/CATALOG.md`](./docs/CATALOG.md) §"Derivation procedure" |
| Compat shim in `core/venous/api/CommandBus/__init__.py` | shipped (one re-export line) |
| Compat shim in `core/venous/api/QueryBus/__init__.py` | shipped (one re-export line) |
| Hand-authored ports for the other 122 primitives | **NOT** in this WP — phase 2 |
| Migrating adapters to depend on `_ports/` | **NOT** in this WP — phase 3 |
| Migrating compose tools to consume `_ports/` | **NOT** in this WP — phase 3 |
| Deleting the auto-inferred `<Name>.protocol.py` stubs | **NOT** in this WP — phase 4 |

`docs/CATALOG.md` lists the phasing in full.

## Directory shape

```
core/venous/_ports/
├── __init__.py                # top-level — no symbols, no side-effects
├── README.md                  # this file
├── CATALOG.json               # machine-readable catalog (124 entries)
├── docs/                       # narrative docs (repo md-location rule)
│   ├── CATALOG.md              # narrative catalog
│   └── COMPAT_SHIM_PLAN.md     # alias/compat shim phasing plan
├── api/
│   ├── __init__.py            # re-exports CommandBusProtocol, QueryBusProtocol
│   ├── CommandBus.py          # exemplar #1 — hand-authored Protocol
│   └── QueryBus.py            # exemplar #2 — hand-authored Protocol
├── auth/__init__.py           # empty (no exemplars in phase 1)
├── billing/__init__.py        # empty
├── cache/__init__.py          # empty
├── compliance/__init__.py     # empty
├── data/__init__.py           # empty
├── events/__init__.py         # empty
├── extras/__init__.py         # empty
├── flags/__init__.py          # empty
├── jobs/__init__.py           # empty
├── llm/__init__.py            # empty
├── obs/__init__.py            # empty
├── policy/__init__.py         # empty
├── resiliency/__init__.py     # empty
└── security/__init__.py       # empty
```

The `cost` namespace (`core/venous/cost/`) ships zero registered
primitives per INVENTORY.md and is therefore **not** mirrored under
`_ports/`. The §1 owned-files list of the WP-15 manifest deliberately
omits `_ports/cost/`; a future WP that promotes a `cost` primitive
will introduce the sub-package at that point.

## Import contract

### Canonical (new) path

```python
from core.venous._ports.api import CommandBusProtocol, QueryBusProtocol
```

### Legacy (pre-WP-15) path — still resolves via compat shim

```python
from core.venous.api.CommandBus import CommandBusProtocol
from core.venous.api.QueryBus  import QueryBusProtocol
```

Both paths resolve to the **same** Protocol object — verified by gate 2
in WP-15 §6 (`L is N` identity check). `isinstance(impl, CommandBusProtocol)`
returns the same value regardless of which path the caller used.

The compat shim is documented in WP-15 §11; the gist:

```python
# core/venous/api/CommandBus/__init__.py — one re-export line:
from core.venous._ports.api.CommandBus import CommandBusProtocol  # noqa: F401
```

No `__getattr__` magic, no `TYPE_CHECKING` gating — a plain re-export
that satisfies both runtime imports and static type-checkers.

## Port-conformance test plan (analog of P1 #15)

WP-15 ships **no** compose tool, so the P1 #15 emitted-tests mandate
becomes a *plan* — what tests will prove the boundary is real and
stays real. Three checks are owned by WP-15 phase 1 and run via the
WP §6 gates; two are deferred to follow-up port-consumer WPs.

| # | Check | Owner | Status |
|---|---|---|---|
| 1 | Catalog completeness — re-derive 124 entries and diff against `CATALOG.json` | WP-15 | runnable via WP-15 §6 — `find` invocation in `docs/CATALOG.md` derivation procedure |
| 2 | Type-only AST audit — every file under `_ports/` parses to a Protocol with `...` bodies and nothing else | WP-15 | runnable via WP-15 §6 + §10 D-11 |
| 3 | Compat-shim `is`-check — legacy and new paths return the same Protocol object | WP-15 | runnable via WP-15 §6 gate 2 |
| 4 | Adapter-conformance — `isinstance(adapter, <Port>)` for each adapter implementing a port | follow-up WP (phase 3) | deferred — needs an adapter migrated to consume `_ports/` first |
| 5 | Compose-tool conformance — consumed surface of `_ports/` stays stable across WPs | follow-up WP (phase 3) | deferred — needs first compose tool consumer |

Conformance test files are NOT created in this WP. The §1 write
surface excludes `tests/` and excludes adding a `conftest.py` under
`_ports/`. Per WP-15 §5 STOP-and-report rule: phase 1 is deliberately
conservative — the plan above is the test surface; the tests
themselves are queued for the WP that first wires `_ports/` into a
runtime consumer.

## Why exemplar-only (not all 124)

The architecture decisions baked into a port — directory location
(`_ports/` vs `ports/`), Protocol vs ABC, `runtime_checkable` policy,
naming convention (`<Name>Protocol`), empty-namespace handling — need
to survive contact with a *real* downstream consumer before being
applied 124 times. Two ports that already share a bus-style shape
exercise the relevant patterns; the remaining 122 are catalogued so
the next WP can re-derive them deterministically.

If the tech lead prefers a different exemplar pair (e.g.
`IdempotencyStore` + `RequestContext` to seed the data namespace),
that is a STOP-AND-ASK per WP-15 §9 F-05 — phase 1 does not
re-author exemplar ports speculatively.

## Cross-reference

- WP manifest: [`docs/wp/WP-15-hexagon-ports.md`](../../../../../docs/wp/WP-15-hexagon-ports.md)
- ADR: `docs/adr/0001-architecture.md` (hexagonal core + plugin)
- INVENTORY (source of truth for the 124 count): [`INVENTORY.md`](../../../INVENTORY.md) §5
- Consumer-shape reference: `skills/SKILL-001-fastapi-production/adapt/_base/` (read-only here)
