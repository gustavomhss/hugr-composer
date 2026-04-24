# orders-event-sourced

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: order processing with full event sourcing. Every state
transition emits an event; current state is reduceable from event log.
Idempotent state machine: PLACED → PAID → SHIPPED → DELIVERED.]

## Acceptance criteria

- POST `/orders` returns 201 + order_id + state=PLACED.
- POST `/orders/{id}/events {type:PAY}` transitions to PAID.
- POST `/orders/{id}/events {type:PAY}` again returns 409 (already paid).
- GET `/orders/{id}/events` returns the chronological event log.

## Non-requirements

- No saga / compensation at v1.
- No event replay tooling beyond GET.
