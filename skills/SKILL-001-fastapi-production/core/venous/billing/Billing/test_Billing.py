"""Unit tests for ``core.venous.billing.Billing`` — API surface + construction.

Behavioural invariant coverage (BILL_INV_01..05) lives in
``behavioral_Billing.py``.
"""
from __future__ import annotations

import pytest

from core.venous.billing.Billing import (
    Billing,
    BillingError,
    Customer,
    Event,
    InMemoryBilling,
    InvalidWebhookSignature,
    LifecycleInvariantError,
    Subscription,
    UnknownCustomer,
    UnknownSubscription,
)


def test_public_surface_matches_contract() -> None:
    # Every exported name MUST be importable from the package — a drop
    # or rename breaks every adapter.
    from core.venous.billing.Billing import (  # noqa: F401
        Billing,
        BillingError,
        Customer,
        Event,
        InMemoryBilling,
        InvalidWebhookSignature,
        LifecycleInvariantError,
        Subscription,
        SubscriptionStatus,
        UnknownCustomer,
        UnknownSubscription,
    )


def test_protocol_membership() -> None:
    b = InMemoryBilling("whsec_test")
    assert isinstance(b, Billing)


def test_construction_requires_nonempty_secret() -> None:
    with pytest.raises(ValueError, match="webhook_secret"):
        InMemoryBilling("")


def test_construction_rejects_non_positive_tolerance() -> None:
    with pytest.raises(ValueError, match="tolerance_s"):
        InMemoryBilling("whsec_test", tolerance_s=0)
    with pytest.raises(ValueError, match="tolerance_s"):
        InMemoryBilling("whsec_test", tolerance_s=-5)


def test_slots_prevent_stray_state_keys() -> None:
    b = InMemoryBilling("whsec_test")
    with pytest.raises(AttributeError):
        b.not_a_field = 1  # type: ignore[attr-defined]


def test_error_hierarchy_is_common() -> None:
    # All domain errors derive from BillingError so callers can catch
    # a single exception type.
    assert issubclass(InvalidWebhookSignature, BillingError)
    assert issubclass(UnknownCustomer, BillingError)
    assert issubclass(UnknownSubscription, BillingError)
    assert issubclass(LifecycleInvariantError, BillingError)


def test_customer_subscription_event_are_frozen_dataclasses() -> None:
    c = Customer(id="cus_x", email="a@b.com", metadata={"k": "v"})
    with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError
        c.email = "hacker@evil.com"  # type: ignore[misc]
    s = Subscription(id="sub_x", customer_id="cus_x", price_id="price_y", status="active")
    with pytest.raises(Exception):
        s.status = "canceled"  # type: ignore[misc]
    e = Event(id="evt_x", type="t", data={})
    with pytest.raises(Exception):
        e.type = "u"  # type: ignore[misc]
