# Serializable multi-key swap with sub-millisecond freshness

## Background

A counter service hosts N named counters. Clients occasionally
**swap** two counters atomically (set their values to each other's
previous value). Reads must see **serialized** outcomes — the sum
`sum(counters)` is invariant under swaps, and any `GET /state` must
be a coherent snapshot corresponding to a point in the operation
history.

Additionally, the service exposes `GET /state?stale_ms=<int>`:
callers can declare their freshness tolerance. The response MUST
include `as_of_ms_ago` — a non-negative int not exceeding
`stale_ms` (unless the service is overloaded, in which case it
returns 503).

## Requirements

1. `POST /counters` — body `{"name": "<string>", "value": <int>}`.
   Creates a counter.
2. `POST /incr` — body `{"name": "<string>", "delta": <int>}`.
3. `POST /swap` — body `{"a": "<string>", "b": "<string>"}`. Atomic
   swap: `counters[a], counters[b] = counters[b], counters[a]`. Sum
   invariant: `sum(counters.values())` is unchanged by every swap.
4. `GET /state?stale_ms=<int>` — returns `{"counters": {...},
   "total": <int>, "as_of_ms_ago": <int>}`. `as_of_ms_ago` MUST be
   ≤ `stale_ms`; default `stale_ms=1`.
5. Under ANY mix of concurrent /swap + /incr + /state requests:
   - `sum(counters.values()) == sum_at_creation + sum_of_all_deltas`
     (invariant).
   - No /state response shows a counter value that the history
     never produced ("phantom").
6. `GET /health` → 200.

## Acceptance criteria

- After 200 concurrent swaps across 10 counters + 200 concurrent
  incrs of mixed deltas, the sum invariant holds exactly.
- `GET /state?stale_ms=1` returns `as_of_ms_ago ≤ 1` in at least 80%
  of calls under 100 parallel readers.
- /state outputs during a swap storm are always self-consistent
  (no swap half-applied).
- /swap with unknown counter name → 404.
- Never returns 500.

## Non-requirements

- No persistence.
- No distributed layer.
- No formal serializability proof; empirical passes are sufficient.
