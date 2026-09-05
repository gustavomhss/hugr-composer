# Billing Domain — Maintenance Skill

> **Crates**: 1 (`Billing`) | **Status**: Production-ready | **Owner**: Payments Team | **Last Updated**: 2026-09-04

> **Purpose**: Payment processing, subscriptions, invoicing, and revenue management.

---

## Crate: `Billing`

**Location**: `core/venous/billing/Billing/`

**Purpose**: Provider-agnostic billing abstraction supporting multiple payment processors (Stripe, Paddle, LemonSqueezy, etc.) with webhook handling, subscription lifecycle, and idempotency.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      BILLING ARCHITECTURE                   │
├─────────────────────────────────────────────────────────────┤
│  Your App → BillingAdapter → Provider SDK → Payment Gateway │
│        ↓                                                         │
│  WebhookHandler → Event Processor → Your Domain Events        │
│        ↓                                                         │
│  IdempotencyLayer → IdempotencyStore → Your Domain            │
└─────────────────────────────────────────────────────────────┘
```

---

## Common Operations

### 1. Adding a New Payment Provider

```python
# 1. Implement the BillingProvider protocol
# core/venous/billing/Billing/Billing.py

class BillingProvider(Protocol):
    async def create_customer(self, email: str, metadata: dict) -> Customer
    async def create_subscription(self, customer_id: str, price_id: str) -> Subscription
    async def cancel_subscription(self, subscription_id: str) -> None
    async def create_checkout_session(self, customer_id: str, price_id: str, success_url: str, cancel_url: str) -> CheckoutSession
    async def create_portal_session(self, customer_id: str, return_url: str) -> PortalSession
    async def handle_webhook(self, payload: bytes, signature: str) -> WebhookEvent

# 2. Implement for your provider (e.g., Paddle)
class PaddleProvider(BillingProvider):
    async def create_customer(self, email: str, metadata: dict) -> Customer:
        # Paddle-specific implementation
        ...

# 3. Register in Billing factory
# core/venous/billing/Billing/__init__.py
PROVIDERS = {
    "stripe": StripeProvider,
    "paddle": PaddleProvider,  # ADD HERE
    # ...
}
```

**Checklist**:
- [ ] Implement all `BillingProvider` methods
- [ ] Add webhook signature verification
- [ ] Add idempotency keys for all mutating operations
- [ ] Add unit tests for all methods
- [ ] Add integration tests with sandbox
- [ ] Update documentation

---

### 2. Handling Webhooks Safely

```python
# Webhooks MUST be idempotent
async def handle_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
    # 1. Verify signature (provider-specific)
    if not self._verify_signature(payload, signature):
        raise InvalidSignatureError()
    
    # 2. Parse event
    event = self._parse_event(payload)
    
    # 4. Process with idempotency
    async with self.idempotency_store.lock(event.idempotency_key):
        if await self.idempotency_store.exists(event.idempotency_key):
            return WebhookEvent(status="duplicate")
        
        # 5. Process event
        result = await self._process_event(event)
        
        # 5. Mark as processed
        await self.idempotency_store.set(event.idempotency_key, result)
        
        return result
```

**Critical**: Always use idempotency keys. Payment providers WILL retry webhooks.

---

### 3. Handling Subscription Lifecycle

```python
# Subscription state machine:
# trialing → active → past_due → canceled
#                    ↓
#               paused (optional)

# Key events to handle:
# - customer.subscription.created
# - customer.subscription.updated
# - customer.subscription.deleted
# - customer.subscription.paused
# - customer.subscription.resumed
# - invoice.payment_succeeded
# - invoice.payment_failed
# - payment_method.attached
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Webhook replay** | Duplicate charges/subscriptions | Idempotency keys on ALL webhooks |
| **Price ID mismatch** | Wrong plan charged | Store price_id in DB; validate on checkout |
| **Currency mismatch** | Wrong amount charged | Store currency in DB; validate on checkout |
| **Trial abuse** | Unlimited free trials | Track trial usage per customer; limit to 1 |
| **Proration confusion** | Wrong charges on plan change | Document proration behavior; test edge cases |
| **Webhook ordering** | Events processed out of order | Use event timestamps; handle out-of-order |
| **Refund vs void** | Wrong accounting | Void if uncaptured; refund if captured |

---

## Evolution Without Breaking Contracts

### Adding a New Webhook Event Type

```python
# 1. Add to WebhookEvent union (non-breaking)
class WebhookEvent(BaseModel):
    type: Literal[
        "customer.created",
        "subscription.created",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
        "customer.subscription.trial_will_end",  # ADD HERE
        # ...
    ]

# 2. Handle in webhook processor (non-breaking)
async def handle_webhook(self, event: WebhookEvent):
    handlers = {
        "customer.created": self._handle_customer_created,
        "subscription.created": self._handle_subscription_created,
        "customer.subscription.trial_will_end": self._handle_trial_ending,  # ADD
    }
    handler = handlers.get(event.type)
    if handler:
        await handler(event)
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing pricing model | **STOP** — Business + Engineering review |
| Changing currency support | **REVIEW** — FX + Accounting |
| Adding new payment provider | **REVIEW** — Security + Compliance |
| Changing subscription billing cycle | **REVIEW** — Proration impact |
| Changing webhook format | **STOP** — Breaking for consumers |
| Modifying refund logic | **REVIEW** — Accounting + Legal |

---

## Health Checks & Monitoring

```python
@app.get("/health/billing")
async def billing_health():
    return {
        "status": "healthy",
        "checks": {
            "stripe_connectivity": await check_stripe_api(),
            "paddle_connectivity": await check_paddle_api(),
            "webhook_processing": await check_webhook_queue(),
            "idempotency_store": await idempotency_store.ping(),
        }
    }

# Metrics to alert on:
# - billing.webhook.failure_rate > 1%
# - billing.charge.failure_rate > 5%
# - billing.subscription.churn_rate > 10% MoM
# - billing.webhook.processing_latency.p99 > 5s
```

---

## Debugging Quick Reference

```bash
# Test Stripe webhook locally
stripe listen --forward-to localhost:8000/webhooks/stripe

# Test Paddle webhook locally
ngrok http 8000
# Configure webhook in Paddle dashboard

# Debug failed payment
python -c "
from app.billing import StripeProvider
p = StripeProvider()
# Check payment intent
pi = stripe.PaymentIntent.retrieve('pi_xxx')
print(pi.status, pi.last_payment_error)
"

# Verify webhook signature
python -c "
import stripe
payload = open('webhook_payload.json', 'rb').read()
sig = 'sig_header_value'
try:
    event = stripe.Webhook.construct_event(payload, sig, 'whsec_xxx')
    print('Valid:', event.type)
except Exception as e:
    print('Invalid:', e)
"
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Webhook processing | Async queue size | 1000 |
| Idempotency store | Redis TTL | 30 days |
| Provider SDK | HTTP pool size | 20 connections |
| Webhook processing | Timeout | 30s |
| Idempotency store | TTL | 30 days |

---

## Security Checklist (Pre-Deploy)

- [ ] All webhooks verify signatures
- [ ] Idempotency keys on ALL webhooks
- [ ] PCI SAQ compliance (if handling cards directly)
- [ ] Webhook signatures verified before processing
- [ ] No sensitive data in webhook logs
- [ ] PCI DSS compliance (if applicable)
- [ ] PCI DSS SAQ-A compliance (if using Stripe/Paddle hosted)
- [ ] Webhook endpoints return 2xx within 10s
- [ ] Idempotency keys have TTL (30 days)
- [ ] Sensitive data encrypted at rest

---

## Version Upgrade Procedures

### Upgrading Stripe SDK

```bash
# 1. Check changelog for breaking changes
# 2. Test in sandbox
pip install -U stripe
# 3. Run integration tests
python -m pytest tests/billing/ -v -k stripe
# 4. Test in staging with real webhooks
# 4. Deploy with feature flag
```

---

## Testing Strategy

```python
# Unit tests
# - Webhook signature verification
# - Idempotency key generation
# - Event parsing
# - State machine transitions

# Integration tests
# - Full checkout flow (Stripe sandbox)
# - Subscription lifecycle (create → cancel → resume)
# - Webhook processing (all event types)
# - Idempotency (duplicate webhook handling)

# Contract tests
# - Webhook payload schemas
# - API response schemas
# - Error response formats

# Load tests
# - 1000 webhooks/minute
# - 100 concurrent checkouts
```

---

## Emergency Procedures

### Payment Provider Outage

```bash
# 1. Switch to backup provider (if configured)
# 2. Disable affected payment methods in UI
# 3. Show maintenance banner for payments
# 4. Queue failed payments for retry
# 4. Alert on-call + stakeholders
# 5. Post-incident: RCA within 24h
```

### Duplicate Charges Incident

```bash
# 1. Identify affected customers
# 2. Issue refunds via Stripe dashboard/API
# 3. Send apology email with timeline
# 4. Root cause analysis
# 4. Implement additional idempotency checks
# 5. Post-incident review within 48h
```

---

## Testing Checklist (Pre-Deploy)

- [ ] All webhook events process without error
- [ ] Idempotency: duplicate webhook = no duplicate effect
- [ ] Subscription lifecycle: create → cancel → resume works
- [ ] Proration calculations correct
- [ ] Trial → paid conversion works
- [ ] Grace period → cancellation works
- [ ] Refunds process correctly
- [ ] Webhook retries handled (exponential backoff)
- [ ] Currency conversion correct
- [ ] Tax calculation correct (if applicable)

---

*Billing Domain Maintenance Skill v1.0 | Maintained by Payments Team | Next review: 2026-12-04*