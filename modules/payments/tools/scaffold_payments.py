"""
SKILL-001 Payments Tool: Generate production Stripe payment infrastructure.

Creates a complete Stripe integration with Checkout Sessions, webhook handling
with signature verification, idempotency keys, subscription lifecycle management,
refund handling, billing portal, and PCI-compliant patterns. All generated code
follows KNOWLEDGE.md patterns and keeps card data off your server (SAQ A).

Generated files:
    payments/__init__.py       -- package marker with re-exports
    payments/config.py         -- Stripe configuration from environment
    payments/checkout.py       -- Checkout Session creation (one-time + subscription)
    payments/webhooks.py       -- Webhook endpoint with signature verification
    payments/handlers.py       -- Idempotent event handlers per webhook type
    payments/subscriptions.py  -- Subscription lifecycle (create, cancel, portal)
    payments/refunds.py        -- Refund creation with idempotency (optional)
    payments/schemas.py        -- Pydantic request/response models
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _init_py(with_subscriptions: bool) -> str:
    sub_imports = ""
    sub_all = ""
    if with_subscriptions:
        sub_imports = "from .subscriptions import create_subscription, create_billing_portal\n"
        sub_all = '    "create_subscription",\n    "create_billing_portal",\n'

    template = textwrap.dedent("""\
        \"\"\"Payments module — production Stripe integration for FastAPI.\"\"\"

        from .checkout import create_checkout_session
        from .webhooks import stripe_webhook_router
        __SUB_IMPORTS__
        __all__ = [
            "create_checkout_session",
            "stripe_webhook_router",
        __SUB_ALL__]
    """)
    result = template.replace("__SUB_IMPORTS__", sub_imports)
    result = result.replace("__SUB_ALL__", sub_all)
    # Clean up double blank lines if no subs
    if not sub_imports:
        result = result.replace("\n\n\n", "\n\n")
    return result


def _config_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Stripe configuration — loaded from environment variables.

        NEVER hardcode API keys. Always use environment variables.
        Test mode keys start with sk_test_ and pk_test_.
        Live mode keys start with sk_live_ and pk_live_.
        \"\"\"

        from __future__ import annotations

        import os

        import stripe


        def configure_stripe() -> None:
            \"\"\"Configure the Stripe SDK from environment variables.

            Call this from your FastAPI lifespan startup.

            Required env vars:
                STRIPE_SECRET_KEY: sk_test_... or sk_live_...
                STRIPE_WEBHOOK_SECRET: whsec_...
            Optional env vars:
                STRIPE_API_VERSION: API version override (e.g., "2024-12-18")
            \"\"\"
            secret_key = os.getenv("STRIPE_SECRET_KEY")
            if not secret_key:
                raise RuntimeError(
                    "STRIPE_SECRET_KEY not set. Add it to .env file."
                )
            stripe.api_key = secret_key

            api_version = os.getenv("STRIPE_API_VERSION")
            if api_version:
                stripe.api_version = api_version


        def get_webhook_secret() -> str:
            \"\"\"Get the webhook signing secret for signature verification.\"\"\"
            secret = os.getenv("STRIPE_WEBHOOK_SECRET")
            if not secret:
                raise RuntimeError(
                    "STRIPE_WEBHOOK_SECRET not set. Get it from Stripe Dashboard "
                    "or 'stripe listen' CLI output."
                )
            return secret


        # Zero-decimal currencies (no cents — amount IS the unit)
        ZERO_DECIMAL_CURRENCIES: set[str] = {
            "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
            "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
        }
    """)


def _schemas_py(with_subscriptions: bool) -> str:
    sub_schemas = ""
    if with_subscriptions:
        sub_schemas = textwrap.dedent("""\


        class SubscriptionRequest(BaseModel):
            model_config = ConfigDict(strict=True)

            price_id: str = Field(description="Stripe Price ID (price_...)")
            trial_days: int = Field(default=0, ge=0, le=90)


        class SubscriptionResponse(BaseModel):
            subscription_id: str
            status: str
            current_period_end: str | None = None
        """)

    template = textwrap.dedent("""\
        \"\"\"Payment request and response schemas with strict validation.\"\"\"

        from pydantic import BaseModel, ConfigDict, Field


        class CheckoutRequest(BaseModel):
            model_config = ConfigDict(strict=True)

            product_name: str = Field(min_length=1, max_length=200)
            amount_cents: int = Field(gt=0, le=99999999, description="Amount in cents")
            currency: str = Field(default="usd", min_length=3, max_length=3)
            order_id: str = Field(min_length=1, max_length=128)


        class CheckoutResponse(BaseModel):
            checkout_url: str
            session_id: str


        class RefundRequest(BaseModel):
            model_config = ConfigDict(strict=True)

            amount_cents: int | None = Field(
                default=None, gt=0,
                description="Partial refund amount in cents. None = full refund.",
            )
            reason: str = Field(
                default="requested_by_customer",
                pattern="^(duplicate|fraudulent|requested_by_customer)$",
            )


        class RefundResponse(BaseModel):
            refund_id: str
            status: str
            amount: int
    """)
    return template.rstrip() + "\n" + sub_schemas


def _checkout_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Stripe Checkout Session creation — PCI SAQ A compliant.

        Uses Stripe Checkout (hosted page) so card data NEVER touches
        your server. This keeps you in PCI SAQ A scope (22 questions)
        instead of SAQ D (329 questions).
        \"\"\"

        from __future__ import annotations

        import os

        import stripe
        from fastapi import APIRouter, HTTPException

        from .schemas import CheckoutRequest, CheckoutResponse

        router = APIRouter(prefix="/payments", tags=["payments"])

        FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


        @router.post("/checkout", response_model=CheckoutResponse)
        async def create_checkout_session(body: CheckoutRequest):
            \"\"\"Create a Stripe Checkout Session for one-time payment.

            Redirects the user to Stripe's hosted payment page.
            Order fulfillment happens via webhook (checkout.session.completed),
            NEVER on redirect to success_url.
            \"\"\"
            try:
                session = stripe.checkout.Session.create(
                    mode="payment",
                    line_items=[{
                        "price_data": {
                            "currency": body.currency,
                            "unit_amount": body.amount_cents,
                            "product_data": {"name": body.product_name},
                        },
                        "quantity": 1,
                    }],
                    success_url=f"{FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url=f"{FRONTEND_URL}/payment/cancel",
                    metadata={
                        "order_id": body.order_id,
                    },
                    idempotency_key=f"checkout:{body.order_id}",
                )
            except stripe.error.StripeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stripe error: {exc.user_message or str(exc)}",
                )

            return CheckoutResponse(
                checkout_url=session.url,
                session_id=session.id,
            )
    """)


def _webhooks_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Stripe webhook endpoint with mandatory signature verification.

        CRITICAL: Always verify webhook signatures. Without verification,
        anyone can POST fake events and trigger false order fulfillments.
        \"\"\"

        from __future__ import annotations

        import logging

        import stripe
        from fastapi import APIRouter, HTTPException, Request

        from .config import get_webhook_secret
        from .handlers import EVENT_HANDLERS

        logger = logging.getLogger("payments.webhooks")

        router = APIRouter(tags=["payments-webhooks"])


        @router.post("/webhooks/stripe")
        async def stripe_webhook(request: Request):
            \"\"\"Handle Stripe webhook events with signature verification.

            Returns 200 immediately after verification. Complex processing
            should be enqueued as a background job to meet Stripe's 20-second
            response timeout.
            \"\"\"
            # 1. Read RAW body — MUST be raw bytes for signature verification
            payload = await request.body()
            sig_header = request.headers.get("stripe-signature")

            if not sig_header:
                raise HTTPException(400, "Missing stripe-signature header")

            # 2. Verify signature (timing-safe, raises on tamper)
            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, get_webhook_secret(),
                )
            except stripe.error.SignatureVerificationError:
                logger.warning("Webhook signature verification failed")
                raise HTTPException(400, "Invalid webhook signature")
            except ValueError:
                logger.warning("Webhook payload parsing failed")
                raise HTTPException(400, "Invalid webhook payload")

            # 3. Route to handler based on event type
            event_type = event["type"]
            handler = EVENT_HANDLERS.get(event_type)

            if handler:
                try:
                    await handler(event["data"]["object"], event)
                except Exception:
                    logger.exception(f"Error handling webhook event: {event_type}")
                    # Return 200 anyway — we don't want Stripe to retry on our bugs
                    # The error is logged for investigation
            else:
                logger.debug(f"Unhandled webhook event type: {event_type}")

            # 4. Return 200 within 20 seconds
            return {"received": True}


        # Export the router for inclusion in the main app
        stripe_webhook_router = router
    """)


def _handlers_py(with_subscriptions: bool) -> str:
    sub_handlers = ""
    sub_handler_map = ""
    if with_subscriptions:
        sub_handlers = textwrap.dedent("""\


        async def handle_subscription_updated(subscription: dict, event: dict) -> None:
            \"\"\"Handle subscription status changes — grant/revoke/restrict access.\"\"\"
            sub_id = subscription["id"]
            customer_id = subscription["customer"]
            status = subscription["status"]

            logger.info(
                f"Subscription {sub_id} for customer {customer_id} -> {status}"
            )

            # TODO: Implement access control based on status
            # match status:
            #     case "active":
            #         await grant_access(customer_id)
            #     case "past_due":
            #         await restrict_access(customer_id, grace_period_days=7)
            #     case "canceled" | "unpaid":
            #         await revoke_access(customer_id)
            #     case "paused":
            #         await pause_access(customer_id)


        async def handle_subscription_deleted(subscription: dict, event: dict) -> None:
            \"\"\"Handle subscription cancellation — revoke access.\"\"\"
            customer_id = subscription["customer"]
            logger.info(f"Subscription deleted for customer {customer_id}")
            # TODO: await revoke_access(customer_id)


        async def handle_invoice_payment_failed(invoice: dict, event: dict) -> None:
            \"\"\"Handle failed invoice payment — notify customer for payment update.\"\"\"
            customer_id = invoice["customer"]
            attempt = invoice.get("attempt_count", 1)
            logger.warning(
                f"Invoice payment failed for customer {customer_id} "
                f"(attempt {attempt})"
            )
            # TODO: Send dunning email with link to update payment method
            # await send_payment_failed_email(customer_id, attempt)
        """)
        sub_handler_map = textwrap.dedent("""\
            "customer.subscription.updated": handle_subscription_updated,
            "customer.subscription.deleted": handle_subscription_deleted,
            "invoice.payment_failed": handle_invoice_payment_failed,
        """)

    template = textwrap.dedent("""\
        \"\"\"Idempotent webhook event handlers.

        Every handler MUST be idempotent — processing the same event twice
        must produce the same result. Stripe retries failed webhook deliveries
        for up to 3 days, so duplicate events are expected.

        Idempotency strategy: check event.id or session_id against processed
        records before acting. Use database UNIQUE constraints as final safety net.
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Awaitable, Callable

        logger = logging.getLogger("payments.handlers")


        async def handle_checkout_completed(session: dict, event: dict) -> None:
            \"\"\"Handle successful checkout — fulfill the order.

            This is the ONLY reliable signal for order fulfillment.
            NEVER fulfill based on redirect to success_url.
            \"\"\"
            order_id = session.get("metadata", {}).get("order_id")
            session_id = session["id"]
            amount = session.get("amount_total", 0)
            currency = session.get("currency", "usd")

            logger.info(
                f"Checkout completed: order={order_id}, session={session_id}, "
                f"amount={amount} {currency}"
            )

            # TODO: Implement idempotent order fulfillment:
            # existing = await db.get_order_by_stripe_session(session_id)
            # if existing and existing.status == "fulfilled":
            #     return  # Already processed — no-op
            #
            # await db.upsert_order(
            #     order_id=order_id,
            #     stripe_session_id=session_id,
            #     status="fulfilled",
            #     amount=amount,
            #     currency=currency,
            # )
            # await send_confirmation_email(order_id)
        __SUB_HANDLERS__

        # Event type -> handler mapping
        EVENT_HANDLERS: dict[str, Callable[..., Awaitable[None]]] = {
            "checkout.session.completed": handle_checkout_completed,
        __SUB_HANDLER_MAP__}
    """)
    result = template.replace("__SUB_HANDLERS__", sub_handlers)
    result = result.replace("__SUB_HANDLER_MAP__", sub_handler_map)
    return result


def _subscriptions_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Stripe subscription management — create, cancel, billing portal.\"\"\"

        from __future__ import annotations

        import os
        import logging

        import stripe
        from fastapi import APIRouter, HTTPException

        from .schemas import SubscriptionRequest, SubscriptionResponse

        logger = logging.getLogger("payments.subscriptions")

        router = APIRouter(prefix="/payments", tags=["payments"])

        FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


        @router.post("/subscriptions", response_model=SubscriptionResponse, status_code=201)
        async def create_subscription(body: SubscriptionRequest, customer_id: str = ""):
            \"\"\"Create a new subscription.

            In production, get customer_id from the authenticated user's
            Stripe customer record. Create the customer if it doesn't exist.
            \"\"\"
            if not customer_id:
                raise HTTPException(
                    400,
                    "customer_id required. Create via Stripe Customer API first.",
                )

            try:
                sub_params: dict = {
                    "customer": customer_id,
                    "items": [{"price": body.price_id}],
                    "payment_behavior": "default_incomplete",
                    "expand": ["latest_invoice.payment_intent"],
                    "idempotency_key": f"sub:{customer_id}:{body.price_id}",
                }
                if body.trial_days > 0:
                    sub_params["trial_period_days"] = body.trial_days

                subscription = stripe.Subscription.create(**sub_params)
            except stripe.error.StripeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stripe error: {exc.user_message or str(exc)}",
                )

            return SubscriptionResponse(
                subscription_id=subscription.id,
                status=subscription.status,
                current_period_end=str(subscription.current_period_end),
            )


        @router.post("/billing/portal")
        async def create_billing_portal(customer_id: str = ""):
            \"\"\"Create a Stripe Billing Portal session.

            The billing portal lets customers manage their subscriptions,
            update payment methods, view invoices, and cancel — all hosted
            by Stripe. No PCI implications.
            \"\"\"
            if not customer_id:
                raise HTTPException(400, "customer_id required")

            try:
                session = stripe.billing_portal.Session.create(
                    customer=customer_id,
                    return_url=f"{FRONTEND_URL}/settings/billing",
                )
            except stripe.error.StripeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stripe error: {exc.user_message or str(exc)}",
                )

            return {"portal_url": session.url}


        @router.delete("/subscriptions/{subscription_id}")
        async def cancel_subscription(subscription_id: str, immediate: bool = False):
            \"\"\"Cancel a subscription.

            By default, cancels at end of billing period (at_period_end=True).
            Set immediate=True for immediate cancellation with prorated refund.
            \"\"\"
            try:
                if immediate:
                    subscription = stripe.Subscription.delete(subscription_id)
                else:
                    subscription = stripe.Subscription.modify(
                        subscription_id,
                        cancel_at_period_end=True,
                    )
            except stripe.error.StripeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stripe error: {exc.user_message or str(exc)}",
                )

            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "cancel_at_period_end": subscription.cancel_at_period_end,
            }
    """)


def _refunds_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Stripe refund handling — full and partial refunds with idempotency.\"\"\"

        from __future__ import annotations

        import logging
        import time

        import stripe
        from fastapi import APIRouter, HTTPException

        from .schemas import RefundRequest, RefundResponse

        logger = logging.getLogger("payments.refunds")

        router = APIRouter(prefix="/payments", tags=["payments"])


        @router.post("/orders/{order_id}/refund", response_model=RefundResponse)
        async def refund_order(order_id: str, body: RefundRequest):
            \"\"\"Create a refund for an order.

            In production, verify:
            1. The order exists and belongs to the requesting user/admin
            2. The refund amount doesn't exceed the remaining balance
            3. The order hasn't already been fully refunded
            \"\"\"
            # TODO: Load order from database
            # order = await db.get_order(order_id)
            # if not order:
            #     raise HTTPException(404, "Order not found")
            # if order.fully_refunded:
            #     raise HTTPException(409, "Order already fully refunded")
            # payment_intent_id = order.stripe_payment_intent_id

            payment_intent_id = ""  # TODO: Get from order record
            if not payment_intent_id:
                raise HTTPException(
                    400,
                    "Order has no associated payment intent. Set payment_intent_id.",
                )

            try:
                refund_params: dict = {
                    "payment_intent": payment_intent_id,
                    "reason": body.reason,
                    "idempotency_key": (
                        f"refund:{order_id}:{body.amount_cents or 'full'}"
                        f":{int(time.time() // 3600)}"
                    ),
                }
                if body.amount_cents:
                    refund_params["amount"] = body.amount_cents

                refund = stripe.Refund.create(**refund_params)
            except stripe.error.StripeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stripe error: {exc.user_message or str(exc)}",
                )

            logger.info(
                f"Refund created for order {order_id}: "
                f"{refund.id} ({refund.amount} {refund.currency})"
            )

            return RefundResponse(
                refund_id=refund.id,
                status=refund.status,
                amount=refund.amount,
            )
    """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_payment_module(
    output_dir: str,
    provider: str = "stripe",
    with_subscriptions: bool = True,
) -> dict:
    """
    Generate a production-ready payment module for a FastAPI project.

    Creates a Stripe integration with Checkout Sessions (PCI SAQ A),
    webhook handling with signature verification, idempotency keys,
    subscription lifecycle management, refund handling, and billing
    portal inside a ``payments/`` subdirectory of *output_dir*.

    Args:
        output_dir: Parent directory where the ``payments/`` package will be created.
        provider: Payment provider. Currently only "stripe" is supported.
        with_subscriptions: Include subscription management endpoints
            (create, cancel, billing portal).

    Returns:
        Dict with ``created_files`` (list of paths) and ``payments_path`` (str).

    Example::

        result = generate_payment_module("/tmp/myproject", with_subscriptions=True)
        print(result["created_files"])
        # ['payments/__init__.py', 'payments/config.py', 'payments/schemas.py',
        #  'payments/checkout.py', 'payments/webhooks.py', 'payments/handlers.py',
        #  'payments/subscriptions.py', 'payments/refunds.py']
    """
    if provider != "stripe":
        raise ValueError(f"Unsupported provider: {provider}. Only 'stripe' is supported.")

    payments_dir = Path(output_dir) / "payments"
    payments_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _init_py(with_subscriptions),
        "config.py": _config_py(),
        "schemas.py": _schemas_py(with_subscriptions),
        "checkout.py": _checkout_py(),
        "webhooks.py": _webhooks_py(),
        "handlers.py": _handlers_py(with_subscriptions),
        "refunds.py": _refunds_py(),
    }

    if with_subscriptions:
        files["subscriptions.py"] = _subscriptions_py()

    created: list[str] = []
    for filename, content in files.items():
        filepath = payments_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"payments/{filename}")

    return {
        "created_files": created,
        "payments_path": str(payments_dir),
        "provider": provider,
        "with_subscriptions": with_subscriptions,
    }
