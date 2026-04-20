# Maestro session — 08-stripe-billing

Plan-level transcript for `mid/01_saas_with_stripe_billing.md`.

## Requirement → kit mapping

1. **Duplicate event deliveries mutate state once.**
   → `IdempotentConsumer` keyed by Stripe `event_id`; second delivery is a no-op.
2. **Bad signature → 401, no mutation.**
   → `SignatureVerifier.verify(body, header, secret)`; mismatch raises before
     the handler runs.
3. **Plan changes land via webhook, not polling.**
   → `customer.subscription.updated` handler writes to the customer record;
     read path never calls Stripe.
4. **7-day past-due → read-only, idempotent job.**
   → `RetentionPolicy(ttl_days=7)` drives the transition clock; the job
     fingerprints `(customer_id, day)` so a second run is a no-op.
5. **Cancellation ends at period end.**
   → `cancel_at_period_end=True` flag; the subscription-deleted handler fires
     only when Stripe emits the terminal event.

## Tool call sequence

```
1. fastapi_generate_project(name="billing_svc")
2. fastapi_add_webhook_sink(provider="stripe", signature_header="Stripe-Signature")
3. fastapi_add_idempotency(key_source="event_id")
4. fastapi_add_billing_grace_period(grace_days=7)
5. fastapi_add_cancel_at_period_end()
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
