"""Inbound verifier: InternalVerifier."""

from __future__ import annotations

from typing import Protocol

class InboundVerifier(Protocol):
    name: str
    def verify(self, body: bytes, headers: dict[str, str]) -> "VerifiedEvent": ...


class InternalVerifier(InboundVerifier):
    """Verify Internal webhook payloads."""

    name = "internal"

    def verify(self, body: bytes, headers: dict[str, str]) -> dict:
        """Verify a signed webhook request."""
        raise NotImplementedError
