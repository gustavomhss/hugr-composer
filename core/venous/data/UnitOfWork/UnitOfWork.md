# UnitOfWork

## What it does (plain language)

UnitOfWork is the transactional-boundary primitive for every domain write. It
tracks which domain objects were created, changed, or removed during one piece
of business work and flushes them to storage as a single atomic commit — or
throws everything away with a rollback if anything goes wrong. One commit, one
rollback, no partial writes.

## Purpose

Track object changes during a business transaction and flush them to storage
as one atomic commit or rollback.

## When to use and when NOT to use

- USE: any domain write touching more than one aggregate, or any sequence of
  writes that must succeed or fail together (bank transfer, order placement,
  inventory adjustment with event emission).
- DO NOT USE: a single idempotent upsert with no cross-aggregate rules — use
  the repository directly.
- DO NOT USE: read-only workflows — UnitOfWork carries only write intent.

## API surface

The catalog `api_signature` in `UnitOfWork.contract.json` is the authority.
Callers open the unit with the context-manager protocol, register changes with
`register_new`, `register_dirty`, `register_removed`, and call `commit()` at
the end of the successful path. On any exception inside the `with` block the
unit rolls back and discards every pending change. Repositories living inside
the unit enlist their mutations (`EnlistingRepository.add`, `.mark_dirty`,
`.remove`) rather than writing directly to storage.

## Invariants

| ID | Rule |
|---|---|
| UOW_INV_01 | A successful commit MUST flush every registered new/dirty/removed object as one atomic transaction; on any exception the unit MUST rollback. |
| UOW_INV_02 | The same object instance SHALL NEVER be registered in more than one of (new, dirty, removed) within one unit. |
| UOW_INV_03 | A UnitOfWork instance CANNOT be reused after commit or rollback; a fresh unit MUST be opened for the next transaction. |
| UOW_INV_04 | Context-manager semantics ALWAYS drive lifecycle; on exception the unit MUST rollback so leaks on error paths are impossible. |
| UOW_INV_05 | Repositories operating inside a unit MUST enlist their mutations with that unit; direct writes bypassing the unit are FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `InMemoryUnitOfWork` serialises bucket mutations via an internal lock so
  concurrent registrations preserve disjointness.
- `commit()` snapshots the buckets under the lock and flushes outside the
  lock; application code called from flush therefore CANNOT deadlock on the
  unit's own lock.
- A unit is scoped to one logical transaction and MUST NOT be shared across
  concurrent requests. The `IdentityMap` primitive enforces the same scoping
  on the read side.

## Operational characteristics (for SRE)

- Flush failures ALWAYS roll back and re-raise; the caller sees the original
  exception unwrapped.
- The default `flush_fn` is a no-op — production deployments wire it to the
  ORM session's `flush()` + `commit()` pair, or to raw SQL inside a
  driver-level transaction.
- Self-observability: `uow.commits` (counter, `result` label), `uow.bucket.size`
  (histogram, `bucket` label), `uow.flush.duration` (histogram, ms).
- A sustained rise in `uow.commits{result="rolled_back"}` is the primary
  symptom of a noisy upstream or a flaky storage backend.

## Security considerations

- The unit stores object references, not serialised copies. Callers MUST NOT
  register objects that contain secrets and then rely on rollback for
  sanitisation — rollback clears references but NOT memory pages.
- `EnlistingRepository.direct_write` ALWAYS raises; this is the contract that
  stops ad-hoc bypass writes. Reviewers MUST flag any repository that does
  not route mutations through the unit.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Fowler — *Patterns of Enterprise Application Architecture* (2002),
    Chapter 11, Unit of Work pattern, pp. 184–194.
  - Vernon — *Implementing Domain-Driven Design* (2013), Chapter 12,
    Repositories + Unit of Work collaboration, pp. 416–419.

## Alternatives considered and rejected

- Auto-commit per repository call — trades atomicity for simplicity and
  breaks multi-aggregate invariants.
- Session-per-request middleware only — implicit boundaries hide rollback
  semantics from the caller.
- Manual BEGIN/COMMIT in each tool — duplicates logic and diverges on error
  handling.

## Extension contract

Downstream tools extend UnitOfWork by subclassing `InMemoryUnitOfWork` or by
registering new flush-phase hooks (`register_before_commit`,
`register_on_commit`, `register_after_commit`). The existing order of
inserts / updates / deletes MUST remain intact; hooks run outside that order
but CANNOT reorder the bucket flush itself.

## Schema of `UnitOfWork.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
def transfer(uow: InMemoryUnitOfWork, src: Account, dst: Account, amount: int) -> None:
    with uow as u:
        src.debit(amount)
        dst.credit(amount)
        u.register_dirty(src)
        u.register_dirty(dst)
        u.commit()
```

## Compose with:

- **Transactional consistency** → `Repository` + `IdentityMap`
  Every mutation enlists with the active UoW; the identity map holds the in-flight graph; a rollback leaves memory and storage aligned.

- **Outbox in the same tx** → `TransactionalOutbox` + `DomainEvent`
  Domain events written to the outbox commit with the state change; the relay publishes them out-of-band — at-least-once delivery without dual writes.

- **Request-scoped lifetime** → `LifetimeScope` + `DiContainer`
  UoW is resolved per request by the container; pipeline exit triggers commit or rollback — handlers never forget to close a transaction.

- **Multi-key atomic CAS** → `OptimisticConcurrency` + `RetryPolicy`
  A `UnitOfWork` batches several `OptimisticConcurrency.compare_and_swap` writes and rolls back the entire batch on any conflict; `RetryPolicy` replays the whole UoW under backoff. Invariant gained: multi-key consistency without distributed transactions.
