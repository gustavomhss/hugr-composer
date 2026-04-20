# ContextMap

## What it does (plain language)

A **ContextMap** is a live, programmatically enforceable catalog of every
BoundedContext in your system and the *kind* of integration relationship
between each pair. It turns "tribal knowledge about which team owns the
translation" into an object with invariants — so architecture diagrams stop
rotting and shadow integrations stop sneaking in.

### One-minute mental model (junior-friendly)

- A **BoundedContext** is a named slice of the domain with its own model
  (e.g., *Orders*, *Billing*, *Catalog*, *Ledger*). It is *not* a microservice;
  it's a model boundary. Multiple services can live inside one context; one
  context can span multiple services.
- Two contexts **always** interact via one of eight canonical relationship
  kinds (Evans DDD Ch.14, Vernon IDDD Ch.3):
  - **Partnership** — two teams succeed or fail together; they coordinate
    changes bidirectionally.
  - **Shared Kernel** — a small, jointly-owned subset of the model is shared.
  - **Customer-Supplier** — downstream depends on upstream; upstream agrees
    to prioritise downstream needs. Directional.
  - **Conformist** — downstream just accepts whatever upstream publishes
    because it has no leverage.
  - **Anticorruption Layer (ACL)** — downstream wraps the upstream model in
    a translation layer to insulate itself.
  - **Open Host Service** — upstream publishes a stable protocol designed
    for many downstream consumers.
  - **Published Language** — a well-documented shared interchange format
    (often paired with Open Host).
  - **Separate Ways** — the two contexts deliberately do not integrate.
- **Why keep them on a live map?** Because without it, producers change
  contracts without notifying downstream, ownership of translations is
  ambiguous, and your C4 diagram in Confluence is always three months stale.

### Glossary

- **BoundedContext** — a named model boundary with a single consistent
  ubiquitous language inside it.
- **Shadow integration** — an integration that exists in production but is
  not recorded on the ContextMap. CTXMAP-INV-03 is designed to surface these
  the moment a lookup happens.
- **Directional cycle** — a cycle in the subgraph restricted to
  Customer-Supplier edges. Forbidden because it implies "everyone is
  everyone else's boss", which collapses the governance model.
- **Promotion** — upgrading a would-be-cyclic Customer-Supplier edge to a
  Partnership, which is symmetric and therefore has no cycle semantics.

### Hello, world

```python
from ContextMap import InMemoryContextMap

m = InMemoryContextMap()
m.add_relationship("Catalog", "Orders", "Published Language")
m.add_relationship("Orders",  "Billing", "Customer-Supplier")
m.add_relationship("Legacy-ERP", "Ledger", "Anticorruption Layer")

m.relationship("Orders", "Billing")         # -> "Customer-Supplier"
list(m.contexts())                          # -> ['Billing', 'Catalog', 'Legacy-ERP', 'Ledger', 'Orders']
list(m.integrations())                      # -> [(u, d, kind), ...] sorted
```

## Purpose

Catalogs every BoundedContext and the integration relationship (Partnership,
Customer-Supplier, Conformist, Open Host, etc.) between each pair, so
integration governance is *enforceable* rather than documentary.

## When to use and when NOT to use

- USE: any system with more than two teams, any microservice migration, any
  platform aspiring to publish stable APIs to many consumers.
- USE: during an architecture review — the map tells you exactly which edges
  need an ACL and which consumers are Conformist (and therefore brittle).
- DO NOT USE: as a runtime service discovery mechanism — ContextMap records
  *governance*, not live endpoints. Pair it with a registry for that.
- DO NOT USE: to model intra-context module dependencies — it is specifically
  a *between-contexts* artefact.

## API surface

The catalog `api_signature` is the sole authority; see
`ContextMap.contract.json` for the verbatim Protocol declaration. The
reference `InMemoryContextMap` exposes:

| method | purpose |
|---|---|
| `contexts()` | Iterate over registered context names (sorted, tuple-stable). |
| `relationship(upstream, downstream)` | Return the kind of a registered edge; raise CTXMAP-INV-03 if shadow. |
| `add_relationship(upstream, downstream, kind)` | Single mutator — enforces INV-01/02/03/04 before committing. |
| `integrations()` | Iterate `(upstream, downstream, kind)` triples (sorted). |
| `version` *(introspection)* | Monotonic audit counter; bumps iff a mutation succeeds. |
| `has_edge(u, d)` *(introspection)* | Boolean probe without raising. |

## Canonical relationship kinds (CTXMAP-INV-01)

`RELATIONSHIP_KINDS` is a `frozenset` of exactly eight strings. Any other
value is rejected loudly with CTXMAP-INV-01. Downstream consumers MUST NOT
redefine these; they MAY register new *additional* kinds via the
extension contract, but the eight canonical kinds are immutable.

## Invariants

| ID | Rule |
|---|---|
| CTXMAP_INV_01 | Every pairwise integration between contexts MUST be classified by one of the canonical relationship kinds; ad-hoc or blank relationships are FORBIDDEN. |
| CTXMAP_INV_02 | The graph of contexts SHALL be acyclic for Customer-Supplier relationships; a cycle CANNOT be introduced without promotion to Partnership. |
| CTXMAP_INV_03 | A BoundedContext CANNOT participate in an integration absent from the ContextMap; shadow integrations MUST be surfaced. |
| CTXMAP_INV_04 | Relationship changes ALWAYS require an explicit mutation through add_relationship so history is auditable. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding. The chaos and
behavioral suites exercise the same invariants under storm and workflow
conditions respectively.

## Thread and async safety

- `InMemoryContextMap` is intended for single-process catalog use. The
  reference implementation is not internally locked; callers that need
  concurrent mutation should wrap `add_relationship` with a lock or delegate
  to a transactional store. Lookups (`relationship`, `integrations`,
  `contexts`, `has_edge`) are read-only and safe for parallel reads
  provided no writer is active.
- CTXMAP-INV-02's cycle detector runs in O(V+E) per insertion (DFS over the
  Customer-Supplier subgraph). For maps under ~10k contexts this is
  sub-millisecond — see the `contextmap.cycle.detection.duration` histogram.

## Operational characteristics (for SRE)

- `contextmap.relationships.added` (counter, labelled by kind) and
  `contextmap.relationships.rejected` (counter, labelled by invariant_id)
  are the core SLI metrics.
- `contextmap.mutation.version` reflects the audit counter; monotonic
  increase proves CTXMAP-INV-04 is honoured.
- `contextmap.cycle.detection.duration` is the key performance gauge;
  alert if p95 exceeds the target (default: 5 ms) — a spike means the map
  has grown unexpectedly dense.
- `contextmap.shadow.integration.refused` events are security-relevant:
  any spike signals a caller attempting to use an unregistered integration,
  which is often an ACL migration gap.

## Security considerations

- **Shadow integrations** are the primary attack surface: a service that
  talks to another context without a registered edge bypasses the
  governance layer. CTXMAP-INV-03 fires loudly on lookup — wire it into
  request interceptors to short-circuit unknown integrations.
- **Name-injection**: context names are validated (length ≤ 80, no control
  characters, no leading/trailing whitespace) so the map cannot be
  poisoned with collision-prone variants like `"Orders\u00a0"` vs `"Orders"`.
- **Audit trail**: the `version` counter is append-only; persistence layers
  SHOULD treat it as a write-once sequence number and cross-check against
  any external event log of map changes.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans, *Domain-Driven Design* (2003), Chapter 14 *Context Map*,
    pp. 344–366.
  - Vernon, *Implementing Domain-Driven Design* (2013), Chapter 3
    *Context Maps*, pp. 83–134.

## Alternatives considered and rejected

- **Architecture diagrams in Confluence** — rot quickly, are not
  programmatically enforceable, and cannot prevent shadow integrations.
- **Service catalog with no relationship kind** — records existence but
  not governance; you still can't answer "does this edge need an ACL?"
- **ADRs only** — chronicle decisions retrospectively but do not expose
  live topology; violations are found months after the fact.

## Extension contract

New integration kinds extend ContextMap by registering a relationship-kind
plugin with translation and governance semantics; existing canonical kinds
SHALL NOT be redefined by downstream consumers. Extensions MUST preserve
the four invariants above. Semver: the Protocol surface is v1; adding new
relationship kinds is additive and does not break consumers, but removing
or redefining one of the eight canonical kinds is a breaking change.

## Schema of `ContextMap.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec) for the
governing standards.

## Usage

```python
def needs_acl(m: ContextMap, upstream: str, downstream: str) -> bool:
    kind = m.relationship(upstream, downstream)
    return kind in {"Conformist", "Anticorruption Layer", "Customer-Supplier"}
```

## Compose with:

- **Customer/supplier integration** → `BoundedContext` + `AntiCorruptionLayer`
  ContextMap declares the relationship; the ACL enforces it at runtime so upstream vocabulary never leaks into the downstream model.

- **Published-language contract** → `DomainEvent` + `OutboundBinding`
  The map names which contexts publish vs consume domain events; OutboundBinding is the single adapter surface honoring that direction.

- **Conformist drift detection** → `BoundedContext` + `AntiCorruptionLayer`
  When an upstream context changes its schema, the ACL is the one seam that fails fast — the context map tells you which downstream teams to page.
