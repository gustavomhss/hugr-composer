# OptimisticConcurrency

## What it does (plain language)

A compare-and-swap store. You `read(key)` and get back `(value, version)`;
you compute a new value; you `compare_and_swap(key, version, new_value)`.
If anyone else wrote to that key in between, the version no longer
matches and you get a `ConcurrencyError` — retry cleanly at the caller.
No torn reads, no lost updates, no hidden retries.

## Purpose

CAS write pattern — write fails cleanly when the stored version changed
since the reader last saw it. The caller decides retry policy externally.

## When to use and when NOT to use

- USE: update flows where conflict is rare (user profile edits, order
  state transitions, settings writes).
- USE: as the storage half of a Unit-of-Work pattern.
- DO NOT USE: high-contention counters — use `ShardedCounter` instead.
- DO NOT USE: as the full "retry on conflict" mechanism — pair with a
  retry primitive; this primitive MUST NOT hide retries (OC_INV_02).

## API surface

`OptimisticConcurrency.contract.json` is the authority. `read(k)` is
safe to call on missing keys — it returns `(None, 0)` (OC_INV_05). The
version is zero for "never written". `compare_and_swap` returns the new
version on success and raises `ConcurrencyError` on mismatch.

## Invariants

| ID | Rule |
|---|---|
| OC_INV_01 | `compare_and_swap` atomically checks old_version and writes OR raises — no partial update. |
| OC_INV_02 | Writer MUST retry on conflict ONLY via the retry primitive (no hidden retry here). |
| OC_INV_03 | Version is monotonic and gap-free per key (next = prev + 1). |
| OC_INV_04 | Readers never observe a torn write (read returns value atomic with its version). |
| OC_INV_05 | `read(k)` of an unknown key returns `(None, 0)` — canonical empty, never raises. |

## Invariant -> test mapping

`test_OptimisticConcurrency.py` has `test_inv_<slug>_{confirms,prevents}`
pairs for each invariant.

## Thread and async safety

- Reference impl serializes CAS through a single `threading.Lock`. Reads
  and writes are mutually exclusive — no torn reads.
- Real adapters rely on the underlying store's CAS primitive:
  Postgres `UPDATE ... WHERE version = $1 RETURNING version`, Redis
  WATCH/MULTI/EXEC, DynamoDB conditional writes. The Protocol is
  unchanged.

## Operational characteristics (for SRE)

- `oc.cas_conflict` (counter, labels: key) — conflict rate per key;
  hot keys surface here before latency degrades.
- `oc.read_latency_ms` (histogram) and `oc.cas_latency_ms` (histogram)
  bound the CAS path; hot-key contention inflates CAS latency long
  before conflict count spikes.
- No warmup required — the store is empty and all reads return `(None, 0)`.

## Security considerations

- Version numbers are internal tokens; callers MUST NOT forge them.
- An attacker who can read-then-write faster than the app is not attacking
  CAS — they are the legitimate writer, by definition. Rate-limit reads
  at the edge.
- `compare_and_swap` validates input types before touching the store —
  malformed keys raise rather than corrupting the version counter.

## Provenance

- Primary source: SQLAlchemy versioning docs —
  https://docs.sqlalchemy.org/en/20/orm/versioning.html
- Pattern is classical database optimistic concurrency (Bernstein &
  Goodman, 1981). Reference impl is stdlib-only.

## Alternatives considered and rejected

- Pessimistic row-level locking — serializes writers even when they
  would not conflict; wastes throughput.
- Last-writer-wins — silently loses updates; unacceptable for billable
  / auditable state.
- Append-only event store — different semantics; appropriate when every
  write is a domain event but too heavy for settings / profiles.

## Extension contract

Adopters MAY substitute a persistent backend — Postgres, Redis,
DynamoDB, etc. — as long as they preserve OC_INV_01..05. The version
counter representation is integer per the Protocol; stores that use
timestamps or UUIDs MUST wrap them in an adapter that exposes the
integer contract.

## Usage

```python
store = InMemoryOptimisticConcurrency[dict]()
value, version = store.read("user:42")  # (None, 0) on first call
try:
    new_version = store.compare_and_swap("user:42", version, {"name": "Ada"})
except ConcurrencyError:
    # Let a retry primitive handle this.
    raise
```

## Compose with:

- **Bounded retry loop** → `RetryPolicy` + `AuditEvent`
  `RetryPolicy` wraps the CAS write with a budgeted exponential-backoff
  retry; each conflict is appended to the audit trail for forensic
  review. Invariant gained: lost-update bugs surface as retry-budget
  exhaustions, not silent data loss.

- **Atomic unit of work** → `UnitOfWork` + `AuditEvent`
  A `UnitOfWork` batches several CAS writes into one logical commit;
  on any CAS conflict the whole UoW rolls back and the retry primitive
  replays the full unit. Invariant gained: multi-key consistency without
  distributed transactions.

- **Audit-first CAS** → `UnitOfWork` + `RetryPolicy`
  The audit record is written within the same UoW as the CAS write;
  either both land or neither. Combined with `RetryPolicy`, the retry
  replays the audit entry along with the data. Invariant gained:
  every state change is auditable with zero gap.
