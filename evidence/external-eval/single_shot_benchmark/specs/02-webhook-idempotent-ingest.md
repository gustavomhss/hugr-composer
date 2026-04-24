# webhook-idempotent-ingest

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: webhook receiver from a 3rd-party that retries on timeout.
Idempotency key in `Idempotency-Key` header; same key + same body =
cached response; same key + different body = 409.]

## Acceptance criteria

- A POST `/webhook` returns 202 + correlation id.
- Same Idempotency-Key + same body returns the cached 202 (not duplicate processing).
- Same Idempotency-Key + different body returns 409 with body fingerprint.
- Idempotency entries are visible for 24h then expire.

## Non-requirements

- No signature verification at v1 (separate spec).
- No rate limiting.
