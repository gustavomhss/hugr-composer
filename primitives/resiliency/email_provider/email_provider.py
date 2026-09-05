"""Protocol/Interface: EmailProvider."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmailProvider(Protocol):
    """Abstract provider interface.

    Implementations must be stateless and safe to instantiate on
    every ``get_provider()`` call — construction should NOT perform
    network I/O or import third-party SDKs.  Those side-effects
    belong inside ``send()`` so the app can boot cleanly without
    the SDK installed.
    """

    async def send(self, message: EmailMessage) -> EmailResult:
        """Send *message* and return the provider's message id."""
        ...
