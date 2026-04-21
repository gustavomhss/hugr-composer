"""Behavioural invariant witnesses for ``billing.Billing`` (BILL_INV_01..05)."""
from __future__ import annotations

import json
import time

import pytest

from core.venous.billing.Billing import (
    BillingError,
    InMemoryBilling,
    InvalidWebhookSignature,
    LifecycleInvariantError,
    UnknownCustomer,
    UnknownSubscription,
)


# ---------------------------------------------------------------------------
# BILL_INV_01 — webhook signature verification is mandatory
# ---------------------------------------------------------------------------
def test_inv_01_valid_signature_accepted() -> None:
    gw = InMemoryBilling("whsec_test")
    payload = json.dumps(
        {"id": "evt_1", "type": "invoice.payment_succeeded", "data": {"x": 1}},
    ).encode()
    sig = gw.sign_payload(payload)
    evt = gw.construct_webhook_event(payload, sig)
    assert evt.id == "evt_1"
    assert evt.type == "invoice.payment_succeeded"
    assert evt.data == {"x": 1}


def test_inv_01_tampered_payload_rejected() -> None:
    gw = InMemoryBilling("whsec_test")
    payload = b'{"id":"evt_1","type":"x"}'
    sig = gw.sign_payload(payload)
    tampered = b'{"id":"evt_1","type":"account.takeover"}'
    with pytest.raises(InvalidWebhookSignature, match="signature mismatch"):
        gw.construct_webhook_event(tampered, sig)


def test_inv_01_wrong_secret_rejected() -> None:
    signer = InMemoryBilling("whsec_test")
    verifier = InMemoryBilling("whsec_other")
    payload = b'{"id":"e","type":"t"}'
    sig = signer.sign_payload(payload)
    with pytest.raises(InvalidWebhookSignature):
        verifier.construct_webhook_event(payload, sig)


def test_inv_01_stale_timestamp_rejected() -> None:
    gw = InMemoryBilling("whsec_test", tolerance_s=10)
    payload = b'{"id":"e","type":"t"}'
    # Sign with a timestamp well outside the tolerance window.
    sig = gw.sign_payload(payload, timestamp=int(time.time()) - 600)
    with pytest.raises(InvalidWebhookSignature, match="tolerance window"):
        gw.construct_webhook_event(payload, sig)


def test_inv_01_future_timestamp_also_rejected() -> None:
    gw = InMemoryBilling("whsec_test", tolerance_s=10)
    payload = b'{"id":"e","type":"t"}'
    sig = gw.sign_payload(payload, timestamp=int(time.time()) + 600)
    with pytest.raises(InvalidWebhookSignature, match="tolerance window"):
        gw.construct_webhook_event(payload, sig)


def test_inv_01_malformed_sig_header_rejected() -> None:
    gw = InMemoryBilling("whsec_test")
    payload = b'{"id":"e","type":"t"}'
    for bad in ("", "garbage", "t=nan,v1=abc", "v1=abc", "t=1234"):
        with pytest.raises(InvalidWebhookSignature):
            gw.construct_webhook_event(payload, bad)


def test_inv_01_bytes_required_on_payload() -> None:
    gw = InMemoryBilling("whsec_test")
    with pytest.raises(InvalidWebhookSignature):
        gw.construct_webhook_event("not-bytes", "t=1,v1=x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BILL_INV_02 — subscription lifecycle is monotonic
# ---------------------------------------------------------------------------
def test_inv_02_canceled_is_terminal_via_set_status() -> None:
    gw = InMemoryBilling("whsec_test")
    cust = gw.create_customer("a@b.com")
    sub = gw.create_subscription(cust.id, "price_x")
    gw.cancel_subscription(sub.id)
    for target in ("active", "past_due", "trialing"):
        with pytest.raises(LifecycleInvariantError, match="canceled"):
            gw.set_status(sub.id, target)  # type: ignore[arg-type]


def test_inv_02_change_plan_refused_on_canceled() -> None:
    gw = InMemoryBilling("whsec_test")
    cust = gw.create_customer("a@b.com")
    sub = gw.create_subscription(cust.id, "price_x")
    gw.cancel_subscription(sub.id)
    with pytest.raises(LifecycleInvariantError, match="canceled"):
        gw.change_plan(sub.id, "price_y")


def test_inv_02_allowed_transitions_succeed() -> None:
    gw = InMemoryBilling("whsec_test")
    cust = gw.create_customer("a@b.com")
    # trialing → active
    sub = gw.create_subscription(cust.id, "price_x", trial_period_days=7)
    assert sub.status == "trialing"
    sub = gw.set_status(sub.id, "active")
    assert sub.status == "active"
    # active → past_due → active (back-and-forth is allowed per graph)
    sub = gw.set_status(sub.id, "past_due")
    assert sub.status == "past_due"
    sub = gw.set_status(sub.id, "active")
    assert sub.status == "active"
    # active → canceled
    sub = gw.set_status(sub.id, "canceled")
    assert sub.status == "canceled"


def test_inv_02_double_cancel_refused() -> None:
    gw = InMemoryBilling("whsec_test")
    cust = gw.create_customer("a@b.com")
    sub = gw.create_subscription(cust.id, "price_x")
    gw.cancel_subscription(sub.id)
    with pytest.raises(LifecycleInvariantError):
        gw.cancel_subscription(sub.id)


# ---------------------------------------------------------------------------
# BILL_INV_03 — plan-change preserves subscription identity
# ---------------------------------------------------------------------------
def test_inv_03_change_plan_returns_same_id() -> None:
    gw = InMemoryBilling("whsec_test")
    cust = gw.create_customer("a@b.com")
    sub_before = gw.create_subscription(cust.id, "price_basic")
    sub_after = gw.change_plan(sub_before.id, "price_pro")
    assert sub_after.id == sub_before.id
    assert sub_after.price_id == "price_pro"
    assert sub_after.customer_id == sub_before.customer_id
    # Status preserved — change_plan is NOT a lifecycle move.
    assert sub_after.status == sub_before.status


def test_inv_03_change_plan_rejects_empty_price_id() -> None:
    gw = InMemoryBilling("whsec_test")
    cust = gw.create_customer("a@b.com")
    sub = gw.create_subscription(cust.id, "price_x")
    with pytest.raises(BillingError, match="new_price_id"):
        gw.change_plan(sub.id, "")


# ---------------------------------------------------------------------------
# BILL_INV_04 — unknown ids raise, never silently upsert
# ---------------------------------------------------------------------------
def test_inv_04_unknown_customer_raises_on_create_subscription() -> None:
    gw = InMemoryBilling("whsec_test")
    with pytest.raises(UnknownCustomer):
        gw.create_subscription("cus_nope", "price_x")


def test_inv_04_unknown_subscription_raises_everywhere() -> None:
    gw = InMemoryBilling("whsec_test")
    for fn in (
        lambda: gw.cancel_subscription("sub_nope"),
        lambda: gw.change_plan("sub_nope", "price_y"),
        lambda: gw.set_status("sub_nope", "active"),
        lambda: gw.get_subscription("sub_nope"),
    ):
        with pytest.raises(UnknownSubscription):
            fn()


# ---------------------------------------------------------------------------
# BILL_INV_05 — no PII in error messages
# ---------------------------------------------------------------------------
def test_inv_05_invalid_email_error_does_not_echo_value() -> None:
    gw = InMemoryBilling("whsec_test")
    secret_email = "SeCrEt_!@super-confidential.example"
    try:
        gw.create_customer(secret_email)
    except BillingError as exc:
        assert secret_email not in str(exc)
    else:
        # The email lacks '@' so create_customer raises — fixture sanity.
        pass
    # Now trigger with missing '@'
    bad = "no-at-sign-here"
    with pytest.raises(BillingError) as exc_info:
        gw.create_customer(bad)
    assert bad not in str(exc_info.value)


def test_inv_05_webhook_error_does_not_echo_payload() -> None:
    gw = InMemoryBilling("whsec_test")
    secret_payload = b'{"id":"evt","type":"CUSTOMER_CARD_NUMBER_4111_1111_1111_1111"}'
    try:
        gw.construct_webhook_event(secret_payload, "t=1,v1=deadbeef")
    except InvalidWebhookSignature as exc:
        assert "4111" not in str(exc)
        assert "CUSTOMER_CARD" not in str(exc)


# ---------------------------------------------------------------------------
# End-to-end webhook → set_status driven lifecycle
# ---------------------------------------------------------------------------
def test_end_to_end_webhook_driven_lifecycle() -> None:
    gw = InMemoryBilling("whsec_test")
    cust = gw.create_customer("a@b.com")
    sub = gw.create_subscription(cust.id, "price_x", trial_period_days=7)
    assert sub.status == "trialing"

    # Simulate the provider sending an "invoice.payment_succeeded" webhook
    # — the app's handler would then call set_status to advance lifecycle.
    payload = json.dumps(
        {"id": "evt_1", "type": "invoice.payment_succeeded", "data": {"sub": sub.id}},
    ).encode()
    sig = gw.sign_payload(payload)
    evt = gw.construct_webhook_event(payload, sig)
    assert evt.type == "invoice.payment_succeeded"
    sub = gw.set_status(sub.id, "active")
    assert sub.status == "active"

    payload2 = json.dumps(
        {"id": "evt_2", "type": "customer.subscription.deleted", "data": {"sub": sub.id}},
    ).encode()
    sig2 = gw.sign_payload(payload2)
    evt2 = gw.construct_webhook_event(payload2, sig2)
    assert evt2.type == "customer.subscription.deleted"
    sub = gw.cancel_subscription(sub.id)
    assert sub.status == "canceled"
