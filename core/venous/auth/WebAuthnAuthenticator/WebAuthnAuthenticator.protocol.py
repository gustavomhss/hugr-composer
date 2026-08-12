"""Protocol for WebAuthnAuthenticator — generated from WebAuthnAuthenticator.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class WebAuthnAuthenticator(Protocol):
    """WebAuthnAuthenticator primitive — FIDO2 passkey ceremony for RP servers."""

    def begin_registration(self, user_id: bytes, user_name: str) -> dict[str, object]: ...
    def finish_registration(self, challenge: bytes, response: dict[str, object]) -> RegistrationResult: ...
    def begin_assertion(self, credential_ids: list[bytes]) -> dict[str, object]: ...
    def finish_assertion(self, challenge: bytes, response: dict[str, object], stored_public_key: bytes, stored_sign_count: int) -> int: ...
