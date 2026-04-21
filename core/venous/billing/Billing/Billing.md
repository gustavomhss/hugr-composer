# Billing

> Provider-agnostic billing gateway — Customer / Subscription lifecycle +
> webhook verification. Reference backend is ``InMemoryBilling``; real
> apps wire the Stripe / Paddle / Chargebee adapter.

## Purpose

Production FastAPI apps that charge money need two things from a billing
provider that the primitive makes explicit and testable:

1. A small, stable **operations surface** (create customer, create /
   cancel / change-plan a subscription) that the app owns and the
   provider fulfills.
2. A **webhook gateway** with mandatory signature verification — so the
   app's DB state only moves on provider-authenticated events, never on
   client-supplied redirects.

The primitive codifies both as a single Protocol and a small type shape
(``Customer``, ``Subscription``, ``Event``). Every SDK-specific detail
(Stripe's prorations, Paddle's plan ids, Chargebee's entitlements) lives
in the provider adapter.

## Invariants

- **BILL_INV_01 — Webhook signature verification is mandatory.**
  ``construct_webhook_event`` MUST verify the signature (HMAC-SHA256 over
  the raw payload using the configured webhook secret) AND the timestamp
  must fall within the configured tolerance window. A tampered payload
  MUST NEVER be returned as a valid ``Event``.
- **BILL_INV_02 — Subscription lifecycle is monotonic.** ``canceled`` is
  terminal. A canceled subscription MUST NEVER transition back to any
  other status through this primitive.
- **BILL_INV_03 — Plan-change preserves subscription identity.**
  ``change_plan(id, new_price)`` returns the SAME ``id`` with the new
  ``price_id``. The caller's DB row is never re-keyed.
- **BILL_INV_04 — Identifiers are opaque and checked.** Unknown
  ``customer_id`` / ``subscription_id`` raises ``UnknownCustomer`` /
  ``UnknownSubscription``; the motor never silently upserts.
- **BILL_INV_05 — No PII in error messages.** Errors raised by this
  primitive MUST NOT echo email / metadata / payload values.

## Reference implementation

``InMemoryBilling`` — deterministic in-memory backend suitable for
tests and local dev. Uses Stripe-compatible webhook signatures
(``t=<ts>,v1=<hex>``) so adapter callers can share fixtures.

Real providers live under ``core/venous/_adapters/<provider>/``:

- ``_adapters/stripe/BillingAdapter.py`` — Stripe SDK wiring.

## Public surface

```python
from core.venous.billing.Billing import (
    Billing,                 # Protocol
    InMemoryBilling,         # reference backend
    Customer, Subscription, Event,
    BillingError,
    InvalidWebhookSignature, # BILL_INV_01
    LifecycleInvariantError, # BILL_INV_02
    UnknownCustomer, UnknownSubscription,  # BILL_INV_04
)

gw = InMemoryBilling("whsec_test")

cust = gw.create_customer("alice@example.com")
sub = gw.create_subscription(cust.id, "price_pro_monthly")
sub = gw.change_plan(sub.id, "price_pro_annual")   # same sub.id (BILL_INV_03)

# Webhook path — payload + sig_header come from the provider:
event = gw.construct_webhook_event(payload, sig_header)
```

## Compose with

- ``SignatureVerifier`` — the lower-level HMAC verifier that every
  billing adapter reuses for webhook authenticity. ``Billing`` wraps it
  into a full event envelope.
- ``InboxDeduplicator`` — stripe + paddle retry webhooks on transient
  failures. Deduplicate by ``event.id`` so downstream handlers run
  exactly once per verified event.
- ``AuditEvent`` — every lifecycle transition ought to land in the
  audit trail (``subscription.created``, ``plan.changed``,
  ``subscription.canceled``) for compliance.
- ``WebhookReceiver`` — Billing is often called from inside a
  WebhookReceiver route. Keep the signature-verification boundary at
  the Billing primitive even if WebhookReceiver also enforces one —
  defence in depth for PII-sensitive state.

## Not in scope

- Proration / tax / dunning logic — provider-specific; lives in the
  adapter.
- Usage metering — use ``MeteredBilling`` (staged, not registered) or
  wire the provider's usage API directly.
- Invoice PDF generation.
