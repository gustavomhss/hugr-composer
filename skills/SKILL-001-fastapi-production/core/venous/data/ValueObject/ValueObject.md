# ValueObject

## What it does (plain language)

A ValueObject is a small, immutable type whose identity is its *values*, not
its memory address. Two ValueObjects with the same attributes are
interchangeable: they compare equal, hash the same, and can be used as dict
keys or set members. Classic examples are `Money(amount_cents, currency)`,
`Email(address)`, and `DateRange(start, end)`. Domain code becomes dramatically
safer because each domain concept has one place where its invariants are
enforced, and mutation is impossible after construction.

## Purpose

Represents a descriptive concept whose identity is defined entirely by its
attributes and which is immutable once constructed.

## When to use and when NOT to use

- USE: monetary amounts, measurements, identifiers-by-shape (email, phone),
  spans (date range, version range), coordinates, colour, specification
  literals, audit-trail payloads.
- DO NOT USE: anything with a lifecycle (create / update / delete) — those are
  Entities or Aggregates. ValueObjects MUST NOT hold references to
  Aggregates (VO-INV-03); compose them *by value* instead.
- DO NOT USE: anything requiring mutation in place. If you find yourself
  wanting a setter, you want an Entity with a state transition method.

## API surface

The catalog `api_signature` is the sole authority; see
`ValueObject.contract.json` for the verbatim Protocol declaration. The
implementation `ValueObject.py` re-declares the Protocol and provides
`FrozenValueObject` as the reference base class, plus `Money`, `Email`, and
`DateRange` as domain-canonical worked examples. Every ValueObject is a
frozen, slotted dataclass: `__eq__` and `__hash__` are derived, and
`with_changes` returns a fresh, fully-validated instance via
`dataclasses.replace`.

## Invariants

| ID | Rule |
|---|---|
| VO_INV_01 | Instances MUST be immutable after construction; attribute assignment post-init is FORBIDDEN. |
| VO_INV_02 | Two instances with the same attribute values MUST compare equal and MUST share the same hash. |
| VO_INV_03 | A ValueObject CANNOT hold a reference to an Aggregate root or Entity whose identity is unstable. |
| VO_INV_04 | Construction SHALL validate every invariant eagerly; a partially-valid instance NEVER exists. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- Frozen dataclasses carry no per-instance mutable state, so concurrent
  *readers* and *constructors* are safe without locks. The chaos suite
  exercises 8 concurrent workers × 500 constructions.
- `with_changes` always produces a new object; there is no writer/reader race.
- The module-level `COUNTERS` object uses plain ints and increments non-
  atomically; it is instrumentation, not a synchronisation primitive. Under
  heavy concurrency the counter value may slightly under-count — that is
  documented and acceptable for its purpose (SRE dashboards, not correctness).

## Operational characteristics (for SRE)

- Construction is O(fields) and allocation-bound; no I/O, no locks.
- `with_changes` costs one allocation plus a full `__post_init__`
  re-validation.  This is intentional: it restores VO-INV-04 invariants for
  the new instance and cannot be shortcut.
- Self-observability: `valueobject.constructed.total`,
  `valueobject.with_changes.total`, `valueobject.validation.failures`. A
  sustained spike in `validation.failures` with a particular `invariant_id`
  label is the primary symptom of an upstream caller starting to send bad
  input.
- There are no failure modes *inside* the primitive: every failure is the
  caller's invariant violation, surfaced as
  `ValueObjectInvariantError(ValueError)`.

## Security considerations

- **PII handling**: several canonical ValueObjects (`Email`, future `Phone`,
  future `Address`) hold PII. Callers are responsible for classifying and
  redacting. The primitive does not auto-redact; redaction happens at the
  log / trace boundary.
- **Aggregate smuggling**: VO-INV-03 prevents embedding an Aggregate root or
  Entity (detected by the `_aggregate_id`, `_entity_id`,
  `__aggregate_root__`, `__entity__` marker attributes). This closes a
  common bug where a "snapshot" silently aliases a live, mutating entity.
- **Mutation via `object.__setattr__`**: frozen dataclasses with `slots=True`
  raise `FrozenInstanceError` / `AttributeError` on every write, so the
  standard bypass does not work. Exercised by the chaos suite.
- **Hash stability**: equal ValueObjects hash equally for the life of the
  process (VO-INV-02). This is sufficient for dict/set usage; it is not
  cryptographic.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans, *Domain-Driven Design* (2003), Chapter 5 "Value Objects",
    pp. 97–106.
  - Vernon, *Implementing Domain-Driven Design* (2013), Chapter 6 "Value
    Objects", pp. 219–240.
  - PEP 557 — *Data Classes* (field-level `frozen=True`).
  - PEP 412 — *Key-Sharing Dictionary* (slots hygiene for memory + attribute
    closure).

## Alternatives considered and rejected

- **Plain dicts or tuples** — rejected: lose validation and type safety;
  equality is structural but attribute names are gone, destroying readability.
- **Mutable dataclasses** — rejected: mutation breaks equality-by-value and
  invites aliasing bugs; `hash()` silently raises on mutable dataclasses.
- **Primitive obsession** — rejected: scatters validation across every
  consumer; defeats the point of a domain model.
- **`typing.NamedTuple`** — rejected: no eager per-field validation hook,
  no class-level invariant composition (`__post_init__` is not a thing),
  tuple-based equality reads awkwardly in domain code.
- **Pydantic `BaseModel(frozen=True)`** — acceptable for edge/DTO layers but
  unnecessary machinery for core domain values; adds a runtime dependency
  and a validation model per class. A `CoercionRegistry` handles
  serialisation at the boundaries without dragging pydantic through the
  domain.

## Extension contract

A downstream tool extends `ValueObject` by:

1. Subclassing `FrozenValueObject` with `@dataclass(frozen=True, slots=True)`
   and declaring the domain fields.
2. Overriding `__post_init__` to enforce class-specific invariants; the
   override MUST call `super().__post_init__()` so VO-INV-01/03 checks run.
3. Registering serialisation adapters with `CoercionRegistry.register(cls,
   to_mapping, from_mapping)` for the wire format.

Extensions MUST preserve the four invariants above. Adding derived fields via
`with_changes` is allowed; mutation in place is FORBIDDEN by the type
system and reaffirmed by VO-INV-01.

## Schema of `ValueObject.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec) for the full
standards governing each field.

## Usage

```python
from ValueObject import Money

def apply_discount(price: Money, pct: int) -> Money:
    # with_changes returns a new, fully-validated Money — the original is
    # untouched (VO-INV-01) and the new instance obeys VO-INV-04.
    return price.with_changes(amount_cents=price.amount_cents * (100 - pct) // 100)

p = Money(amount_cents=10_000, currency="USD")
assert apply_discount(p, 20) == Money(amount_cents=8_000, currency="USD")
```

## Compose with:

- **Immutable domain state** → `Aggregate` + `Specification`
  Aggregates compose value objects; state changes replace them rather than mutate — invariants are checked at construction, once.

- **Validated hydration** → `InputValidator` + `DataMapper`
  Inbound payloads become value objects through the validator; the mapper re-emits them to storage — invalid state is unrepresentable at the type level.

- **Pure equality** → `Specification` + `DomainEvent`
  VO equality is structural, so event payloads and specification matches compare cleanly across processes — no hidden identity.
