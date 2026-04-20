# BoundedContext

## What it does (plain language)

A BoundedContext is a named fence around one model and one shared vocabulary.
Everything inside the fence uses the same words with the same meanings, and
the same invariants apply. Nothing crosses the fence as a raw object — it
must be translated by an AntiCorruptionLayer and every integration with
another context must be registered on a ContextMap.

## Glossary (for readers new to DDD)

- **Aggregate** — a cluster of domain objects treated as a single unit for
  data changes. Always has one "root" object; the whole cluster is loaded,
  saved, and validated together.
- **Ubiquitous language** — the shared vocabulary a team uses for a given
  part of the domain. Inside one BoundedContext, every word has exactly one
  meaning.
- **AntiCorruptionLayer (ACL)** — a translator between two contexts so
  foreign ideas never leak into the local model. Inbound payloads are
  validated and converted before they touch local aggregates.
- **ContextMap** — a registry that lists every pair of contexts that talk
  to each other and the kind of relationship they have (Partnership,
  Customer-Supplier, Conformist, Open Host, ACL).
- **Maturity: battle_tested** — this primitive has passed all 10 tier gates
  (static, behavioral, formal TLA+, state-machine, metamorphic, concurrency,
  adversarial, observability, chaos, meta). You can rely on it in
  production without further ceremony.

## Five-minute walkthrough

A bank has two teams. The Sales team says "Customer" to mean a person who
buys things. The Billing team says "Customer" to mean an entity that
receives invoices. Same word, different meaning — exactly the situation
BoundedContext exists to solve.

1. Each team declares its own context: `SimpleBoundedContext("sales")`
   and `SimpleBoundedContext("billing")`.
2. Each team claims the Aggregate types it owns — `sales.claim(Order)`,
   `billing.claim(Invoice)`. The runtime ledger guarantees neither team
   can silently hijack the other's types.
3. Each team defines its own glossary: `sales.define_term("customer",
   "...")` and `billing.define_term("customer", "...")`. Re-defining the
   word inside the same context fails loudly (BC-INV-03); defining it
   differently across contexts is fine — that is the whole point.
4. When Billing needs to react to a Sales event, Billing registers an
   AntiCorruptionLayer and calls
   `billing.publish_integration(sales, "Customer-Supplier", direction="upstream", translator=acl)`.
   The relationship shows up on the shared ContextMap, and raw Sales
   objects can never cross into Billing.

## Purpose

Declare the explicit linguistic and model boundary within which one
ubiquitous language and one set of invariants apply.

## When to use and when NOT to use

- USE: whenever two parts of a system use the same word for two different
  things (e.g. "Customer" in Sales vs. Billing), or when ownership of an
  Aggregate type is ambiguous across teams or services.
- DO NOT USE: for purely technical layering (persistence, transport). A
  BoundedContext is a **domain** boundary, not a deployment boundary.
- DO NOT USE: when the codebase is small enough for one team to hold the
  whole ubiquitous language in their head — the primitive adds ceremony
  without clarifying anything.

## API surface

The catalog `api_signature` in `BoundedContext.contract.json` is the
authority. Callers:

- Register aggregate ownership with `claim(aggregate_type)` — fails if the
  type is already owned by another context (BC-INV-01).
- Add glossary entries with `define_term(term, meaning)` — fails if the term
  already has a different meaning (BC-INV-03).
- Declare integrations with `publish_integration(other, kind, translator=...)`
  — records the edge on the shared `ContextMap` (BC-INV-04) and attaches an
  `AntiCorruptionLayer` when the kind demands translation (BC-INV-02).
- Send cross-context payloads through `forward(other, payload,
  local_types=(...))` which refuses raw local objects.

## Invariants

| ID | Rule |
|---|---|
| BC_INV_01 | Every Aggregate type MUST be owned by exactly one BoundedContext; shared ownership across contexts is FORBIDDEN. |
| BC_INV_02 | Cross-context calls MUST pass through an AntiCorruptionLayer or a published-language schema; raw object sharing is NEVER permitted. |
| BC_INV_03 | The ubiquitous language of a context SHALL be locally consistent: one term CANNOT carry two meanings inside the same BoundedContext. |
| BC_INV_04 | A BoundedContext ALWAYS exposes its integration points through a ContextMap relationship (Customer-Supplier, Conformist, Partnership, Open Host). |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Relationship kinds

`CANONICAL_RELATIONSHIPS` contains the canonical Evans/Vernon kinds:

- **Partnership** — two contexts succeed or fail together; no ACL required.
- **Customer-Supplier** — downstream consumes upstream; translator required.
- **Conformist** — downstream conforms to upstream's model; translator
  required so the local model still owns its shape.
- **Open Host** — upstream publishes a language for many downstreams; the
  downstreams attach their own ACLs.
- **Anticorruption Layer** — explicit translator-only relationship.

## Thread and async safety

- `_OwnershipLedger` serialises claim/release under a lock so concurrent
  claims produce exactly one winner per `(aggregate_type, ledger)` pair.
- `SimpleBoundedContext` protects its language dictionary, aggregate-type
  set, and translator registry with an internal lock.
- `ContextMap` is thread-safe for both `add_relationship` and read paths.

## Operational characteristics (for SRE)

- A sustained rise in `bounded.context.ownership.conflicts{result="rejected"}`
  indicates either a deploy race (two services trying to claim the same
  aggregate type) or a design mistake (genuinely shared ownership — which is
  FORBIDDEN and must be refactored into two types or one owning context).
- `bounded.context.language.conflict` events are ALWAYS bugs: either a typo
  or a hidden re-definition. The runbook is to revert the offending commit,
  not tolerate the conflict.
- Integration graph size (`bounded.context.integrations`) tracks architectural
  coupling; an unbounded rise is a smell and warrants a context-mapping
  workshop.

## Security considerations

- The ledger is process-local by default; in multi-process deployments the
  authoritative map lives in a shared registry (database, service catalog).
  Callers wiring `SimpleBoundedContext` across processes MUST pass a shared
  `_OwnershipLedger` (or equivalent persistent registry) — otherwise two
  processes can each believe they own the same type.
- AntiCorruptionLayer implementations SHALL validate inbound foreign
  payloads (`guard`) before local aggregates see them. The reference
  `NoopAntiCorruptionLayer` is a TEST double only — do NOT ship it.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans — *Domain-Driven Design* (2003), Chapter 14, Bounded Context,
    pp. 335–346.
  - Vernon — *Implementing Domain-Driven Design* (2013), Chapter 2,
    Domains, Subdomains, Bounded Contexts, pp. 43–80.

## Alternatives considered and rejected

- One canonical enterprise model — impossible to keep consistent at scale
  and collapses under concurrent change.
- Per-service ad hoc boundaries — no shared vocabulary for integration
  policy.
- Database-schema-as-boundary — couples physical storage to logical
  context.

## Extension contract

New domains are introduced by subclassing `SimpleBoundedContext` (or
implementing the `BoundedContext` Protocol directly) and registering
translator adapters for each upstream or downstream neighbor. Redefining an
existing context's language in place is FORBIDDEN — the extension MUST
declare a new context.

## Schema of `BoundedContext.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from BoundedContext import (
    REL_CUSTOMER_SUPPLIER,
    NoopAntiCorruptionLayer,
    SimpleBoundedContext,
)

sales = SimpleBoundedContext("sales")
billing = SimpleBoundedContext("billing", context_map=sales.context_map)

class Order: ...
class Invoice: ...

sales.claim(Order)
billing.claim(Invoice)

sales.define_term("order", "a customer purchase")
billing.define_term("order", "an invoice line reference")  # different context — OK

# Billing depends on sales as a customer — translation required.
acl = NoopAntiCorruptionLayer()  # real ACL in production
billing.publish_integration(
    sales, REL_CUSTOMER_SUPPLIER, direction="upstream", translator=acl,
)
```

## Compose with:

- **Language isolation** → `Aggregate` + `ValueObject`
  Inside the context, one term means one thing; aggregates and value objects are named in the context's ubiquitous language without qualifiers.

- **Explicit integration** → `ContextMap` + `AntiCorruptionLayer`
  Every cross-context call routes through an ACL named in the context map — silent cross-context imports are prevented at the module boundary.

- **Published events** → `DomainEvent` + `TopicBus`
  Events emitted by a context form its published language; other contexts subscribe through the bus and translate via their own ACL.
