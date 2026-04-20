# Event-sourced orders with transactional outbox

## Background

An e-commerce ordering service stores orders as an **event stream**:
every state change is an append-only event (`OrderCreated`,
`ItemAdded`, `OrderConfirmed`, `OrderCancelled`). The current state of
any order is derived by folding the events for that `order_id`.

Downstream systems (warehouse, billing) must be notified whenever an
order changes. The notification path is AT-LEAST-ONCE via an internal
**outbox**: every state-change event is atomically stored both in the
order's stream and in a separate outbox table. A poller drains the
outbox.

## Requirements

1. `POST /orders` — body `{"customer_id": "<string>"}`. Returns 201
   with `{"order_id": "<uuid>", "status": "open"}`. Emits
   `OrderCreated` (appended to the order stream AND to the outbox).
2. `POST /orders/{id}/items` — body `{"sku": "<string>",
   "quantity": <int>}`. Returns 200 with current order summary.
   Emits `ItemAdded`.
3. `POST /orders/{id}/confirm` — transitions `open` → `confirmed`.
   Idempotent: confirming an already-confirmed order returns the same
   response without emitting a duplicate `OrderConfirmed`.
4. `POST /orders/{id}/cancel` — transitions `open` → `cancelled`. A
   confirmed order MUST NOT be cancellable (422).
5. `GET /orders/{id}` — returns `{"order_id", "status", "items": [...],
   "version": <int>}`. `version` is the count of events applied.
6. `GET /orders/{id}/events` — returns `{"events": [...]}` — ALL
   events for that order, in append order.
7. `GET /outbox` — returns `{"pending": [...]}` — outbox entries not
   yet marked as delivered.
8. `POST /outbox/drain` — returns `{"drained": <int>}` — marks every
   pending outbox entry as delivered. After a drain, `GET /outbox`
   returns `{"pending": []}`.
9. **Invariant**: the count of events in `GET /orders/{id}/events`
   equals the count of outbox entries (pending + delivered) for that
   order. No lost events, no duplicated outbox entries.
10. `GET /health` → 200 `{"ok": true}`.

## Acceptance criteria

- Create → add items → confirm → events show the full history.
- Cancelling a confirmed order → 422.
- Confirm replay (same order): returns ok both times; only ONE
  `OrderConfirmed` event in the stream.
- Under 100 concurrent `POST /orders` the number of unique order_ids
  emitted equals 100 AND the outbox has exactly 100 `OrderCreated`
  entries (no lost events, no duplicates).
- Version is monotonically increasing per order.

## Non-requirements

- No persistence across restart.
- No actual external broker; the outbox POST just marks delivered.
- No authentication.
