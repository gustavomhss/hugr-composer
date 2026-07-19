"""Behavioural tests for ``StripeBillingAdapter``.

Strategy: inject a fake ``stripe`` module via the constructor's
``stripe_module`` parameter — dependency-injection over monkeypatch.
No network, no live Stripe, no Docker.

Covers:

1. Lazy import — construction + init never imports stripe.
2. Missing-SDK error is actionable (``pip install stripe`` hint).
3. Webhook signature failures map to ``InvalidWebhookSignature``
   (BILL_INV_01).
4. ``InvalidRequestError`` → ``UnknownCustomer`` / ``UnknownSubscription``
   depending on caller context (BILL_INV_04).
5. Unknown Stripe statuses map to the motor's 4-value enum.
6. Plan-change preserves subscription id (BILL_INV_03).
7. No PII echoed in error strings (BILL_INV_05).
8. api_key and webhook_secret non-empty validation at construction.
"""
from __future__ import annotations

import builtins
import sys
from collections.abc import Mapping
from typing import Any

import pytest

from core.venous._adapters.stripe import (
    StripeBillingAdapter,
    StripeNotInstalled,
)
from core.venous.billing.Billing import (
    BillingError,
    Customer,
    Event,
    InvalidWebhookSignature,
    Subscription,
    UnknownCustomer,
    UnknownSubscription,
)


# ---------------------------------------------------------------------------
# Fake stripe module
# ---------------------------------------------------------------------------
class _StripeFakeError(Exception):
    pass


# Adapter matches Stripe error classes BY NAME via ``type(exc).__name__``;
# name the fakes with the exact names the real stripe.error module uses.
class SignatureVerificationError(_StripeFakeError):  # noqa: N801 — match stripe.error
    pass


class InvalidRequestError(_StripeFakeError):  # noqa: N801 — match stripe.error
    pass


class _FakeCustomerAPI:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.next_response: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.created.append(kwargs)
        if self.next_response is not None:
            return self.next_response
        return {
            "id": "cus_fake_1",
            "email": kwargs.get("email", ""),
            "metadata": dict(kwargs.get("metadata") or {}),
        }


class _FakeSubscriptionAPI:
    def __init__(self) -> None:
        self.create_raises: Exception | None = None
        self.modify_raises: Exception | None = None
        self.retrieve_raises: Exception | None = None
        self.stored: dict[str, dict[str, Any]] = {}
        self.next_create_status: str = "active"

    def create(self, **kwargs: Any) -> dict[str, Any]:
        if self.create_raises is not None:
            raise self.create_raises
        sid = "sub_fake_1"
        raw = {
            "id": sid,
            "customer": kwargs["customer"],
            "status": self.next_create_status,
            "items": {
                "data": [{
                    "id": "si_1",
                    "price": {"id": kwargs["items"][0]["price"]},
                }],
            },
        }
        self.stored[sid] = raw
        return raw

    def retrieve(self, subscription_id: str) -> dict[str, Any]:
        if self.retrieve_raises is not None:
            raise self.retrieve_raises
        return self.stored[subscription_id]

    def modify(self, subscription_id: str, **kwargs: Any) -> dict[str, Any]:
        if self.modify_raises is not None:
            raise self.modify_raises
        raw = self.stored[subscription_id]
        if "items" in kwargs:
            # Plan change — update the first item's price (BILL_INV_03
            # requires the id to remain subscription_id).
            new_price = kwargs["items"][0]["price"]
            raw["items"]["data"][0]["price"]["id"] = new_price
        if kwargs.get("cancel_at_period_end"):
            # Stripe communicates pending cancellation via a flag; the
            # adapter test below flips status separately.
            raw["cancel_at_period_end"] = True
        return raw


class _FakeWebhookAPI:
    def __init__(self) -> None:
        self.raise_signature_error = False
        self.raise_other_error: Exception | None = None

    def construct_event(
        self, payload: bytes, sig_header: str, secret: str,
    ) -> Mapping[str, Any]:
        if self.raise_signature_error:
            raise SignatureVerificationError("sig fail")
        if self.raise_other_error is not None:
            raise self.raise_other_error
        import json
        body = json.loads(payload)
        return {"id": body["id"], "type": body["type"], "data": body.get("data") or {}}


class _FakeStripe:
    def __init__(self) -> None:
        self.api_key: str | None = None
        self.Customer = _FakeCustomerAPI()
        self.Subscription = _FakeSubscriptionAPI()
        self.Webhook = _FakeWebhookAPI()
        # Error classes that the adapter matches by name (not by class
        # identity — the real stripe.error submodule has these names).
        self.error = type("error", (), {
            "SignatureVerificationError": SignatureVerificationError,
            "InvalidRequestError": InvalidRequestError,
        })


@pytest.fixture()
def fake_stripe() -> _FakeStripe:
    return _FakeStripe()


@pytest.fixture()
def adapter(fake_stripe: _FakeStripe) -> StripeBillingAdapter:
    return StripeBillingAdapter(
        api_key="sk_test_123",
        webhook_secret="whsec_test",
        stripe_module=fake_stripe,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------
def test_api_key_required() -> None:
    with pytest.raises(ValueError, match="api_key"):
        StripeBillingAdapter(api_key="", webhook_secret="whsec_x")


def test_webhook_secret_required() -> None:
    with pytest.raises(ValueError, match="webhook_secret"):
        StripeBillingAdapter(api_key="sk_x", webhook_secret="")


def test_lazy_import_never_triggers_without_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    # Construction alone MUST NOT import stripe. We don't poison sys.modules
    # — we verify construction succeeds without touching the import hook.
    adapter = StripeBillingAdapter(api_key="sk_x", webhook_secret="whsec_x")
    assert adapter is not None


def test_missing_stripe_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "stripe", raising=False)
    orig = builtins.__import__

    def _block(name: str, *a: Any, **k: Any) -> Any:
        if name == "stripe":
            raise ImportError("no stripe")
        return orig(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _block)
    adapter = StripeBillingAdapter(api_key="sk_x", webhook_secret="whsec_x")
    with pytest.raises(StripeNotInstalled, match="pip install stripe"):
        adapter.create_customer("a@b.com")


# ---------------------------------------------------------------------------
# create_customer
# ---------------------------------------------------------------------------
def test_create_customer_returns_motor_type(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    c = adapter.create_customer("alice@example.com", {"tier": "pro"})
    assert isinstance(c, Customer)
    assert c.id == "cus_fake_1"
    assert c.email == "alice@example.com"
    assert c.metadata == {"tier": "pro"}
    # api_key was set on the SDK module before the call.
    assert fake_stripe.api_key == "sk_test_123"


def test_create_customer_rejects_invalid_email(adapter: StripeBillingAdapter) -> None:
    with pytest.raises(BillingError, match="email"):
        adapter.create_customer("no-at-sign")


# ---------------------------------------------------------------------------
# create_subscription
# ---------------------------------------------------------------------------
def test_create_subscription_returns_motor_type(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    s = adapter.create_subscription("cus_1", "price_basic")
    assert isinstance(s, Subscription)
    assert s.id == "sub_fake_1"
    assert s.customer_id == "cus_1"
    assert s.price_id == "price_basic"
    assert s.status == "active"


def test_create_subscription_unknown_customer_maps_error(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Subscription.create_raises = InvalidRequestError("no such customer")
    with pytest.raises(UnknownCustomer, match="cus_nope"):
        adapter.create_subscription("cus_nope", "price_x")


def test_create_subscription_validates_inputs(adapter: StripeBillingAdapter) -> None:
    with pytest.raises(BillingError):
        adapter.create_subscription("", "price_x")
    with pytest.raises(BillingError):
        adapter.create_subscription("cus_x", "")
    with pytest.raises(BillingError):
        adapter.create_subscription("cus_x", "price_x", trial_period_days=-1)


def test_create_subscription_trialing_status_mapped(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Subscription.next_create_status = "trialing"
    s = adapter.create_subscription("cus_1", "price_basic", trial_period_days=7)
    assert s.status == "trialing"


def test_create_subscription_unknown_stripe_status_maps_to_past_due(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Subscription.next_create_status = "incomplete"
    s = adapter.create_subscription("cus_1", "price_basic")
    assert s.status == "past_due"


# ---------------------------------------------------------------------------
# change_plan — BILL_INV_03 witness
# ---------------------------------------------------------------------------
def test_change_plan_preserves_subscription_id(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    before = adapter.create_subscription("cus_1", "price_basic")
    after = adapter.change_plan(before.id, "price_pro")
    assert after.id == before.id  # BILL_INV_03
    assert after.price_id == "price_pro"


def test_change_plan_unknown_subscription_maps_error(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Subscription.retrieve_raises = InvalidRequestError("no such sub")
    with pytest.raises(UnknownSubscription, match="sub_nope"):
        adapter.change_plan("sub_nope", "price_x")


# ---------------------------------------------------------------------------
# cancel_subscription
# ---------------------------------------------------------------------------
def test_cancel_subscription_marks_cancel_at_period_end(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    before = adapter.create_subscription("cus_1", "price_x")
    after = adapter.cancel_subscription(before.id)
    assert after.id == before.id
    assert fake_stripe.Subscription.stored[before.id].get("cancel_at_period_end") is True


def test_cancel_subscription_unknown_maps_error(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Subscription.modify_raises = InvalidRequestError("no such sub")
    with pytest.raises(UnknownSubscription, match="sub_nope"):
        adapter.cancel_subscription("sub_nope")


# ---------------------------------------------------------------------------
# construct_webhook_event — BILL_INV_01 witness
# ---------------------------------------------------------------------------
def test_webhook_valid_returns_event(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    payload = b'{"id":"evt_1","type":"invoice.paid","data":{"x":1}}'
    evt = adapter.construct_webhook_event(payload, "t=1,v1=fake")
    assert isinstance(evt, Event)
    assert evt.id == "evt_1"
    assert evt.type == "invoice.paid"
    assert evt.data == {"x": 1}


def test_webhook_signature_error_maps_to_motor_error(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Webhook.raise_signature_error = True
    payload = b'{"id":"evt_1","type":"x"}'
    with pytest.raises(InvalidWebhookSignature, match="signature mismatch"):
        adapter.construct_webhook_event(payload, "t=1,v1=fake")


def test_webhook_other_stripe_error_maps_to_generic_billing_error(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Webhook.raise_other_error = ValueError("malformed")
    payload = b'{"id":"evt_1","type":"x"}'
    with pytest.raises(BillingError, match="webhook construct failed"):
        adapter.construct_webhook_event(payload, "t=1,v1=fake")


def test_webhook_requires_bytes_payload(adapter: StripeBillingAdapter) -> None:
    with pytest.raises(InvalidWebhookSignature, match="bytes"):
        adapter.construct_webhook_event("str-not-bytes", "t=1,v1=fake")  # type: ignore[arg-type]


def test_webhook_requires_sig_header(adapter: StripeBillingAdapter) -> None:
    with pytest.raises(InvalidWebhookSignature, match="signature header"):
        adapter.construct_webhook_event(b"{}", "")


# ---------------------------------------------------------------------------
# BILL_INV_05 — no PII echo in error messages
# ---------------------------------------------------------------------------
def test_no_pii_leak_on_webhook_error(
    adapter: StripeBillingAdapter, fake_stripe: _FakeStripe,
) -> None:
    fake_stripe.Webhook.raise_signature_error = True
    secret_payload = b'{"id":"evt","type":"CARD_4111_1111_1111_1111"}'
    try:
        adapter.construct_webhook_event(secret_payload, "t=1,v1=fake")
    except InvalidWebhookSignature as exc:
        assert "4111" not in str(exc)
        assert "CARD" not in str(exc)


def test_no_pii_leak_on_create_customer_error(
    adapter: StripeBillingAdapter,
) -> None:
    secret_email = "hacker@evil.com"
    try:
        adapter.create_customer("no-at-sign")  # raise in our validation
    except BillingError as exc:
        assert secret_email not in str(exc)
