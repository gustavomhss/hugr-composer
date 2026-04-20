# Signed idempotent webhook receiver

## Background

A partner sends webhooks to our service. Deliveries may be duplicated
(at-least-once). Every webhook is HMAC-SHA256-signed with a pre-shared
secret. Processing a webhook increments a per-event-id counter on the
server — the counter represents a side-effect the partner must never
see double-applied.

The pre-shared secret is `s3cr3t-bench-key`. Signatures are hex,
computed as `HMAC_SHA256(secret, raw_request_body)` and sent in header
`X-Signature`.

## Requirements

1. `POST /webhook` — body is JSON `{"event_id": "<string>",
   "event_type": "<string>", "payload": {...}}`. On success:
   - First time for an `event_id`: HTTP 200 `{"applied": true,
     "count": 1}`.
   - Duplicate delivery of the same `event_id`: HTTP 200
     `{"applied": false, "count": 1}` (idempotent — count unchanged).
2. If the `X-Signature` header is missing OR its value does not match
   the HMAC of the raw body, return HTTP 401. The server MUST use a
   constant-time comparison (never leak timing).
3. `GET /events/{event_id}` — returns `{"event_id": "...", "count": N}`
   if the event was accepted, 404 otherwise.
4. `GET /events` — returns `{"events": [ ... ]}`, one entry per unique
   event_id accepted, with `{"event_id": "...", "count": N}`.
5. `GET /health` → 200 `{"ok": true}`.

## Acceptance criteria

- Valid signed request → 200 applied true. Same event_id re-sent →
  applied false, count unchanged.
- Tampered body (anything different from what was signed) → 401.
- Missing or wrong signature → 401.
- 200 concurrent deliveries of the SAME signed request → count is
  exactly 1, never 2 or more.
- Under 100 concurrent deliveries of 100 distinct event_ids → each
  count is exactly 1; total events accepted is 100.

## Non-requirements

- No persistence; in-process dict is acceptable.
- No admin UI.
- No rate limiting.
- No retries toward the sender.
