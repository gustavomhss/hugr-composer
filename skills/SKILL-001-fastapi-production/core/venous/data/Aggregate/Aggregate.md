# Aggregate

## What it does (plain language)

Aggregate is the DDD transactional-consistency boundary for a cluster of
related entities. One root owns the invariants. External callers ONLY touch
the root. State changes go through commands on the root, which bump a
monotonic version and emit domain events. Cross-aggregate work is coordinated
through those events, not through shared references.

## Purpose

Define a consistency boundary around a cluster of entities and value objects
governed by a single root responsible for invariants.

## When to use and when NOT to use

- USE: any domain concept with local invariants that must hold together
  (Order + OrderLines, Account + Transactions, Cart + Items).
- DO NOT USE: read-only projections — use a dedicated read model.
- DO NOT USE: a single value with no invariants — use `ValueObject`.
- DO NOT USE: to stitch together two distinct aggregates in one transaction —
  emit a domain event and let the other side react.

## API surface

The catalog `api_signature` in `Aggregate.contract.json` is the authority.
The Protocol requires three members:

```python
class Aggregate(Protocol, Generic[ID]):
    @property
    def id(self) -> ID: ...
    @property
    def version(self) -> int: ...
    def pull_events(self) -> Iterable[object]: ...
```

The reference implementation `AggregateRoot` adds a `_mutate(apply, event=None)`
helper that subclasses call from command methods; it bumps the version, runs
`_check_invariants`, and rolls back to the prior snapshot on failure so
illegal intermediate states CANNOT be exposed (AGG-INV-03).

## Invariants

| ID | Rule |
|---|---|
| AGG_INV_01 | Only the aggregate root MUST be referenced from outside the aggregate; external references to internal children are FORBIDDEN. |
| AGG_INV_02 | A single transaction MUST modify at most one aggregate instance; cross-aggregate changes SHALL be coordinated via domain events. |
| AGG_INV_03 | All invariants defined by the root MUST hold at the end of every public method; intermediate illegal states CANNOT be exposed. |
| AGG_INV_04 | The aggregate version NEVER decreases and MUST increment on every state-changing operation for optimistic concurrency. |
| AGG_INV_05 | External collaborators SHALL reference other aggregates by identifier only, NEVER by object reference. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Lifecycle state machine

| State              | Public methods allowed               | Produces           |
|--------------------|--------------------------------------|--------------------|
| constructed (v=1)  | any command                          | OrderPlaced event  |
| mutated (v>1)      | any command, `pull_events`, save     | domain events      |
| saved (repo owned) | read via `repo.get`; further cmds OK | none until mutated |

On any command failure the aggregate snapshots + restores, so the state
machine never has an "illegal" node — only legal ones.

## Thread and async safety

- `AggregateRoot._mutate` serialises mutations with an internal RLock; the
  snapshot + check + restore sequence is atomic with respect to other
  commands on the same instance.
- `pull_events` atomically swaps the pending buffer with an empty list.
- `InMemoryAggregateRepository` uses a separate lock to linearise `save`
  calls and compare versions before overwriting stored state.
- One aggregate instance MUST NOT be shared across concurrent requests in
  production; each request reconstructs the aggregate from storage.

## Operational characteristics (for SRE)

- Version bumps fire on every successful command; a sustained rise in
  `aggregate.concurrency.conflicts` is the primary symptom of a misbehaving
  client re-using stale snapshots.
- `aggregate.invariant.violated` logs carry `invariant_id`; a spike on
  AGG-INV-03 usually means input validation upstream is letting illegal
  commands through.
- Event drains happen inside `save`; publishers therefore only see events
  for committed state.

## Security considerations

- Cross-aggregate object references are rejected at the boundary via
  `require_identifier_reference` (AGG-INV-05). Reviewers MUST flag any
  command argument typed as another `AggregateRoot`.
- Internal children (`_OrderLine`, etc.) never leave the root. Projections
  are immutable tuples; callers CANNOT mutate aggregate state via them.
- Rollback on failure preserves only object references, not memory pages —
  do not rely on it for secret scrubbing.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans — *Domain-Driven Design* (2003), Chapter 6, Aggregates, pp. 125–140.
  - Vernon — *Implementing Domain-Driven Design* (2013), Chapter 10,
    Aggregates, pp. 347–396.

## Alternatives considered and rejected

- Transaction-per-operation anemic domain — loses invariant enforcement and
  pushes rules into services, scattering them across the codebase.
- Whole-graph aggregates — every write touches the same giant root; locks
  become a contention hot-spot and transactions oversized.
- Entity-only modelling without roots — ambiguous ownership of invariants;
  two developers each fix the same rule in different places and drift apart.

## Extension contract

New aggregate types subclass `AggregateRoot`, override `_check_invariants`
to install domain rules, and add command methods that call `self._mutate`
with an `apply` closure and an optional `event`. Subclasses MAY override
`_snapshot` / `_restore` to capture and restore additional mutable state.
The version-bump and event-drain semantics MUST NOT be overridden.

## Usage

```python
def place_order(repo: InMemoryAggregateRepository[str], order_id: str, customer_id: str) -> list[object]:
    order = OrderAggregate(order_id, customer_id)
    order.add_line("SKU-A", 2)
    order.add_line("SKU-B", 1)
    return repo.save(order)  # returns drained domain events
```

## Compose with:

- **Transactional consistency** → `Repository` + `UnitOfWork`
  All mutations to the aggregate flow through the root and commit atomically through the UoW — no child entity can be modified outside the root's invariants.

- **Immutable inner model** → `ValueObject` + `Specification`
  Aggregate state is composed of value objects; selection predicates are Specifications — the internal structure never leaks as ORM types.

- **Event-sourced commits** → `DomainEvent` + `TransactionalOutbox`
  Each aggregate change emits a domain event; the outbox guarantees the event ships if and only if the state change committed.
