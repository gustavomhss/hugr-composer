# Causal event reorder under simulated broker partition

## Background

A service ingests events from an upstream broker that delivers
messages possibly out-of-order. Every event carries `(aggregate_id,
sequence)` where `sequence` is a monotonically increasing integer
per aggregate_id.

Downstream consumers must see events in STRICT causal order per
aggregate_id. Out-of-order arrivals must be BUFFERED until the gap
is filled. If a gap is not filled within 500ms (pre-registered
wall-clock budget), a `GapEvent` must be emitted and the consumer
proceeds.

## Requirements

1. `POST /events` — body `{"aggregate_id": "<string>",
   "sequence": <int>, "payload": {...}}`. Accepted sequences are
   non-negative integers. Returns 202 `{"buffered": <bool>,
   "delivered_count": <int>}`.
2. `GET /delivered/{aggregate_id}` — returns `{"events": [...]}` in
   delivered order. The first delivered event per aggregate_id is
   sequence 0.
3. Causal order invariant: within a single aggregate_id, events MUST
   be delivered in increasing sequence order. After a gap-event
   emission, delivery MUST resume at the next still-buffered
   sequence.
4. `GET /gaps/{aggregate_id}` — returns `{"gaps": [N1, N2, ...]}` —
   sequences for which a GapEvent was emitted.
5. `POST /broker/_partition` — body `{"duration_ms": <int>}`. While
   the broker is "partitioned" no events get delivered (they still
   arrive at the API but stay buffered). After duration ends,
   buffered events drain in causal order, gaps older than 500ms get
   GapEvents.
6. `GET /health` → 200.

## Acceptance criteria

- Send events for aggregate "X" in order 0,1,2 → /delivered/X has 3
  events in order; no gaps.
- Send 2 then 0 (out of order for agg "Y") → /delivered/Y shows
  [0, 2]? NO — the delivered order must be [0, 1 (gap), 2] or
  equivalently [0, 2] IFF sequence 1 had a gap event emitted. Check
  /gaps/Y contains 1.
- Send 5, 4, 3, 2, 1, 0 for aggregate "Z" → /delivered/Z ends up
  as [0, 1, 2, 3, 4, 5] in order, no gaps.
- 100 interleaved events across 20 aggregates with 10% random order
  → causal order holds per aggregate.
- Partition for 100ms does NOT lose any events (they all appear in
  /delivered or /gaps eventually).
- Never returns 500.

## Non-requirements

- No durable broker; all state is in-process.
- No persistence.
- No real network partitions.
