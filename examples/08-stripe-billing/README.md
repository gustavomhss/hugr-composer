# Example 08 — SaaS with Stripe billing

**Tier:** mid · **Benchmark spec:** `mid/01_saas_with_stripe_billing.md`

Plans, Stripe webhooks, and a 7-day past-due grace window. Demonstrates the
**`SignatureVerifier` + `IdempotentConsumer` + `RetentionPolicy`** recipe.

## What this example shows

- Duplicate webhook deliveries for the same Stripe `event_id` update state once.
- Webhooks with a bad HMAC signature return 401 without mutating state.
- Plan changes land on the server via webhook — no per-request Stripe polling.
- 7-day past-due grace job is idempotent: running it twice the same day does
  not double-notify the user.
- Cancellation sets `cancel_at_period_end`; premium access ends at period end.

## How to run

```bash
cd examples/08-stripe-billing
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_webhook_sink`           | HMAC-verified Stripe webhook endpoint.          |
| `fastapi_add_idempotency`            | Dedup on Stripe `event_id`.                     |
| `fastapi_add_billing_grace_period`   | 7-day past-due → read-only transition job.      |
| `fastapi_add_cancel_at_period_end`   | Deferred cancellation through period boundary.  |

## Primitives imported

| Primitive              | Role                                                 |
| ---------------------- | ---------------------------------------------------- |
| `SignatureVerifier`    | HMAC check over webhook body.                        |
| `InboundVerifier`      | Turns raw (body, headers) into a `VerifiedEvent`.    |
| `IdempotentConsumer`   | At-most-once handler per Stripe `event_id`.          |
| `RetentionPolicy`      | Drives the 7-day past-due grace clock.               |
| `AuditEvent`           | Each state change recorded with actor + reason.      |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
