"""Unit tests for WebAuthnAuthenticator — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import hashlib
import threading

import pytest

from WebAuthnAuthenticator import (
    ChallengeStore,
    CredentialStore,
    ReferenceWebAuthnAuthenticator,
    WebAuthnInvariantError,
)

RP_ID = "passkeys.example.com"
ORIGIN = "https://passkeys.example.com"
RP_ID_HASH = hashlib.sha256(RP_ID.encode()).digest()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
def _auth_data(
    *,
    rp_id_hash: bytes = RP_ID_HASH,
    flags: int = 0x05,  # UP | UV
    sign_count: int = 1,
) -> bytes:
    return rp_id_hash + bytes([flags]) + sign_count.to_bytes(4, "big")


def _registration_response(
    *,
    challenge: bytes,
    user_id: bytes = b"user-a",
    credential_id: bytes = b"cred-a",
    public_key: bytes = b"pubkey-a",
    aaguid: bytes = b"\x00" * 16,
    origin: str = ORIGIN,
    rp_id_hash: bytes = RP_ID_HASH,
    flags: int = 0x05,
    sign_count: int = 0,
) -> dict[str, object]:
    return {
        "clientData": {
            "type": "webauthn.create",
            "origin": origin,
            "challenge": challenge,
        },
        "authenticatorData": _auth_data(
            rp_id_hash=rp_id_hash, flags=flags, sign_count=sign_count
        ),
        "credentialId": credential_id,
        "publicKey": public_key,
        "aaguid": aaguid,
        "userId": user_id,
    }


def _assertion_response(
    *,
    challenge: bytes,
    credential_id: bytes = b"cred-a",
    origin: str = ORIGIN,
    rp_id_hash: bytes = RP_ID_HASH,
    flags: int = 0x05,
    sign_count: int = 2,
    signature_valid: bool = True,
) -> dict[str, object]:
    return {
        "clientData": {
            "type": "webauthn.get",
            "origin": origin,
            "challenge": challenge,
        },
        "authenticatorData": _auth_data(
            rp_id_hash=rp_id_hash, flags=flags, sign_count=sign_count
        ),
        "credentialId": credential_id,
        "signatureValid": signature_valid,
    }


def _register_alice() -> tuple[ReferenceWebAuthnAuthenticator, bytes, bytes]:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"user-a", user_name="alice")
    challenge = opts["challenge"]
    assert isinstance(challenge, bytes)
    auth.finish_registration(
        challenge=challenge,
        response=_registration_response(challenge=challenge),
    )
    return auth, challenge, b"cred-a"


# ===========================================================================
# WEBAUTHN_INV_01 — challenges are CSPRNG-sized and single-use
# ===========================================================================
def test_inv_challenge_single_use_confirms() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"u", user_name="alice")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    assert len(ch) >= 16
    # Consuming it exactly once succeeds.
    auth.finish_registration(
        challenge=ch,
        response=_registration_response(challenge=ch),
    )


def test_inv_challenge_single_use_prevents() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"u", user_name="alice")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    auth.finish_registration(
        challenge=ch, response=_registration_response(challenge=ch)
    )
    # Replay — second use MUST be rejected.
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch,
            response=_registration_response(challenge=ch, user_id=b"u2", credential_id=b"c2"),
        )


def test_inv_challenge_single_use_under_failure() -> None:
    store = ChallengeStore()
    # Short challenge is rejected.
    with pytest.raises(WebAuthnInvariantError):
        store.issue(b"short")
    # Unknown challenge consume is rejected.
    with pytest.raises(WebAuthnInvariantError):
        store.consume(b"\x00" * 32)


# ===========================================================================
# WEBAUTHN_INV_02 — origin exact match
# ===========================================================================
def test_inv_origin_exact_match_confirms() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"u", user_name="a")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    auth.finish_registration(
        challenge=ch,
        response=_registration_response(challenge=ch, origin=ORIGIN),
    )


def test_inv_origin_exact_match_prevents() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"u", user_name="a")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch,
            response=_registration_response(
                challenge=ch, origin="https://evil.passkeys.example.com"
            ),
        )


def test_inv_origin_exact_match_under_failure() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    # Even under repeated attacker attempts with scheme / subdomain drift,
    # origin check MUST hold and the challenge MUST be consumed.
    attempts = [
        "http://passkeys.example.com",          # scheme drift
        "https://PASSKEYS.example.com",         # casing drift
        "https://passkeys.example.com:8443",    # port drift
        "https://passkeys.example.com.evil.io", # suffix injection
    ]
    for bad in attempts:
        opts = auth.begin_registration(user_id=b"u", user_name="a")
        ch = opts["challenge"]
        assert isinstance(ch, bytes)
        with pytest.raises(WebAuthnInvariantError):
            auth.finish_registration(
                challenge=ch,
                response=_registration_response(challenge=ch, origin=bad),
            )


# ===========================================================================
# WEBAUTHN_INV_03 — RP ID hash match
# ===========================================================================
def test_inv_rp_id_hash_confirms() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"u", user_name="a")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    auth.finish_registration(
        challenge=ch,
        response=_registration_response(challenge=ch, rp_id_hash=RP_ID_HASH),
    )


def test_inv_rp_id_hash_prevents() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"u", user_name="a")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    wrong = hashlib.sha256(b"evil.example.com").digest()
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch,
            response=_registration_response(challenge=ch, rp_id_hash=wrong),
        )


def test_inv_rp_id_hash_under_failure() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    # Truncated or wrong-size hash is also rejected (parse-level guard).
    opts = auth.begin_registration(user_id=b"u", user_name="a")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    with pytest.raises(WebAuthnInvariantError):
        # Supply authenticatorData that's too short — parse fails before hash check.
        auth.finish_registration(
            challenge=ch,
            response={
                "clientData": {"type": "webauthn.create", "origin": ORIGIN, "challenge": ch},
                "authenticatorData": b"\x00" * 10,
                "credentialId": b"c",
                "publicKey": b"p",
                "aaguid": b"\x00" * 16,
                "userId": b"u",
            },
        )


# ===========================================================================
# WEBAUTHN_INV_04 — sign_count monotonicity
# ===========================================================================
def test_inv_sign_count_monotonic_confirms() -> None:
    auth, _reg_ch, cred_id = _register_alice()
    opts = auth.begin_assertion([cred_id])
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    new_count = auth.finish_assertion(
        challenge=ch,
        response=_assertion_response(challenge=ch, sign_count=5),
        stored_public_key=b"pubkey-a",
        stored_sign_count=1,
    )
    assert new_count == 5


def test_inv_sign_count_monotonic_prevents() -> None:
    auth, _reg_ch, cred_id = _register_alice()
    opts = auth.begin_assertion([cred_id])
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_assertion(
            challenge=ch,
            response=_assertion_response(challenge=ch, sign_count=1),
            stored_public_key=b"pubkey-a",
            stored_sign_count=5,
        )


def test_inv_sign_count_monotonic_under_failure() -> None:
    # Authenticator that always returns 0 is acceptable.
    auth, _reg_ch, cred_id = _register_alice()
    opts = auth.begin_assertion([cred_id])
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    new_count = auth.finish_assertion(
        challenge=ch,
        response=_assertion_response(challenge=ch, sign_count=0),
        stored_public_key=b"pubkey-a",
        stored_sign_count=0,
    )
    assert new_count == 0


# ===========================================================================
# WEBAUTHN_INV_05 — UV flag enforced
# ===========================================================================
def test_inv_uv_flag_enforced_confirms() -> None:
    auth = ReferenceWebAuthnAuthenticator(
        rp_id=RP_ID, origin=ORIGIN, require_user_verification=True
    )
    opts = auth.begin_registration(user_id=b"u", user_name="a")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    # flags = UP | UV (0x05) passes.
    auth.finish_registration(
        challenge=ch,
        response=_registration_response(challenge=ch, flags=0x05),
    )


def test_inv_uv_flag_enforced_prevents() -> None:
    auth = ReferenceWebAuthnAuthenticator(
        rp_id=RP_ID, origin=ORIGIN, require_user_verification=True
    )
    opts = auth.begin_registration(user_id=b"u", user_name="a")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    # UP only (0x01), UV bit missing — rejected.
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch,
            response=_registration_response(challenge=ch, flags=0x01),
        )


def test_inv_uv_flag_enforced_under_failure() -> None:
    auth, _reg_ch, cred_id = _register_alice()
    opts = auth.begin_assertion([cred_id])
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    # Assertion with UP but no UV — rejected.
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_assertion(
            challenge=ch,
            response=_assertion_response(challenge=ch, flags=0x01, sign_count=2),
            stored_public_key=b"pubkey-a",
            stored_sign_count=1,
        )


# ===========================================================================
# WEBAUTHN_INV_06 — credentials bound to (user_id, credential_id)
# ===========================================================================
def test_inv_credential_binding_confirms() -> None:
    store = CredentialStore()
    store.register(
        user_id=b"alice",
        credential_id=b"cred-1",
        public_key=b"pk-1",
        sign_count=0,
        user_verified=True,
    )
    assert store.public_key_for_user(b"alice", b"cred-1") == b"pk-1"


def test_inv_credential_binding_prevents() -> None:
    store = CredentialStore()
    store.register(
        user_id=b"alice",
        credential_id=b"cred-1",
        public_key=b"pk-1",
        sign_count=0,
        user_verified=True,
    )
    # Attempting to re-bind the same credential_id to a different user is FORBIDDEN.
    with pytest.raises(WebAuthnInvariantError):
        store.register(
            user_id=b"mallory",
            credential_id=b"cred-1",
            public_key=b"pk-2",
            sign_count=0,
            user_verified=True,
        )
    # Cross-user lookup is FORBIDDEN.
    with pytest.raises(WebAuthnInvariantError):
        store.public_key_for_user(b"mallory", b"cred-1")


def test_inv_credential_binding_under_failure() -> None:
    store = CredentialStore()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(user: bytes) -> None:
        try:
            store.register(
                user_id=user,
                credential_id=b"shared-cred-id",
                public_key=b"pk-" + user,
                sign_count=0,
                user_verified=True,
            )
        except WebAuthnInvariantError as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(bytes([i]) * 6,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Exactly one user can own the credential_id; the rest are rejected.
    assert len(errors) == 7
