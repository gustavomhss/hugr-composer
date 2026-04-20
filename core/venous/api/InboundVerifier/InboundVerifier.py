from __future__ import annotations
from abc import ABC
from abc import abstractmethod


class InboundVerifier(ABC):
    """Abstract base class for provider-specific webhook verifiers.

    Subclasses must set the ``name`` class attribute and implement
    ``verify``.  The ``verify`` method must raise ``HTTPException``
    on any signature, format, or replay error — it MUST NOT return
    ``None`` or swallow exceptions silently.
    """
    name: str

    @abstractmethod
    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        """Verify the inbound request and return a ``VerifiedEvent``.

        Args:
            body: Raw request body bytes.
            headers: Lowercased request headers dict.

        Returns:
            A ``VerifiedEvent`` on successful verification.

        Raises:
            HTTPException(400): On signature mismatch or invalid format.
            HTTPException(401): On missing required authentication header.
        """
