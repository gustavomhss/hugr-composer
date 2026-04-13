# Module: Payments — Production Stripe Integration for FastAPI

> The LLM generates: `stripe.Charge.create()` with no webhook verification, no idempotency, no error handling.
> The staff engineer knows: Checkout Sessions for PCI compliance, webhook signature verification, idempotency keys, subscription lifecycle, refund handling, test clocks.

---

## 1. Stripe Checkout Flow — Create Session -> Redirect -> Webhook -> Fulfill

### WHY
The LLM creates charges directly with `stripe.Charge.create()`, which means your server handles card data and puts you in PCI SAQ D scope (the hardest compliance tier). The correct pattern uses Stripe Checkout Sessions: you create a session, redirect the user to Stripe's hosted page, Stripe handles all card data, and a webhook notifies your server when payment succeeds. This keeps you in SAQ A scope (the easiest tier) because card data never touches your server.

### HOW
```python
import stripe
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

stripe.api_key = settings.stripe_secret_key  # From environment, NEVER hardcoded

router = APIRouter(tags=["payments"])

@router.post("/checkout")
async def create_checkout_session(body: CheckoutRequest, user: CurrentUser):
    """Create a Stripe Checkout Session and redirect to hosted page."""
    session = stripe.checkout.Session.create(
        mode="payment",  # "subscription" for recurring
        customer_email=user.email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": body.amount_cents,  # Always in smallest unit (cents)
                "product_data": {"name": body.product_name},
            },
            "quantity": 1,
        }],
        success_url=f"{settings.frontend_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.frontend_url}/payment/cancel",
        metadata={"order_id": body.order_id, "user_id": str(user.id)},
        idempotency_key=f"checkout:{body.order_id}",  # Prevent duplicate sessions
    )
    return {"checkout_url": session.url, "session_id": session.id}
```

### GOTCHA
NEVER fulfill the order on redirect to `success_url` — users can close the tab before redirect, or manipulate the URL. ALWAYS fulfill based on the `checkout.session.completed` webhook. The `success_url` is just a "thank you" page. `{CHECKOUT_SESSION_ID}` is a Stripe template variable — it is replaced with the actual session ID at redirect time.

---

## 2. Webhook Signature Verification — ALWAYS Verify, Timing-Safe Comparison

### WHY
Without signature verification, anyone can POST fake webhook events to your endpoint and trigger fake order fulfillments, fake subscription activations, or fake refund processing. Stripe signs every webhook with HMAC-SHA256 using your webhook endpoint's signing secret. The `stripe.Webhook.construct_event()` method does timing-safe verification — never implement your own.

### HOW
```python
from fastapi import Request, HTTPException

STRIPE_WEBHOOK_SECRET = settings.stripe_webhook_secret  # whsec_... from Stripe dashboard

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events. Signature verification is mandatory."""
    # 1. Read raw body — MUST be raw bytes, not parsed JSON
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(400, "Missing stripe-signature header")

    # 2. Verify signature (timing-safe, raises on failure)
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    except ValueError:
        raise HTTPException(400, "Invalid payload")

    # 3. Route to handler based on event type
    handler = EVENT_HANDLERS.get(event["type"])
    if handler:
        await handler(event["data"]["object"])
    else:
        pass  # Unknown event type — log and ignore, don't error

    # 4. Return 200 IMMEDIATELY — Stripe expects response within 20 seconds
    return {"received": True}

EVENT_HANDLERS = {
    "checkout.session.completed": handle_checkout_completed,
    "customer.subscription.updated": handle_subscription_updated,
    "customer.subscription.deleted": handle_subscription_deleted,
    "invoice.payment_failed": handle_payment_failed,
}
```

### GOTCHA
You MUST read the raw request body (`await request.body()`), not the parsed JSON (`await request.json()`). Signature verification hashes the raw bytes — if FastAPI parses and re-serializes the JSON, the signature won't match. Also: return 200 within 20 seconds or Stripe marks delivery as failed and retries. For complex processing, enqueue a background job and return 200 immediately.

---

## 3. Idempotency Keys — Prevent Double Charges

### WHY
Network timeouts between your server and Stripe are common. Your server sends a charge request, Stripe processes it, but the response is lost due to network error. Without an idempotency key, retrying creates a second charge. With an idempotency key, Stripe returns the result of the original request. This is not optional — it is mandatory for any financial operation.

### HOW
```python
# Every Stripe write operation MUST include an idempotency key
session = stripe.checkout.Session.create(
    # ... session params ...
    idempotency_key=f"checkout:{order_id}",  # Deterministic from business data
)

# Subscription creation
subscription = stripe.Subscription.create(
    customer=customer_id,
    items=[{"price": price_id}],
    idempotency_key=f"sub:{customer_id}:{price_id}:{int(time.time() // 86400)}",
)

# Refund
refund = stripe.Refund.create(
    payment_intent=payment_intent_id,
    amount=amount_cents,
    idempotency_key=f"refund:{payment_intent_id}:{amount_cents}",
)

# Key design rules:
# 1. Deterministic — same inputs produce same key
# 2. Unique per intent — different operations produce different keys
# 3. Include version/time when operations can repeat intentionally
#    (e.g., daily subscription = include date)
```

### GOTCHA
Stripe stores idempotency results for 24 hours. After 24 hours, the same key creates a new operation. If your retry window exceeds 24 hours, you need additional application-level deduplication. Also: idempotency keys are per-API-key — test and live mode have separate namespaces.

---

## 4. Webhook Retry Handling — Stripe Retries for 3 Days, Must Be Idempotent

### WHY
Stripe retries failed webhook deliveries (non-2xx response) with exponential backoff for up to 3 days. This means your webhook handler WILL receive the same event multiple times if it ever returns an error. If your handler creates a database record on `checkout.session.completed`, a retry would create a duplicate record. Every webhook handler must be idempotent — processing the same event twice must produce the same result.

### HOW
```python
async def handle_checkout_completed(session: dict):
    """Handle checkout.session.completed — MUST be idempotent."""
    order_id = session["metadata"]["order_id"]
    session_id = session["id"]

    # Idempotency check: has this event already been processed?
    existing = await db.get_order_by_stripe_session(session_id)
    if existing and existing.status == "fulfilled":
        return  # Already processed — no-op

    # Process the order (upsert, not insert)
    await db.upsert_order(
        order_id=order_id,
        stripe_session_id=session_id,
        status="fulfilled",
        amount=session["amount_total"],
        currency=session["currency"],
    )

    # Side effects should also be idempotent
    await send_confirmation_email(order_id, idempotency_key=f"email:{session_id}")

# Track processed events to detect duplicates
async def is_event_processed(event_id: str) -> bool:
    """Check if a Stripe event has already been handled."""
    return await db.exists("processed_events", {"event_id": event_id})

async def mark_event_processed(event_id: str):
    """Mark a Stripe event as processed. Use UNIQUE constraint for safety."""
    try:
        await db.insert("processed_events", {"event_id": event_id, "processed_at": datetime.utcnow()})
    except UniqueViolationError:
        pass  # Already exists — concurrent processing, no-op
```

### GOTCHA
Use a database UNIQUE constraint on `event_id` (or `stripe_session_id`) as the final safety net. Even with application-level checks, race conditions between concurrent webhook deliveries can slip through. The UNIQUE constraint guarantees atomicity at the database level.

---

## 5. Subscription Lifecycle — Create, Update, Cancel, Pause, Resume

### WHY
Subscriptions are state machines with complex transitions: trial -> active -> past_due -> canceled, or active -> paused -> active. Each transition triggers different webhook events and requires different business logic (grant access, send dunning emails, revoke access). The LLM generates `stripe.Subscription.create()` and stops. The staff engineer handles the full lifecycle.

### HOW
```python
# Key webhook events for subscription lifecycle
SUBSCRIPTION_HANDLERS = {
    # Trial started or subscription created
    "customer.subscription.created": handle_sub_created,
    # Plan change, payment method update, status change
    "customer.subscription.updated": handle_sub_updated,
    # Subscription canceled (end of billing period or immediate)
    "customer.subscription.deleted": handle_sub_deleted,
    # Payment failed — start dunning
    "invoice.payment_failed": handle_invoice_failed,
    # Payment succeeded after dunning
    "invoice.payment_succeeded": handle_invoice_succeeded,
}

async def handle_sub_updated(subscription: dict):
    """Handle subscription updates — the most complex handler."""
    sub_id = subscription["id"]
    customer_id = subscription["customer"]
    status = subscription["status"]

    match status:
        case "active":
            await grant_access(customer_id, subscription["items"]["data"])
        case "past_due":
            # Payment failed but subscription not yet canceled
            await send_dunning_email(customer_id)
            # Optionally: restrict features but don't revoke entirely
            await restrict_access(customer_id, grace_period_days=7)
        case "canceled":
            await revoke_access(customer_id)
            await send_cancellation_email(customer_id)
        case "paused":
            await pause_access(customer_id)
        case "unpaid":
            # All retry attempts exhausted
            await revoke_access(customer_id)
            await send_account_suspended_email(customer_id)

# Create subscription with trial
@router.post("/subscriptions")
async def create_subscription(body: SubscriptionRequest, user: CurrentUser):
    customer = await get_or_create_stripe_customer(user)
    subscription = stripe.Subscription.create(
        customer=customer.id,
        items=[{"price": body.price_id}],
        trial_period_days=14,
        payment_behavior="default_incomplete",  # Don't charge until trial ends
        expand=["latest_invoice.payment_intent"],
        idempotency_key=f"sub:{user.id}:{body.price_id}",
    )
    return {"subscription_id": subscription.id, "status": subscription.status}
```

### GOTCHA
`payment_behavior="default_incomplete"` is critical for trials — without it, Stripe tries to charge immediately even with a trial. Also: always store the Stripe `subscription.id` and `customer.id` in your database. Never derive access grants from the checkout session alone — the subscription status can change independently (payment failure, admin cancellation).

---

## 6. Invoice Handling — Draft -> Open -> Paid -> Void

### WHY
Invoices are the financial record of charges. For subscription billing, Stripe auto-generates invoices. For one-time charges, you can create invoices manually. Understanding the invoice lifecycle is essential for accounting reconciliation, tax compliance, and customer billing portals. The LLM ignores invoices entirely.

### HOW
```python
async def handle_invoice_succeeded(invoice: dict):
    """Invoice paid — record payment in your system."""
    await db.upsert_payment(
        stripe_invoice_id=invoice["id"],
        customer_id=invoice["customer"],
        amount=invoice["amount_paid"],
        currency=invoice["currency"],
        status="paid",
        period_start=datetime.fromtimestamp(invoice["period_start"]),
        period_end=datetime.fromtimestamp(invoice["period_end"]),
        invoice_pdf=invoice.get("invoice_pdf"),
    )

async def handle_invoice_failed(invoice: dict):
    """Payment failed — Stripe will retry. Notify the customer."""
    customer_id = invoice["customer"]
    attempt = invoice.get("attempt_count", 1)
    next_attempt = invoice.get("next_payment_attempt")

    await send_payment_failed_email(
        customer_id=customer_id,
        amount=invoice["amount_due"],
        attempt=attempt,
        next_attempt=datetime.fromtimestamp(next_attempt) if next_attempt else None,
        update_payment_url=f"{settings.frontend_url}/billing/update-payment",
    )

# Customer billing portal (let customers manage their own billing)
@router.post("/billing/portal")
async def create_billing_portal(user: CurrentUser):
    """Redirect customer to Stripe's hosted billing portal."""
    customer = await get_stripe_customer(user)
    session = stripe.billing_portal.Session.create(
        customer=customer.stripe_id,
        return_url=f"{settings.frontend_url}/settings/billing",
    )
    return {"portal_url": session.url}
```

### GOTCHA
Stripe's Smart Retries automatically retry failed payments using ML-optimized timing (e.g., retry at the time of day when the card is most likely to succeed). Don't build your own retry logic — configure retry behavior in the Stripe Dashboard under Billing > Automatic collection. The `invoice.payment_failed` webhook fires on each failed attempt — don't send the customer 8 emails.

---

## 7. PCI Compliance Levels — SAQ A (Stripe.js) vs SAQ D (Card Data Touches Your Server)

### WHY
PCI DSS is mandatory for anyone handling card payments. There are 4 SAQ (Self-Assessment Questionnaire) levels. SAQ A has 22 questions and minimal requirements. SAQ D has 329 questions and requires network segmentation, penetration testing, and security audits. The difference: does card data touch your server? If YES = SAQ D. If NO (Stripe Checkout/Elements) = SAQ A. The LLM often generates server-side card handling that puts you in SAQ D unnecessarily.

### HOW
```python
# SAQ A (recommended) — card data NEVER touches your server
# Use Stripe Checkout (hosted page) or Stripe Elements (embedded form)

# Option 1: Checkout Session (fully hosted by Stripe)
session = stripe.checkout.Session.create(mode="payment", ...)
# Redirect to session.url — Stripe handles everything

# Option 2: Stripe Elements (embedded, card data goes directly to Stripe)
# Frontend: <CardElement> sends card data to Stripe, returns payment_method_id
# Backend: only receives payment_method_id (not card data)
@router.post("/pay")
async def pay(body: PaymentRequest):
    # body.payment_method_id is a Stripe token — NOT card data
    intent = stripe.PaymentIntent.create(
        amount=body.amount_cents,
        currency="usd",
        payment_method=body.payment_method_id,  # Token, not card number
        confirm=True,
    )
    return {"status": intent.status}

# --------- NEVER DO THIS (SAQ D) ---------
# @router.post("/pay")
# async def pay(card_number: str, cvv: str, expiry: str):
#     # Card data touches your server = SAQ D = 329 compliance questions
#     stripe.Charge.create(source=..., ...)
```

### GOTCHA
Even logging card data puts you in SAQ D scope. Ensure your logging framework does not capture request bodies on payment endpoints. Use `request.body()` exclusion in your structured logging middleware. PCI compliance is not just technical — it requires annual self-assessment and attestation.

---

## 8. Refund Handling — Full vs Partial, Refund to Original Payment Method

### WHY
Refunds are a critical part of payment operations. The LLM generates charge creation but never handles refunds. Refunds must be idempotent (retrying a refund request should not double-refund), traceable (linked to original payment), and validated (cannot refund more than the original amount).

### HOW
```python
@router.post("/orders/{order_id}/refund")
async def refund_order(
    order_id: str,
    body: RefundRequest,
    user: AdminUser,  # Only admins can issue refunds
):
    order = await db.get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.refunded:
        raise HTTPException(409, "Order already refunded")

    # Calculate refund amount
    amount = body.amount_cents or order.amount_cents  # Partial or full
    if amount > order.amount_cents - order.refunded_amount:
        raise HTTPException(400, "Refund amount exceeds remaining balance")

    refund = stripe.Refund.create(
        payment_intent=order.stripe_payment_intent_id,
        amount=amount,  # In smallest currency unit (cents)
        reason=body.reason,  # "duplicate", "fraudulent", "requested_by_customer"
        idempotency_key=f"refund:{order_id}:{amount}:{int(time.time() // 3600)}",
    )

    await db.update_order(order_id, refunded_amount=order.refunded_amount + amount)
    return {"refund_id": refund.id, "status": refund.status}

# Handle refund webhook (Stripe notifies when refund completes)
async def handle_refund_updated(refund: dict):
    if refund["status"] == "succeeded":
        await db.mark_refund_completed(refund["id"])
    elif refund["status"] == "failed":
        await alert_ops(f"Refund {refund['id']} failed: {refund.get('failure_reason')}")
```

### GOTCHA
Stripe refunds take 5-10 business days to appear on the customer's statement. Your system should show "refund pending" immediately but note the bank processing time. Also: refunds on disputes (chargebacks) are handled differently — Stripe manages the dispute process. Monitor `charge.dispute.created` webhook for chargebacks.

---

## 9. Multi-Currency Support — Store Amounts in Smallest Unit (Cents)

### WHY
Stripe handles all currency conversion at the payment level, but your database and API must handle currency correctly. The universal rule: store amounts in the smallest currency unit (cents for USD/EUR, yen for JPY). Never use floating point for money — `0.1 + 0.2 != 0.3` in IEEE 754 floating point. Use integers everywhere.

### HOW
```python
from pydantic import BaseModel, Field

class PriceAmount(BaseModel):
    """Amount in smallest currency unit. Always integer, never float."""
    amount: int = Field(ge=0, description="Amount in smallest unit (e.g., cents)")
    currency: str = Field(min_length=3, max_length=3, pattern="^[a-z]{3}$")

    def to_display(self) -> str:
        """Convert to human-readable format."""
        if self.currency in ZERO_DECIMAL_CURRENCIES:
            return f"{self.amount} {self.currency.upper()}"
        return f"{self.amount / 100:.2f} {self.currency.upper()}"

# Zero-decimal currencies (no cents — amount IS the unit)
ZERO_DECIMAL_CURRENCIES = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
}

# Database: ALWAYS store as integer cents
# amount_cents INTEGER NOT NULL
# currency VARCHAR(3) NOT NULL

# API: Accept and return integer cents
@router.post("/products/{product_id}/price")
async def set_price(product_id: int, body: PriceAmount):
    # body.amount is already in cents — no conversion needed
    await db.update_price(product_id, body.amount, body.currency)

# Display: Convert only at the presentation layer
# "1999 usd" -> "$19.99"
# "1000 jpy" -> "¥1000" (JPY is zero-decimal)
```

### GOTCHA
Japan (JPY), Korea (KRW), and 15+ other currencies are zero-decimal — `amount=1000` means 1000 yen, not 10.00 yen. Stripe's API documentation lists all zero-decimal currencies. If you assume all currencies have 2 decimal places, JPY charges will be 100x too small. Always check the `ZERO_DECIMAL_CURRENCIES` set.

---

## 10. Testing with Stripe CLI — stripe listen, Test Clocks for Subscriptions

### WHY
Testing payment flows in production is dangerous and against Stripe's TOS. Stripe provides a complete test environment with test API keys, test card numbers, the Stripe CLI for local webhook testing, and Test Clocks for simulating subscription time progression. The staff engineer never tests payments against live Stripe — every scenario can be tested locally.

### HOW
```bash
# 1. Install Stripe CLI
brew install stripe/stripe-cli/stripe

# 2. Login
stripe login

# 3. Forward webhooks to local server
stripe listen --forward-to localhost:8000/webhooks/stripe
# Outputs: whsec_... (use this as STRIPE_WEBHOOK_SECRET in dev)

# 4. Trigger test events
stripe trigger checkout.session.completed
stripe trigger customer.subscription.created
stripe trigger invoice.payment_failed
```

```python
# Test card numbers (use in test mode only)
TEST_CARDS = {
    "success": "4242424242424242",            # Always succeeds
    "decline": "4000000000000002",            # Always declines
    "insufficient": "4000000000009995",       # Insufficient funds
    "3ds_required": "4000002500003155",       # Requires 3D Secure
    "dispute": "4000000000000259",            # Triggers dispute after charge
}

# Test Clocks — simulate subscription time progression
@pytest.fixture
async def test_clock():
    """Create a Stripe Test Clock for subscription testing."""
    clock = stripe.test_helpers.TestClock.create(
        frozen_time=int(datetime(2026, 1, 1).timestamp()),
    )
    yield clock
    stripe.test_helpers.TestClock.delete(clock.id)

async def test_subscription_renewal(test_clock):
    """Test that subscription renews and invoice is paid."""
    customer = stripe.Customer.create(test_clock=test_clock.id)
    sub = stripe.Subscription.create(
        customer=customer.id,
        items=[{"price": "price_test_monthly"}],
    )
    assert sub.status == "active"

    # Advance time by 1 month — triggers renewal
    stripe.test_helpers.TestClock.advance(
        test_clock.id,
        frozen_time=int(datetime(2026, 2, 1).timestamp()),
    )
    # Check that invoice was created and paid
```

### GOTCHA
Test mode and live mode are completely separate environments with different API keys, different webhook secrets, and different data. Never mix them. The `whsec_...` secret from `stripe listen` is different from the one in the Dashboard — use the CLI's secret for local development. Test Clocks only work with customers created with `test_clock=clock.id`.
