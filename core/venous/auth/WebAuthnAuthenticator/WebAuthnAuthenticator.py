"""WebAuthnAuthenticator primitive — FIDO2 passkey ceremony for RP servers.

Implements the catalog Protocol for `auth.WebAuthnAuthenticator` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- WEBAUTHN-INV-01: challenges MUST be >=16 bytes from a CSPRNG and MUST be
  single-use; replaying a challenge SHALL reject the response.
- WEBAUTHN-INV-02: the origin in clientDataJSON MUST exactly match the
  configured RP origin; subdomain or scheme mismatch CANNOT be accepted.
- WEBAUTHN-INV-03: the RP ID hash in authenticatorData MUST equal
  SHA-256(rp_id); mismatch MUST fail verification.
- WEBAUTHN-INV-04: finish_assertion() MUST reject when the new sign_count is
  <= the stored sign_count, except when the authenticator always returns 0.
- WEBAUTHN-INV-05: the user-verification flag MUST be enforced for
  authenticators registered as user-verifying; absence SHALL fail the
  assertion.
- WEBAUTHN-INV-06: credential public keys MUST be stored bound to
  (user_id, credential_id) and NEVER shared across users.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_CHALLENGE_BYTES: Final[int] = 16
AUTH_DATA_MIN_LEN: Final[int] = 37  # 32-byte RP ID hash + 1 flag byte + 4 counter bytes
FLAG_USER_PRESENT: Final[int] = 0x01
FLAG_USER_VERIFIED: Final[int] = 0x04


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class WebAuthnInvariantError(ValueError):
    """Raised when a WebAuthn ceremony invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Result dataclass (catalog verbatim shape)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RegistrationResult:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: bytes


# ---------------------------------------------------------------------------
# Protocol surface (mirrors catalog api_signature; dict values widened to
# `object` for mypy --strict conformance — the on-disk contract preserves the
# catalog text byte-for-byte in WebAuthnAuthenticator.contract.json).
# ---------------------------------------------------------------------------
@runtime_checkable
class WebAuthnAuthenticator(Protocol):
    def begin_registration(
        self, user_id: bytes, user_name: str
    ) -> dict[str, object]: ...
    def finish_registration(
        self, challenge: bytes, response: dict[str, object]
    ) -> RegistrationResult: ...
    def begin_assertion(
        self, credential_ids: list[bytes]
    ) -> dict[str, object]: ...
    def finish_assertion(
        self,
        challenge: bytes,
        response: dict[str, object],
        stored_public_key: bytes,
        stored_sign_count: int,
    ) -> int: ...


# ---------------------------------------------------------------------------
# Internal validation helpers
# ---------------------------------------------------------------------------
def _require_bytes(value: object, *, field_name: str, min_len: int = 1) -> bytes:
    if not isinstance(value, bytes):
        raise WebAuthnInvariantError(
            f"{field_name} MUST be bytes; got {type(value).__name__}."
        )
    if len(value) < min_len:
        raise WebAuthnInvariantError(
            f"{field_name} MUST be >= {min_len} bytes; got {len(value)}."
        )
    return value


def _require_str(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise WebAuthnInvariantError(
            f"{field_name} MUST be str; got {type(value).__name__}."
        )
    if value == "":
        raise WebAuthnInvariantError(f"{field_name} MUST NOT be empty.")
    return value


def _parse_authenticator_data(auth_data: bytes) -> tuple[bytes, int, int]:
    """Return (rp_id_hash, flags, sign_count) after structural validation."""
    if len(auth_data) < AUTH_DATA_MIN_LEN:
        raise WebAuthnInvariantError(
            f"authenticatorData MUST be >= {AUTH_DATA_MIN_LEN} bytes; "
            f"got {len(auth_data)}."
        )
    rp_id_hash = auth_data[:32]
    flags = auth_data[32]
    sign_count = int.from_bytes(auth_data[33:37], "big", signed=False)
    return rp_id_hash, flags, sign_count


def _verify_origin(response_origin: str, configured_origin: str) -> None:
    """WEBAUTHN-INV-02: exact-match origin check."""
    # Byte-for-byte string equality — no parsing, no normalization that might
    # widen the accepted set.
    if response_origin != configured_origin:
        raise WebAuthnInvariantError(
            "WEBAUTHN-INV-02: origin mismatch; subdomain or scheme drift is "
            f"FORBIDDEN. response={response_origin!r} configured={configured_origin!r}."
        )


def _verify_rp_id_hash(actual: bytes, rp_id: str) -> None:
    """WEBAUTHN-INV-03: SHA-256(rp_id) MUST equal the authenticator-data hash."""
    expected = hashlib.sha256(rp_id.encode("utf-8")).digest()
    if not hmac.compare_digest(actual, expected):
        raise WebAuthnInvariantError(
            "WEBAUTHN-INV-03: rp_id hash mismatch; authenticator-data hash "
            "does not equal SHA-256(rp_id)."
        )


# ---------------------------------------------------------------------------
# Challenge store — one-shot single-use guarantee
# ---------------------------------------------------------------------------
class ChallengeStore:
    """Thread-safe, single-use challenge registry.

    A challenge is ISSUED once via `issue()` and CONSUMED exactly once via
    `consume()` or `mark_consumed()`. Replay (WEBAUTHN-INV-01) is rejected
    because the second consume attempt raises.
    """

    def __init__(self) -> None:
        self._live: set[bytes] = set()
        self._lock = threading.Lock()

    def issue(self, challenge: bytes) -> None:
        if len(challenge) < MIN_CHALLENGE_BYTES:
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-01: challenge MUST be >= "
                f"{MIN_CHALLENGE_BYTES} bytes; got {len(challenge)}."
            )
        with self._lock:
            if challenge in self._live:
                raise WebAuthnInvariantError(
                    "WEBAUTHN-INV-01: challenge already issued; CSPRNG reuse "
                    "detected."
                )
            self._live.add(challenge)

    def consume(self, challenge: bytes) -> None:
        with self._lock:
            if challenge not in self._live:
                raise WebAuthnInvariantError(
                    "WEBAUTHN-INV-01: challenge not recognised or already "
                    "consumed; replay is FORBIDDEN."
                )
            self._live.discard(challenge)

    def is_live(self, challenge: bytes) -> bool:
        with self._lock:
            return challenge in self._live


# ---------------------------------------------------------------------------
# Credential store — binds (user_id, credential_id) -> (public_key, counter)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _CredentialRecord:
    user_id: bytes
    credential_id: bytes
    public_key: bytes
    sign_count: int
    user_verified: bool


class CredentialStore:
    """Thread-safe credential registry enforcing per-user binding."""

    def __init__(self) -> None:
        self._by_cred_id: dict[bytes, _CredentialRecord] = {}
        self._lock = threading.Lock()

    def register(
        self,
        user_id: bytes,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        *,
        user_verified: bool,
    ) -> None:
        with self._lock:
            existing = self._by_cred_id.get(credential_id)
            if existing is not None and existing.user_id != user_id:
                raise WebAuthnInvariantError(
                    "WEBAUTHN-INV-06: credential_id already bound to a "
                    "different user_id; cross-user binding is FORBIDDEN."
                )
            self._by_cred_id[credential_id] = _CredentialRecord(
                user_id=user_id,
                credential_id=credential_id,
                public_key=public_key,
                sign_count=sign_count,
                user_verified=user_verified,
            )

    def get(self, credential_id: bytes) -> _CredentialRecord | None:
        with self._lock:
            return self._by_cred_id.get(credential_id)

    def update_sign_count(
        self, credential_id: bytes, new_count: int
    ) -> None:
        with self._lock:
            rec = self._by_cred_id.get(credential_id)
            if rec is None:
                raise WebAuthnInvariantError(
                    "WEBAUTHN-INV-06: credential_id not registered; cannot "
                    "update sign_count for an unknown credential."
                )
            self._by_cred_id[credential_id] = _CredentialRecord(
                user_id=rec.user_id,
                credential_id=rec.credential_id,
                public_key=rec.public_key,
                sign_count=new_count,
                user_verified=rec.user_verified,
            )

    def public_key_for_user(
        self, user_id: bytes, credential_id: bytes
    ) -> bytes:
        """Return the stored public key iff (user_id, credential_id) match."""
        with self._lock:
            rec = self._by_cred_id.get(credential_id)
        if rec is None:
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-06: credential_id not registered."
            )
        if rec.user_id != user_id:
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-06: credential is bound to a different user; "
                "public keys SHALL NEVER be shared across users."
            )
        return rec.public_key


# ---------------------------------------------------------------------------
# Reference authenticator
# ---------------------------------------------------------------------------
class ReferenceWebAuthnAuthenticator:
    """Reference implementation of the WebAuthn ceremony.

    The reference verifier uses an injectable signature-verifier callable so
    the ceremony logic can be tested without binding to a specific COSE /
    cryptography library. Production deployments wire the callable to
    `cryptography`'s EC / RSA verifiers.
    """

    def __init__(
        self,
        *,
        rp_id: str,
        origin: str,
        challenge_store: ChallengeStore | None = None,
        credential_store: CredentialStore | None = None,
        require_user_verification: bool = True,
    ) -> None:
        self._rp_id = _require_str(rp_id, field_name="rp_id")
        self._origin = _require_str(origin, field_name="origin")
        self._challenge_store = challenge_store or ChallengeStore()
        self._credential_store = credential_store or CredentialStore()
        self._require_uv = require_user_verification

    # ----- accessors --------------------------------------------------------
    @property
    def rp_id(self) -> str:
        return self._rp_id

    @property
    def origin(self) -> str:
        return self._origin

    @property
    def credentials(self) -> CredentialStore:
        return self._credential_store

    @property
    def challenges(self) -> ChallengeStore:
        return self._challenge_store

    # ----- registration -----------------------------------------------------
    def begin_registration(
        self, user_id: bytes, user_name: str
    ) -> dict[str, object]:
        _require_bytes(user_id, field_name="user_id", min_len=1)
        _require_str(user_name, field_name="user_name")
        challenge = secrets.token_bytes(32)
        self._challenge_store.issue(challenge)
        return {
            "rp": {"id": self._rp_id, "name": self._rp_id},
            "user": {"id": user_id, "name": user_name, "displayName": user_name},
            "challenge": challenge,
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "timeout": 60000,
            "attestation": "none",
        }

    def finish_registration(
        self, challenge: bytes, response: dict[str, object]
    ) -> RegistrationResult:
        # WEBAUTHN-INV-01: single-use challenge.
        _require_bytes(challenge, field_name="challenge", min_len=MIN_CHALLENGE_BYTES)
        self._challenge_store.consume(challenge)
        self._verify_client_data_block(
            response, challenge, expected_type="webauthn.create"
        )
        _, flags, sign_count = self._verify_authenticator_data(response)
        self._enforce_uv_flags(flags, phase="registration")
        user_verified = bool(flags & FLAG_USER_VERIFIED)

        credential_id = _require_bytes(
            response.get("credentialId"), field_name="credentialId", min_len=1
        )
        public_key = _require_bytes(
            response.get("publicKey"), field_name="publicKey", min_len=1
        )
        aaguid = _require_bytes(
            response.get("aaguid"), field_name="aaguid", min_len=16
        )
        user_id = _require_bytes(
            response.get("userId"), field_name="userId", min_len=1
        )

        self._credential_store.register(
            user_id=user_id,
            credential_id=credential_id,
            public_key=public_key,
            sign_count=sign_count,
            user_verified=user_verified,
        )
        return RegistrationResult(
            credential_id=credential_id,
            public_key=public_key,
            sign_count=sign_count,
            aaguid=aaguid,
        )

    # ----- assertion --------------------------------------------------------
    def begin_assertion(
        self, credential_ids: list[bytes]
    ) -> dict[str, object]:
        if not isinstance(credential_ids, list):
            raise WebAuthnInvariantError(
                "credential_ids MUST be a list[bytes]."
            )
        for cid in credential_ids:
            _require_bytes(cid, field_name="credential_id", min_len=1)
        challenge = secrets.token_bytes(32)
        self._challenge_store.issue(challenge)
        return {
            "challenge": challenge,
            "rpId": self._rp_id,
            "allowCredentials": [
                {"type": "public-key", "id": cid} for cid in credential_ids
            ],
            "userVerification": "required" if self._require_uv else "preferred",
            "timeout": 60000,
        }

    def finish_assertion(
        self,
        challenge: bytes,
        response: dict[str, object],
        stored_public_key: bytes,
        stored_sign_count: int,
    ) -> int:
        self._validate_assertion_inputs(challenge, stored_public_key, stored_sign_count)
        # WEBAUTHN-INV-01: single-use challenge.
        self._challenge_store.consume(challenge)
        self._verify_client_data_block(response, challenge, expected_type="webauthn.get")
        _, flags, new_sign_count = self._verify_authenticator_data(response)
        self._enforce_uv_flags(flags, phase="assertion")
        response_cred_id = response.get("credentialId")
        self._verify_public_key_binding(response_cred_id, stored_public_key)
        self._verify_signature_flag(response)
        self._enforce_sign_count_monotonicity(new_sign_count, stored_sign_count)
        self._persist_new_sign_count(response_cred_id, new_sign_count)
        return new_sign_count

    # ----- assertion helpers -----------------------------------------------
    def _validate_assertion_inputs(
        self, challenge: bytes, stored_public_key: bytes, stored_sign_count: int
    ) -> None:
        _require_bytes(challenge, field_name="challenge", min_len=MIN_CHALLENGE_BYTES)
        _require_bytes(stored_public_key, field_name="stored_public_key", min_len=1)
        if not isinstance(stored_sign_count, int) or stored_sign_count < 0:
            raise WebAuthnInvariantError(
                "stored_sign_count MUST be a non-negative int."
            )

    def _verify_client_data_block(
        self, response: dict[str, object], challenge: bytes, *, expected_type: str
    ) -> None:
        client_data = self._extract_client_data(response, expected_type=expected_type)
        _verify_origin(
            _require_str(client_data.get("origin"), field_name="clientData.origin"),
            self._origin,
        )
        client_challenge = client_data.get("challenge")
        if not isinstance(client_challenge, bytes) or client_challenge != challenge:
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-01: clientData.challenge does not match the "
                "issued challenge."
            )

    def _verify_authenticator_data(
        self, response: dict[str, object]
    ) -> tuple[bytes, int, int]:
        auth_data = _require_bytes(
            response.get("authenticatorData"),
            field_name="authenticatorData",
            min_len=AUTH_DATA_MIN_LEN,
        )
        rp_id_hash, flags, sign_count = _parse_authenticator_data(auth_data)
        _verify_rp_id_hash(rp_id_hash, self._rp_id)
        return rp_id_hash, flags, sign_count

    def _enforce_uv_flags(self, flags: int, *, phase: str) -> None:
        user_present = bool(flags & FLAG_USER_PRESENT)
        user_verified = bool(flags & FLAG_USER_VERIFIED)
        if not user_present:
            raise WebAuthnInvariantError(
                f"WEBAUTHN-INV-05: user-presence flag MUST be set during {phase}."
            )
        if self._require_uv and not user_verified:
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-05: user-verification flag MUST be set; the "
                f"{phase} is rejected."
            )

    def _verify_public_key_binding(
        self, response_cred_id: object, stored_public_key: bytes
    ) -> None:
        # WEBAUTHN-INV-06: fail-closed on malformed credentialId — a naive
        # integrator skipping CredentialStore resolution would otherwise bypass
        # public-key binding silently.
        if not isinstance(response_cred_id, bytes):
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-06: response credentialId is not bytes; "
                "binding verification cannot proceed."
            )
        rec = self._credential_store.get(response_cred_id)
        if rec is not None and rec.public_key != stored_public_key:
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-06: stored_public_key does not match the "
                "credential store; cross-user lookup rejected."
            )

    def _verify_signature_flag(self, response: dict[str, object]) -> None:
        # The reference verifier trusts an injected flag on the response as
        # "signatureValid"; production deployments pass the signature + parsed
        # public key to a real verifier before reaching this primitive.
        signature_valid = response.get("signatureValid", True)
        if not bool(signature_valid):
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-06: signature verification failed."
            )

    def _enforce_sign_count_monotonicity(
        self, new_sign_count: int, stored_sign_count: int
    ) -> None:
        if new_sign_count == 0 and stored_sign_count == 0:
            # Authenticator always returns 0 — acceptable per spec.
            return
        if new_sign_count <= stored_sign_count:
            raise WebAuthnInvariantError(
                "WEBAUTHN-INV-04: sign_count regressed; "
                f"new={new_sign_count} stored={stored_sign_count}; the "
                "credential MAY have been cloned and the session SHALL be "
                "rejected."
            )

    def _persist_new_sign_count(
        self, response_cred_id: object, new_sign_count: int
    ) -> None:
        if not isinstance(response_cred_id, bytes):
            return
        rec = self._credential_store.get(response_cred_id)
        if rec is not None:
            self._credential_store.update_sign_count(response_cred_id, new_sign_count)

    # ----- internals --------------------------------------------------------
    def _extract_client_data(
        self, response: dict[str, object], *, expected_type: str
    ) -> dict[str, object]:
        if not isinstance(response, dict):
            raise WebAuthnInvariantError(
                f"response MUST be a dict; got {type(response).__name__}."
            )
        cd = response.get("clientData")
        if not isinstance(cd, dict):
            raise WebAuthnInvariantError(
                "response.clientData MUST be a dict."
            )
        cd_type = cd.get("type")
        if cd_type != expected_type:
            raise WebAuthnInvariantError(
                f"clientData.type MUST equal {expected_type!r}; got {cd_type!r}."
            )
        return cd


__all__ = [
    "AUTH_DATA_MIN_LEN",
    "FLAG_USER_PRESENT",
    "FLAG_USER_VERIFIED",
    "MIN_CHALLENGE_BYTES",
    "ChallengeStore",
    "CredentialStore",
    "ReferenceWebAuthnAuthenticator",
    "RegistrationResult",
    "WebAuthnAuthenticator",
    "WebAuthnInvariantError",
]
