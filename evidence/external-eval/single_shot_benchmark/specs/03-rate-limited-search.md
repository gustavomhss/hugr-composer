# rate-limited-search

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: search endpoint with token-bucket rate limiting per API key.
60 requests/minute per key; burst of 10. 429 on overflow with
Retry-After header.]

## Acceptance criteria

- Request 1-60 within a minute return 200.
- Request 61 returns 429 with Retry-After header set.
- After Retry-After seconds, requests succeed again.
- Different API keys have independent buckets.

## Non-requirements

- No global rate limiting (per-key only).
- No tier-based limits at v1.
