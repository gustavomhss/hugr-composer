"""Protocol for SignatureVerifier — generated from SignatureVerifier.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class SignatureVerifier(Protocol):
    """SignatureVerifier primitive — detached signature producer/verifier."""

    def sign(self, message: bytes, key_id: str) -> bytes: ...
    def verify(self, message: bytes, signature: bytes, key_id: str) -> None: ...
