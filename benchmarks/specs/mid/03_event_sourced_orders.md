# Event-sourced order service

## Requirements

- An order's lifecycle is modeled as a sequence of events (`OrderPlaced`, `PaymentAuthorized`, `Shipped`, `Delivered`, `Returned`).
- The current state of an order is derived by folding events; no mutable state table.
- The system emits integration events to downstream consumers when an order transitions state.
- Consumers can subscribe to a topic and replay from any offset.
- Failed handlers MUST NOT drop events; they land in a recovery queue for manual re-run.

## Acceptance criteria

- Given the same event log, the derived order state is identical on any node (pure fold).
- A downstream consumer that crashes mid-handler sees the event redelivered on restart.
- A publisher that crashes between "write to store" and "publish to topic" still delivers the event to subscribers after restart (no lost events).
- Replaying from offset 0 reconstructs the exact same derived state as was computed live.

## Non-requirements

- No snapshots / compaction — full replay is acceptable.
- No support for order modification after placement (cancel/return are their own events).
- No multi-region replication.
- No GraphQL API.
