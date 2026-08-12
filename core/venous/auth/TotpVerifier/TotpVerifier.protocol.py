"""Protocol for TotpVerifier — generated from TotpVerifier.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class TotpVerifier(Protocol):
    """TotpVerifier primitive — RFC 6238 TOTP with replay-step protection."""

    def provision_uri(self, account: str, issuer: str, secret: bytes) -> str: ...
    def verify(self, secret: bytes, code: str, last_used_step: int | None) -> int: ...
