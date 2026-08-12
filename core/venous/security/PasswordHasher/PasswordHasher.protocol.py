"""Protocol for PasswordHasher — generated from PasswordHasher.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class PasswordHasher(Protocol):
    """PasswordHasher primitive — Argon2id password verifier with rotation metadata."""

    def hash(self, plaintext: str) -> str: ...
    def verify(self, plaintext: str, stored: str) -> bool: ...
    def needs_rehash(self, stored: str) -> bool: ...
