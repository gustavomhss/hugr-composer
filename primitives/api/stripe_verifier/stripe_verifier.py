"""Inbound verifier: StripeVerifier."""

from __future__ import annotations

from typing import Protocol

class InboundVerifier(Protocol):
    name: str
    def verify(self, body: bytes, headers: dict[str, str]) -> "VerifiedEvent": ...


class StripeVerifier(InboundVerifier):
    """Verify Stripe webhook payloads."""

    name = "stripe"

    def verify(self, body: bytes, headers: dict[str, str]) -> dict:
        """Verify a signed webhook request."""
        raise NotImplementedError
