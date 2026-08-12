"""Protocol for CryptoEnvelope — generated from CryptoEnvelope.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class CryptoEnvelope(Protocol):
    """CryptoEnvelope primitive — AEAD envelope with key-id tagging for rotation."""

    def seal(self, plaintext: bytes, aad: bytes) -> Envelope: ...
    def open(self, envelope: Envelope, aad: bytes) -> bytes: ...
