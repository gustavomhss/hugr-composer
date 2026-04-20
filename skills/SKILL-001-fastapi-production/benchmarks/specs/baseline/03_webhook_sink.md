# Inbound webhook sink

## Requirements

- Single endpoint `POST /webhooks/{provider}` receives third-party events.
- Each request carries an HMAC signature in a header; reject mismatches.
- Reject requests whose timestamp drifts more than ±5 minutes from the server clock.
- Duplicate deliveries of the same event id must be processed exactly once.
- Persist every accepted event for later replay and audit.

## Acceptance criteria

- Unsigned or bad-signature requests return 401 without executing business logic.
- Two deliveries of the same event id in any order result in exactly one downstream effect.
- The stored event record contains: provider, event_id, received_at, signature_verified flag, and raw body.
- Under concurrent duplicate deliveries (10 parallel POSTs of the same event), exactly one succeeds and nine are short-circuited.

## Non-requirements

- No outbound webhooks to other systems.
- No admin UI for replay; replay is a CLI or script.
- No per-tenant signing keys — one key per provider is fine.
- No SLA around acknowledgment latency beyond "under 1 second at 100 rps".
