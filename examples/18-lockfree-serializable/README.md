# Example 18 — Lock-free reads + strictly serializable writes

**Tier:** adversarial · **Benchmark spec:**
`adversarial/03_conflicting_primitives_lockfree_serializable.md`

Readers never acquire a lock. Writers race via compare-and-swap; one wins,
the other gets a retryable error. Readers always see a self-consistent
snapshot — no torn state. Demonstrates the **`OptimisticConcurrency` +
`UnitOfWork`** recipe (Phase-3 primitives for this conflict).

## What this example shows

- Continuous reads under 10× writer contention: no lock acquisitions.
- Concurrent writers on the same record: one winner, one retryable error.
- Reads always return a self-consistent tuple (no torn multi-field read).
- Reads 100 ms after a write observe the write.

## How to run

```bash
cd examples/18-lockfree-serializable
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_cas_record_store`       | CAS-on-revision record store.                   |
| `fastapi_add_snapshot_read`          | Lock-free snapshot-read endpoint.               |
| `fastapi_add_writer_retry_hint`      | 409 Retry-After on optimistic conflict.         |

## Primitives imported

| Primitive                | Role                                                |
| ------------------------ | --------------------------------------------------- |
| `OptimisticConcurrency`  | Compare-and-swap on record revision.                |
| `UnitOfWork`             | Write+publish atomic commit; reject on mismatch.    |
| `IdentityMap`            | Per-session load cache for repeat reads.            |
| `Repository`             | Collection-like interface over one aggregate.       |
| `AuditEvent`             | Record every write with (who, before, after).       |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
