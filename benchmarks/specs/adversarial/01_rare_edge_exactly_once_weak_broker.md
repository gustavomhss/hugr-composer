# Exactly-once delivery on a best-effort broker

## Requirements

- The app publishes events to a broker that only guarantees at-least-once and may deliver out of order.
- Downstream consumers MUST observe each logical event exactly once, in the original causal order per aggregate.
- The app runs on multiple replicas; any replica may handle any inbound request.
- An outage that corrupts the broker's offset store must not cause double-processing after recovery.

## Acceptance criteria

- Under 100× artificially injected duplicate deliveries, the downstream side effect runs exactly once per logical event.
- Out-of-order arrivals are buffered and handed to the consumer in causal order; a stuck predecessor eventually times out and triggers a recorded gap.
- After a simulated offset-store corruption, recovery does not replay any event whose side-effect already landed in the idempotency store.

## Non-requirements

- No change to the broker — it remains at-least-once.
- No global total order across aggregates.
- No cross-datacenter replication.
- No UI to inspect the dedup store; a CLI is fine.
