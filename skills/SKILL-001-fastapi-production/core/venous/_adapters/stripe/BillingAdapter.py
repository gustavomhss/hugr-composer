"""Stripe adapter for the ``billing.Billing`` primitive.

Wires the Stripe Python SDK to the motor Protocol so generated FastAPI
apps can depend on a provider-agnostic interface:

    from core.venous.billing.Billing import Billing
    from core.venous._adapters.stripe import StripeBillingAdapter

    gw: Billing = StripeBillingAdapter(
        api_key=settings.STRIPE_SECRET_KEY,
        webhook_secret=settings.STRIPE_WEBHOOK_SECRET,
    )

Design:

- ``stripe`` is imported LAZILY inside the first call that needs a live
  client. A FastAPI app can boot (and import this module) without the
  SDK installed; the missing-dep error is raised only when a billing
  call actually runs. Matches the Bulkhead / PubSub adapter convention.
- Webhook verification delegates to ``stripe.Webhook.construct_event``
  which implements the same HMAC-SHA256 scheme the motor expects
  (BILL_INV_01).
- Status mapping converts Stripe's wider status set (``incomplete``,
  ``incomplete_expired``, ``unpaid``, …) into the motor's 4-value
  enum. Unknown / transitional Stripe statuses map to ``past_due`` so
  the app can drive retries from a single state.
- All methods return motor value types (``Customer`` / ``Subscription``
  / ``Event``) — callers never couple to Stripe's dicts. The raw
  stripe object is NOT leaked.

Errors: Stripe SDK errors (``stripe.error.SignatureVerificationError``,
``stripe.error.InvalidRequestError``) are translated into motor errors
(``InvalidWebhookSignature``, ``UnknownCustomer`` /
``UnknownSubscription``) to preserve the abstraction.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast

from core.venous.billing.Billing import (
    BillingError,
    Customer,
    Event,
    InvalidWebhookSignature,
    Subscription,
    SubscriptionStatus,
    UnknownCustomer,
    UnknownSubscription,
)


__all__ = [
    "StripeBillingAdapter",
    "StripeNotInstalled",
]


# Stripe statuses that do not fit the motor's 4-value enum are mapped
# here. See https://stripe.com/docs/api/subscriptions/object#subscription_object-status
_STRIPE_TO_MOTOR_STATUS: Final[Mapping[str, SubscriptionStatus]] = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    # Transitional states — default to past_due so the app drives retry
    # from a single lane. BILL_INV_02's monotonicity is preserved because
    # a Stripe ``canceled`` always maps to motor ``canceled``.
    "incomplete": "past_due",
    "incomplete_expired": "canceled",
    "unpaid": "past_due",
    "paused": "past_due",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class StripeNotInstalled(ImportError):
    """Raised when a Stripe-dependent call runs without the SDK installed."""


# ---------------------------------------------------------------------------
# StripeBillingAdapter
# ---------------------------------------------------------------------------
class StripeBillingAdapter:
    """``billing.Billing`` adapter backed by the Stripe Python SDK.

    Args:
        api_key: Stripe secret key (``sk_live_…`` / ``sk_test_…``). Required.
        webhook_secret: Stripe webhook endpoint secret (``whsec_…``). Required.
        stripe_module: Optional override used in tests to inject a fake
            ``stripe`` module (dependency injection over monkeypatch).

    Satisfies the ``Billing`` Protocol. Raises ``StripeNotInstalled``
    if the SDK is missing when the first call runs.
    """

    __slots__ = ("_api_key", "_webhook_secret", "_stripe_module")

    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        stripe_module: Any = None,
    ) -> None:
        if not isinstance(api_key, str) or api_key == "":
            raise ValueError("StripeBillingAdapter requires a non-empty api_key.")
        if not isinstance(webhook_secret, str) or webhook_secret == "":
            raise ValueError(
                "StripeBillingAdapter requires a non-empty webhook_secret "
                "(BILL_INV_01: signature verification cannot be bypassed).",
            )
        self._api_key: str = api_key
        self._webhook_secret: str = webhook_secret
        self._stripe_module: Any = stripe_module

    # ---- lazy SDK import --------------------------------------------------
    def _get_stripe(self) -> Any:
        """Return a configured ``stripe`` module (lazy import).

        Raises:
            StripeNotInstalled: the ``stripe`` package is missing.
        """
        if self._stripe_module is not None:
            mod = self._stripe_module
        else:
            try:
                import stripe as mod  # noqa: PLC0415
            except ImportError as exc:
                raise StripeNotInstalled(
                    "StripeBillingAdapter requires the `stripe` package. "
                    "Install via `pip install stripe>=8`.",
                ) from exc
        # API key is set per-call so app boot never triggers an outbound
        # call — matches Stripe's recommended pattern for short-lived
        # requests.
        mod.api_key = self._api_key
        return mod

    # ---- customers --------------------------------------------------------
    def create_customer(
        self, email: str, metadata: Mapping[str, str] | None = None,
    ) -> Customer:
        if not isinstance(email, str) or "@" not in email:
            raise BillingError("email MUST be a string containing '@'.")
        stripe = self._get_stripe()
        raw = stripe.Customer.create(
            email=email, metadata=dict(metadata or {}),
        )
        return Customer(
            id=str(raw["id"]),
            email=str(raw.get("email", email)),
            metadata=dict(raw.get("metadata") or {}),
        )

    # ---- subscriptions ----------------------------------------------------
    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_period_days: int | None = None,
    ) -> Subscription:
        if not isinstance(customer_id, str) or customer_id == "":
            raise BillingError("customer_id MUST be a non-empty string.")
        if not isinstance(price_id, str) or price_id == "":
            raise BillingError("price_id MUST be a non-empty string.")
        if trial_period_days is not None and (
            not isinstance(trial_period_days, int) or trial_period_days < 0
        ):
            raise BillingError("trial_period_days MUST be int >= 0 or None.")
        stripe = self._get_stripe()
        params: dict[str, Any] = {
            "customer": customer_id,
            "items": [{"price": price_id}],
        }
        if trial_period_days:
            params["trial_period_days"] = trial_period_days
        try:
            raw = stripe.Subscription.create(**params)
        except Exception as exc:
            self._reraise_stripe_error(exc, customer_id=customer_id)
            raise  # unreachable — _reraise always raises
        return _subscription_from_stripe(raw, fallback_price=price_id)

    def cancel_subscription(self, subscription_id: str) -> Subscription:
        if not isinstance(subscription_id, str) or subscription_id == "":
            raise BillingError("subscription_id MUST be a non-empty string.")
        stripe = self._get_stripe()
        try:
            raw = stripe.Subscription.modify(
                subscription_id, cancel_at_period_end=True,
            )
        except Exception as exc:
            self._reraise_stripe_error(exc, subscription_id=subscription_id)
            raise
        return _subscription_from_stripe(raw)

    def change_plan(self, subscription_id: str, new_price_id: str) -> Subscription:
        if not isinstance(subscription_id, str) or subscription_id == "":
            raise BillingError("subscription_id MUST be a non-empty string.")
        if not isinstance(new_price_id, str) or new_price_id == "":
            raise BillingError("new_price_id MUST be a non-empty string.")
        stripe = self._get_stripe()
        try:
            current = stripe.Subscription.retrieve(subscription_id)
            item_id = current["items"]["data"][0]["id"]
            raw = stripe.Subscription.modify(
                subscription_id,
                items=[{"id": item_id, "price": new_price_id}],
                proration_behavior="create_prorations",
            )
        except Exception as exc:
            self._reraise_stripe_error(exc, subscription_id=subscription_id)
            raise
        # BILL_INV_03: id preserved by construction (same ``subscription_id``
        # went in, provider returns the same id back).
        return _subscription_from_stripe(raw, fallback_price=new_price_id)

    # ---- webhook verification --------------------------------------------
    def construct_webhook_event(self, payload: bytes, sig_header: str) -> Event:
        if not isinstance(payload, (bytes, bytearray)):
            raise InvalidWebhookSignature("payload MUST be bytes.")
        if not isinstance(sig_header, str) or sig_header == "":
            raise InvalidWebhookSignature("missing signature header.")
        stripe = self._get_stripe()
        try:
            raw = stripe.Webhook.construct_event(
                payload, sig_header, self._webhook_secret,
            )
        except Exception as exc:
            # Stripe raises SignatureVerificationError on any mismatch.
            # Map to motor error without echoing payload (BILL_INV_05).
            name = type(exc).__name__
            if name == "SignatureVerificationError":
                raise InvalidWebhookSignature("signature mismatch.") from exc
            # Other errors (e.g. malformed JSON) are generic billing errors.
            raise BillingError(f"webhook construct failed: {name}.") from exc
        data_obj: Mapping[str, Any] = {}
        if isinstance(raw, Mapping):
            raw_data = raw.get("data")
            if isinstance(raw_data, Mapping):
                data_obj = cast(Mapping[str, Any], raw_data)
        return Event(
            id=str(raw["id"]) if isinstance(raw, Mapping) else "",
            type=str(raw["type"]) if isinstance(raw, Mapping) else "",
            data=dict(data_obj),
        )

    # ---- error translation ------------------------------------------------
    def _reraise_stripe_error(
        self, exc: Exception, *,
        customer_id: str | None = None,
        subscription_id: str | None = None,
    ) -> None:
        """Translate a Stripe SDK error into the motor's error hierarchy.

        Stripe's ``InvalidRequestError`` covers both "no such customer"
        and "no such subscription" — the caller context tells us which.
        Preserves the original exception as ``__cause__`` for ops.
        """
        name = type(exc).__name__
        # Do not echo customer/subscription ids the caller didn't pass
        # back — id echoes are allowed (caller already knows them) but
        # nothing else from exc is surfaced (BILL_INV_05).
        if name in ("InvalidRequestError", "ResourceNotFoundError"):
            if subscription_id is not None:
                raise UnknownSubscription(
                    f"stripe: no subscription with id={subscription_id!r}.",
                ) from exc
            if customer_id is not None:
                raise UnknownCustomer(
                    f"stripe: no customer with id={customer_id!r}.",
                ) from exc
        # Anything else: generic billing error without payload echo.
        raise BillingError(f"stripe call failed: {name}.") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _subscription_from_stripe(
    raw: Mapping[str, Any], *, fallback_price: str | None = None,
) -> Subscription:
    """Translate a Stripe Subscription object into the motor value type.

    We accept Stripe's loose mapping (it's neither a TypedDict nor a
    concrete class at this layer) and normalise fields we care about.
    """
    items = raw.get("items") or {}
    data = (items.get("data") if isinstance(items, Mapping) else None) or []
    price_id: str = fallback_price or ""
    if data and isinstance(data[0], Mapping):
        price = data[0].get("price") or {}
        if isinstance(price, Mapping):
            pid = price.get("id")
            if isinstance(pid, str) and pid:
                price_id = pid
    stripe_status = str(raw.get("status", "active"))
    status: SubscriptionStatus = _STRIPE_TO_MOTOR_STATUS.get(
        stripe_status, "past_due",
    )
    # Stripe communicates pending cancellation via cancel_at_period_end;
    # once the provider fires the `customer.subscription.deleted` webhook,
    # status flips to `canceled`. We do NOT pre-empt that here — the
    # motor's lifecycle is driven by verified webhook events.
    return Subscription(
        id=str(raw["id"]),
        customer_id=str(raw.get("customer", "")),
        price_id=price_id,
        status=status,
        trial_period_days=None,
    )
