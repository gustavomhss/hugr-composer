"""InboundVerifier — framework-free abstract base for webhook verifiers.

Provider-specific verifiers (Stripe, Slack, Twilio, custom HMAC) inherit
from this base, set the ``name`` class attribute, and implement ``verify``
to return a trusted dict on success OR raise a subclass-specific
exception on failure.

Invariants cited here:

- IV_INV_01 — named contract: every concrete subclass MUST set the
  ``name`` class attribute (string) — ``InboundVerifier.__init_subclass__``
  raises at subclass-definition time otherwise. This lets a registry
  route webhooks to the correct verifier by name.
- IV_INV_02 — verify-or-raise: ``verify`` either returns a trusted
  dict (the VerifiedEvent) OR raises. Returning ``None`` / swallowing
  errors is forbidden by the contract (and enforced by callers; the
  base class cannot mechanically enforce, but the ABC docstring is
  the authority).
- IV_INV_03 — framework-free: the base does NOT import from FastAPI /
  Starlette / Flask. Adapters that wrap verifier errors into HTTP
  responses live in ``core/venous/_adapters/<framework>/`` and are
  the place where HTTP concerns attach.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# Trusted post-verification envelope. Framework-free: a plain dict
# that subclasses populate with whatever their protocol carries
# (event_id, payload, timestamp, etc.). Wrapping into a richer
# `VerifiedEvent` dataclass lives in the staged primitive of the
# same name — not imported here because the staged primitive is
# NOT part of the registered surface.
VerifiedEvent = dict[str, Any]


class InboundVerifier(ABC):
    """Abstract base for provider-specific webhook verifiers."""

    name: str = ""  # Sentinel; concrete subclasses override. Empty = unset.

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only enforce IV_INV_01 on classes that have implemented `verify`
        # — an abstract intermediate that still carries `verify` in
        # __abstractmethods__ may legitimately defer setting `name` to
        # a deeper subclass.
        if getattr(cls, "__abstractmethods__", frozenset()):
            return
        value = getattr(cls, "name", "")
        if not isinstance(value, str) or not value:
            raise TypeError(
                f"{cls.__name__} must set a non-empty `name: str` class "
                "attribute (IV_INV_01).",
            )

    @abstractmethod
    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        """Verify the inbound request and return the trusted envelope.

        Args:
            body: Raw request body bytes.
            headers: Lowercased request headers dict.

        Returns:
            A trusted ``VerifiedEvent`` dict on successful verification.

        Raises:
            Exception: Subclass-specific. The base contract says
                "raise on any signature, format, or replay error";
                the subclass picks the exception type. Silent
                ``None`` returns are forbidden (IV_INV_02).
        """


__all__ = ["InboundVerifier", "VerifiedEvent"]
