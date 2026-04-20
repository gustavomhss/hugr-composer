# BatchCore

**Namespace:** `api`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/api_design/add_batch_endpoint.py`

## Purpose

`BatchCore` is the async executor behind a generic batch endpoint: it
takes a list of items, a per-item handler, a processing strategy
(sequential / parallel), and an isolation mode (all-or-nothing /
best-effort), and returns a list of per-item results aligned to the
input order.

## Invariants

- **BATCH_CORE_INV_01** — Result alignment: `len(results) == len(items)`
  and `results[i]` corresponds to `items[i]`, regardless of completion
  order.
- **BATCH_CORE_INV_02** — All-or-nothing rollback: the first failure
  (status ≥ 400) stops processing and all subsequent items receive a
  409 rollback placeholder.
- **BATCH_CORE_INV_03** — Bounded parallelism: the semaphore limits
  simultaneous handler invocations to `max_parallel` in the parallel
  strategy.

Tests: see `test_BatchCore.py`.

## Compose with:

- **Idempotent batch endpoint** → `IdempotencyStore` + `RequestShape`
  Client sends a retry of the same batch with the same idempotency key; the store returns the cached per-item result set and BatchCore never re-invokes any handler.

- **Bounded parallelism** → `Bulkhead` + `TimeoutBudget`
  Per-item semaphore + inherited deadline: a slow item cannot expand beyond its share of the pool or survive past the request's budget.

- **All-or-nothing transactional batch** → `UnitOfWork` + `TransactionalOutbox`
  Failure stops processing; UoW rolls back; the outbox never emits events for items that didn't commit — downstream consumers see a coherent batch or no batch.
