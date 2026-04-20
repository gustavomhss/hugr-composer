# Rate-limited public API

## Requirements

- Public REST API key'd by a per-caller API key.
- Each API key has a plan (free / pro) with different per-minute and per-day quotas.
- When a caller exceeds quota, respond 429 with headers indicating `X-RateLimit-Remaining` and `Retry-After`.
- During traffic spikes, the service must shed low-priority load to protect p99 latency.
- API key usage is metered for billing.

## Acceptance criteria

- Under 100 concurrent callers on the free plan, every successful response carries correct remaining-quota headers.
- Exceeding quota returns 429 with `Retry-After` pointing to the quota-reset timestamp.
- With `/priority/high` and `/priority/low` endpoints and 2× capacity in flight, low-priority requests are shed first and high-priority p95 stays below target.
- A counter dump at end-of-day accurately reflects successful calls per key (idempotent read).

## Non-requirements

- No OAuth or user accounts — API keys only.
- No endpoint for callers to view their usage; CLI export is fine.
- No dynamic per-tenant quotas; plans are fixed.
- No regional rate limits.
