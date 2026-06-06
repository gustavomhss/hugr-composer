"""Tests for the Stripe-billing example."""
from __future__ import annotations

import json

import pytest

from app import BillingService, SignatureVerifier


SECRET = b"whsec_test"


def _svc() -> BillingService:
    return BillingService(SignatureVerifier(SECRET))


def _event(eid: str, kind: str, **data) -> tuple[bytes, str]:
    body = json.dumps({"id": eid, "type": kind, "data": data}).encode()
    sig = SignatureVerifier(SECRET).sign(body)
    return body, sig


def test_duplicate_webhook_updates_state_exactly_once() -> None:
    svc = _svc()
    svc.upsert_customer("cus_1", plan="team")
    body, sig = _event("evt_1", "customer.subscription.updated",
                       customer_id="cus_1", plan="enterprise")
    assert svc.handle_webhook(body, sig) == (200, "ok")
    assert svc.handle_webhook(body, sig) == (200, "duplicate")
    assert svc.get("cus_1").plan == "enterprise"


def test_bad_signature_returns_401_without_mutation() -> None:
    svc = _svc()
    svc.upsert_customer("cus_1", plan="team")
    body, _ = _event("evt_bad", "customer.subscription.updated",
                     customer_id="cus_1", plan="enterprise")
    code, _ = svc.handle_webhook(body, "deadbeef")
    assert code == 401
    assert svc.get("cus_1").plan == "team"


def test_plan_change_reflected_within_one_webhook_roundtrip() -> None:
    svc = _svc()
    svc.upsert_customer("cus_1", plan="free")
    body, sig = _event("evt_up", "customer.subscription.updated",
                       customer_id="cus_1", plan="team")
    svc.handle_webhook(body, sig)
    # Read path does not call Stripe — it uses the server record.
    assert svc.get("cus_1").plan == "team"


def test_grace_job_is_idempotent_per_day() -> None:
    svc = _svc()
    svc.upsert_customer("cus_1", plan="team")
    body, sig = _event("evt_pd", "customer.subscription.updated",
                       customer_id="cus_1", status="past_due",
                       past_due_at=0.0)
    svc.handle_webhook(body, sig)
    # Day 8 — past-due for 7 days, should trigger.
    notified_a = svc.run_grace_job(now=8 * 86400, day_key=8)
    notified_b = svc.run_grace_job(now=8 * 86400, day_key=8)
    assert notified_a == ["cus_1"]
    assert notified_b == []  # idempotent
    assert svc.notifications() == ["cus_1"]


def test_cancel_at_period_end_keeps_access_until_boundary() -> None:
    svc = _svc()
    svc.upsert_customer("cus_1", plan="team", period_end=1000.0)
    body, sig = _event("evt_cap", "customer.subscription.updated",
                       customer_id="cus_1", cancel_at_period_end=True)
    svc.handle_webhook(body, sig)
    assert svc.has_premium_access("cus_1", now=500.0) is True
    assert svc.has_premium_access("cus_1", now=1000.0) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
