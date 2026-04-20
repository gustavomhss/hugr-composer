"""Stripe-billed SaaS — signature verify + idempotent events + grace window."""
from __future__ import annotations

import hashlib
import hmac
import threading
from dataclasses import dataclass, field
from typing import Literal


PlanStatus = Literal["active", "past_due", "read_only", "canceled"]


@dataclass
class Customer:
    id: str
    plan: str = "free"
    status: PlanStatus = "active"
    past_due_since: float | None = None
    cancel_at_period_end: bool = False
    period_end: float = 0.0


class SignatureVerifier:
    """Mirror of `SignatureVerifier` primitive (HMAC-SHA256)."""

    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    def sign(self, body: bytes) -> str:
        return hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    def verify(self, body: bytes, signature: str) -> bool:
        expected = self.sign(body)
        return hmac.compare_digest(expected, signature or "")


class IdempotentConsumer:
    """Mirror of `IdempotentConsumer` primitive. At-most-once per event_id."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def seen(self, event_id: str) -> bool:
        with self._lock:
            if event_id in self._seen:
                return True
            self._seen.add(event_id)
            return False


class BillingService:
    def __init__(self, verifier: SignatureVerifier) -> None:
        self._verifier = verifier
        self._dedup = IdempotentConsumer()
        self._customers: dict[str, Customer] = {}
        self._notifications: list[str] = []
        self._transition_days: set[tuple[str, int]] = set()
        self._lock = threading.Lock()

    def upsert_customer(self, customer_id: str, *, plan: str = "free",
                        period_end: float = 0.0) -> Customer:
        with self._lock:
            c = self._customers.setdefault(customer_id, Customer(id=customer_id))
            c.plan = plan
            c.period_end = period_end
            return c

    def get(self, customer_id: str) -> Customer | None:
        with self._lock:
            c = self._customers.get(customer_id)
            return None if c is None else Customer(**c.__dict__)

    def handle_webhook(self, body: bytes, signature: str) -> tuple[int, str]:
        """Returns (status_code, message)."""
        if not self._verifier.verify(body, signature):
            return 401, "bad signature"
        import json
        try:
            event = json.loads(body.decode())
        except Exception:
            return 400, "bad body"
        eid = event.get("id") or ""
        if not eid:
            return 400, "missing event id"
        if self._dedup.seen(eid):
            return 200, "duplicate"
        self._apply(event)
        return 200, "ok"

    def _apply(self, event: dict) -> None:
        kind = event.get("type")
        data = event.get("data", {})
        cid = data.get("customer_id", "")
        with self._lock:
            c = self._customers.setdefault(cid, Customer(id=cid))
            if kind == "invoice.paid":
                c.status = "active"
                c.past_due_since = None
            elif kind == "customer.subscription.updated":
                c.plan = data.get("plan", c.plan)
                c.period_end = data.get("period_end", c.period_end)
                if data.get("status") == "past_due":
                    c.status = "past_due"
                    c.past_due_since = data.get("past_due_at", 0.0)
                if data.get("cancel_at_period_end"):
                    c.cancel_at_period_end = True
            elif kind == "customer.subscription.deleted":
                c.status = "canceled"
                c.plan = "free"

    def run_grace_job(self, *, now: float, day_key: int) -> list[str]:
        """Idempotent: same day_key produces no extra notifications."""
        notified: list[str] = []
        with self._lock:
            for c in self._customers.values():
                if c.status != "past_due" or c.past_due_since is None:
                    continue
                if now - c.past_due_since < 7 * 86400:
                    continue
                key = (c.id, day_key)
                if key in self._transition_days:
                    continue
                self._transition_days.add(key)
                c.status = "read_only"
                self._notifications.append(c.id)
                notified.append(c.id)
        return notified

    def notifications(self) -> list[str]:
        with self._lock:
            return list(self._notifications)

    def has_premium_access(self, customer_id: str, *, now: float) -> bool:
        with self._lock:
            c = self._customers.get(customer_id)
            if c is None or c.status in ("canceled", "read_only"):
                return False
            if c.cancel_at_period_end and now >= c.period_end:
                return False
            return c.plan != "free"
