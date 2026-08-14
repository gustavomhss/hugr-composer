"""Billing primitive — provider-agnostic subscription + webhook gateway.

Reference implementation for ``billing.Billing``. Defines the Protocol
surface every billing adapter (Stripe, Paddle, Chargebee, …) must honour,
plus an ``InMemoryBilling`` reference backend suitable for tests and
local development.

The primitive is framework-free and provider-free. SDK-specific wiring
lives under ``core/venous/_adapters/<provider>/BillingAdapter.py``.

Invariants cited by this module:

- BILL_INV_01: **Webhook signature verification is mandatory.**
  ``construct_webhook_event`` MUST verify the signature (HMAC-SHA256 over
  the raw payload using the configured webhook secret) and raise
  ``InvalidWebhookSignature`` on mismatch. A tampered payload MUST NEVER
  be returned as a valid ``Event``.
- BILL_INV_02: **Subscription lifecycle is monotonic.** Status transitions
  follow ``trialing → active → (past_due|canceled)`` or
  ``active → (past_due|canceled)``. ``canceled`` is terminal — a canceled
  subscription MUST NEVER be observed transitioning back to ``active`` /
  ``past_due`` / ``trialing`` via this primitive.
- BILL_INV_03: **Plan-change preserves subscription identity.** Given an
  existing ``Subscription(id=X, price_id=A)``, ``change_plan(X, B)``
  returns ``Subscription(id=X, price_id=B)`` — the SAME id. The caller's
  DB row never needs re-keying.
- BILL_INV_04: **Identifiers are opaque and checked.** ``customer_id`` and
  ``subscription_id`` are provider-issued opaque tokens. Calls that
  reference an unknown id MUST raise ``UnknownCustomer`` /
  ``UnknownSubscription`` rather than silently upsert.
- BILL_INV_05: **No PII in error messages.** Errors raised by this
  primitive MUST NOT echo email addresses, metadata values, or any
  caller-supplied payload fields. Tests assert this by pattern.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal, Protocol, runtime_checkable

__all__ = [
    "Billing",
    "BillingError",
    "Customer",
    "Event",
    "InMemoryBilling",
    "InvalidWebhookSignature",
    "LifecycleInvariantError",
    "Subscription",
    "SubscriptionStatus",
    "UnknownCustomer",
    "UnknownSubscription",
]


SubscriptionStatus = Literal["trialing", "active", "past_due", "canceled"]

# Status transition graph (BILL_INV_02). Keyed by current status → allowed next.
# ``canceled`` is terminal — no outgoing edges.
_ALLOWED_TRANSITIONS: Final[Mapping[SubscriptionStatus, frozenset[SubscriptionStatus]]] = {
    "trialing": frozenset({"active", "past_due", "canceled"}),
    "active": frozenset({"past_due", "canceled"}),
    "past_due": frozenset({"active", "canceled"}),
    "canceled": frozenset(),
}


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Customer:
    """Opaque customer record returned by the provider.

    Attributes:
        id: Provider-issued opaque token.
        email: Contact email. NEVER echoed in error messages.
        metadata: Provider-passthrough key/value pairs (both strings).
    """

    id: str
    email: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Subscription:
    """Opaque subscription record returned by the provider.

    Attributes:
        id: Provider-issued opaque subscription token.
        customer_id: Owning customer's ``Customer.id``.
        price_id: Current price the subscription is billed against.
        status: One of ``SubscriptionStatus``.
        trial_period_days: Trial length at creation time, or ``None``.
    """

    id: str
    customer_id: str
    price_id: str
    status: SubscriptionStatus
    trial_period_days: int | None = None


@dataclass(frozen=True)
class Event:
    """Verified webhook event returned by ``construct_webhook_event``.

    Attributes:
        id: Provider event id.
        type: Provider event type (e.g. ``"invoice.payment_succeeded"``).
        data: Opaque payload object the provider attaches to this event.
    """

    id: str
    type: str
    data: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class BillingError(Exception):
    """Common base for billing-family errors."""


class InvalidWebhookSignatureError(BillingError):
    """BILL_INV_01: raised when a webhook signature fails HMAC verification."""


InvalidWebhookSignature = InvalidWebhookSignatureError  # backward-compat alias


class UnknownCustomerError(BillingError):
    """BILL_INV_04: referenced ``customer_id`` does not exist."""


UnknownCustomer = UnknownCustomerError  # backward-compat alias


class UnknownSubscriptionError(BillingError):
    """BILL_INV_04: referenced ``subscription_id`` does not exist."""


UnknownSubscription = UnknownSubscriptionError  # backward-compat alias


class LifecycleInvariantError(BillingError):
    """BILL_INV_02: attempted transition violates the subscription lifecycle graph."""


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------
@runtime_checkable
class Billing(Protocol):
    """The minimum billing gateway every provider adapter MUST honour."""

    def create_customer(
        self,
        email: str,
        metadata: Mapping[str, str] | None = None,
    ) -> Customer: ...

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_period_days: int | None = None,
    ) -> Subscription: ...

    def cancel_subscription(self, subscription_id: str) -> Subscription: ...

    def change_plan(self, subscription_id: str, new_price_id: str) -> Subscription: ...

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> Event: ...


# ---------------------------------------------------------------------------
# Reference implementation — InMemoryBilling
# ---------------------------------------------------------------------------
class InMemoryBilling:
    """Deterministic in-memory Billing backend for tests and local dev.

    This is a reference implementation — real apps wire the Stripe /
    Paddle / … adapter. The motor's state (customer + subscription
    dicts) is isolated per-instance; the webhook signature scheme is
    compatible with Stripe's convention:

        sig_header = "t=<ts>,v1=<hex(HMAC_SHA256(secret, f'{ts}.{payload}'))>"

    allowing callers to drive test fixtures through the same verification
    path the production adapter uses. Tolerance window defaults to 5
    minutes (BILL_INV_01 — freshness).

    Args:
        webhook_secret: Shared secret used to sign/verify webhook events.
            Required; passing an empty string fails at construction so
            the invariant check cannot be bypassed accidentally.
        tolerance_s: Max clock skew tolerated between signed timestamp
            and verification time (BILL_INV_01). Must be positive.
    """

    _DEFAULT_TOLERANCE_S: Final[int] = 300

    __slots__ = (
        "_cust_seq",
        "_customers",
        "_evt_seq",
        "_secret",
        "_sub_seq",
        "_subs",
        "_tolerance_s",
    )

    def __init__(
        self,
        webhook_secret: str,
        *,
        tolerance_s: int = _DEFAULT_TOLERANCE_S,
    ) -> None:
        if not isinstance(webhook_secret, str) or webhook_secret == "":
            raise ValueError(
                "InMemoryBilling requires a non-empty webhook_secret "
                "(BILL_INV_01: signature verification cannot be bypassed).",
            )
        if not isinstance(tolerance_s, int) or tolerance_s <= 0:
            raise ValueError(
                "InMemoryBilling tolerance_s MUST be a positive int "
                "(BILL_INV_01: an unbounded window lets replays through).",
            )
        self._secret: str = webhook_secret
        self._tolerance_s: int = tolerance_s
        self._customers: dict[str, Customer] = {}
        self._subs: dict[str, Subscription] = {}
        self._cust_seq: int = 0
        self._sub_seq: int = 0
        self._evt_seq: int = 0

    # ---- customers --------------------------------------------------------
    def create_customer(
        self,
        email: str,
        metadata: Mapping[str, str] | None = None,
    ) -> Customer:
        if not isinstance(email, str) or "@" not in email:
            # BILL_INV_05: message does NOT echo the email.
            raise BillingError("email MUST be a string containing '@'.")
        self._cust_seq += 1
        cid = f"cus_mem_{self._cust_seq:08d}"
        cust = Customer(id=cid, email=email, metadata=dict(metadata or {}))
        self._customers[cid] = cust
        return cust

    def get_customer(self, customer_id: str) -> Customer:
        if customer_id not in self._customers:
            raise UnknownCustomer(f"no customer with id={customer_id!r}.")
        return self._customers[customer_id]

    # ---- subscriptions ----------------------------------------------------
    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_period_days: int | None = None,
    ) -> Subscription:
        if customer_id not in self._customers:
            raise UnknownCustomer(f"no customer with id={customer_id!r}.")
        if not isinstance(price_id, str) or price_id == "":
            raise BillingError("price_id MUST be a non-empty string.")
        if trial_period_days is not None and (
            not isinstance(trial_period_days, int) or trial_period_days < 0
        ):
            raise BillingError("trial_period_days MUST be int >= 0 or None.")
        self._sub_seq += 1
        sid = f"sub_mem_{self._sub_seq:08d}"
        status: SubscriptionStatus = "trialing" if trial_period_days else "active"
        sub = Subscription(
            id=sid,
            customer_id=customer_id,
            price_id=price_id,
            status=status,
            trial_period_days=trial_period_days,
        )
        self._subs[sid] = sub
        return sub

    def cancel_subscription(self, subscription_id: str) -> Subscription:
        sub = self._require_sub(subscription_id)
        self._assert_transition(sub.status, "canceled")
        new_sub = replace(sub, status="canceled")
        self._subs[subscription_id] = new_sub
        return new_sub

    def change_plan(self, subscription_id: str, new_price_id: str) -> Subscription:
        sub = self._require_sub(subscription_id)
        if sub.status == "canceled":
            # BILL_INV_02: cannot mutate a terminal subscription.
            raise LifecycleInvariantError(
                f"sub {subscription_id!r} is canceled (terminal); change_plan refused.",
            )
        if not isinstance(new_price_id, str) or new_price_id == "":
            raise BillingError("new_price_id MUST be a non-empty string.")
        # BILL_INV_03: same id is preserved across the plan change.
        new_sub = replace(sub, price_id=new_price_id)
        self._subs[subscription_id] = new_sub
        return new_sub

    def set_status(
        self,
        subscription_id: str,
        new_status: SubscriptionStatus,
    ) -> Subscription:
        """Apply a status change (typically from a verified webhook event).

        Raises ``LifecycleInvariantError`` if the transition is not in
        ``_ALLOWED_TRANSITIONS`` (BILL_INV_02).
        """
        sub = self._require_sub(subscription_id)
        self._assert_transition(sub.status, new_status)
        new_sub = replace(sub, status=new_status)
        self._subs[subscription_id] = new_sub
        return new_sub

    def get_subscription(self, subscription_id: str) -> Subscription:
        return self._require_sub(subscription_id)

    def _require_sub(self, subscription_id: str) -> Subscription:
        if subscription_id not in self._subs:
            raise UnknownSubscription(
                f"no subscription with id={subscription_id!r}.",
            )
        return self._subs[subscription_id]

    def _assert_transition(
        self,
        current: SubscriptionStatus,
        new: SubscriptionStatus,
    ) -> None:
        if new not in _ALLOWED_TRANSITIONS[current]:
            raise LifecycleInvariantError(
                f"subscription status transition refused: {current!r} → {new!r} "
                f"(BILL_INV_02 — canceled is terminal; "
                f"allowed next={sorted(_ALLOWED_TRANSITIONS[current])}).",
            )

    # ---- webhook verification --------------------------------------------
    def sign_payload(self, payload: bytes, *, timestamp: int | None = None) -> str:
        """Return a Stripe-compatible signature header for ``payload``.

        Useful in tests to produce a valid ``sig_header`` that the motor
        (and any provider adapter built on the same scheme) will accept.
        """
        if not isinstance(payload, (bytes, bytearray)):
            raise BillingError("payload MUST be bytes.")
        ts = int(timestamp if timestamp is not None else time.time())
        signed_payload = f"{ts}.".encode() + bytes(payload)
        v1 = hmac.new(
            self._secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        return f"t={ts},v1={v1}"

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> Event:
        """Verify + parse a webhook event.

        Raises:
            InvalidWebhookSignature: payload / header / secret mismatch OR
                timestamp outside tolerance window (BILL_INV_01).
            BillingError: payload is not JSON parseable into an object.
        """
        if not isinstance(payload, (bytes, bytearray)):
            raise InvalidWebhookSignature("payload MUST be bytes.")
        if not isinstance(sig_header, str) or sig_header == "":
            raise InvalidWebhookSignature("missing signature header.")
        ts, v1 = _parse_sig_header(sig_header)
        signed_payload = f"{ts}.".encode() + bytes(payload)
        expected = hmac.new(
            self._secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, v1):
            # BILL_INV_05: no payload echo in the error.
            raise InvalidWebhookSignature("signature mismatch.")
        now = int(time.time())
        if abs(now - ts) > self._tolerance_s:
            raise InvalidWebhookSignature(
                f"timestamp outside tolerance window ({self._tolerance_s}s).",
            )
        try:
            body = json.loads(bytes(payload).decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BillingError(f"payload is not valid JSON: {exc!s}.") from exc
        if not isinstance(body, dict):
            raise BillingError("payload JSON MUST be an object.")
        self._evt_seq += 1
        return Event(
            id=str(body.get("id", f"evt_mem_{self._evt_seq:08d}")),
            type=str(body.get("type", "unknown")),
            data=dict(body.get("data") or {}),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_sig_header(header: str) -> tuple[int, str]:
    """Parse a ``t=<ts>,v1=<hex>`` header.

    Returns ``(ts, v1)``. Raises ``InvalidWebhookSignature`` on any
    malformed input — we never infer missing fields.
    """
    fields: dict[str, str] = {}
    for raw_part in header.split(","):
        part = raw_part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        fields[k.strip()] = v.strip()
    if "t" not in fields or "v1" not in fields:
        raise InvalidWebhookSignature(
            "signature header MUST include both 't' and 'v1' fields.",
        )
    try:
        ts = int(fields["t"])
    except ValueError as exc:
        raise InvalidWebhookSignature("signature timestamp MUST be integer.") from exc
    return ts, fields["v1"]
