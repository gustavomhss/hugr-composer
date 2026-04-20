# Lock-free reads with strictly serializable writes

## Requirements

- Read path MUST never acquire any lock, even for its own consistency — p99 read latency must not regress when write load doubles.
- Write path MUST be strictly serializable: writers see each other's effects in a single total order.
- A reader must never see a partial write (torn read across fields).
- Writers can be rejected under contention but readers must not be.
- No stale reads older than 100 ms.

## Acceptance criteria

- A continuous reader under 10× write-contention shows no increase in tail latency compared to read-only baseline.
- Concurrent writers racing on the same record produce a single winner; the loser receives a retryable error.
- A field-level integrity check on any read returns a self-consistent tuple (no torn state).
- Reads issued 100 ms after a write observe the write.

## Non-requirements

- No multi-key transactions — single-record writes only.
- No user-facing UI; a client library with retry is fine.
- No cross-region consistency.
- No audit log of reads.
