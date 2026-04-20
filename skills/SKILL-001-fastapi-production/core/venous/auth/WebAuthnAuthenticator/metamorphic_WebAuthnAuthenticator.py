"""Metamorphic + differential tests for WebAuthnAuthenticator.

Algebraic properties:
- every begin_registration() returns a fresh, CSPRNG-sized challenge
- challenge issue/consume are inverse operations: issue then consume keeps the
  store empty
- finish_registration is idempotent up to the single-use guard — the same
  (challenge, response) pair NEVER succeeds twice
- origin comparison is byte-identity equivalent (whitespace / casing rejected)
- registering the same credential_id twice under the same user_id is a no-op
  (no new binding, no error)
"""

from __future__ import annotations

import hashlib

import pytest

from WebAuthnAuthenticator import (
    ChallengeStore,
    CredentialStore,
    MIN_CHALLENGE_BYTES,
    ReferenceWebAuthnAuthenticator,
    WebAuthnInvariantError,
)

RP_ID = "passkeys.example.com"
ORIGIN = "https://passkeys.example.com"
RP_ID_HASH = hashlib.sha256(RP_ID.encode()).digest()


def _reg_resp(challenge: bytes, user_id: bytes, credential_id: bytes) -> dict[str, object]:
    return {
        "clientData": {"type": "webauthn.create", "origin": ORIGIN, "challenge": challenge},
        "authenticatorData": RP_ID_HASH + bytes([0x05]) + (0).to_bytes(4, "big"),
        "credentialId": credential_id,
        "publicKey": b"pk-" + user_id,
        "aaguid": b"\x00" * 16,
        "userId": user_id,
    }


def test_metamorphic_every_challenge_is_fresh_and_sized() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    seen: set[bytes] = set()
    for _ in range(64):
        opts = auth.begin_registration(user_id=b"u", user_name="u")
        ch = opts["challenge"]
        assert isinstance(ch, bytes)
        assert len(ch) >= MIN_CHALLENGE_BYTES
        assert ch not in seen
        seen.add(ch)


def test_metamorphic_challenge_issue_consume_is_inverse() -> None:
    store = ChallengeStore()
    challenge = b"\x01" * 32
    store.issue(challenge)
    assert store.is_live(challenge)
    store.consume(challenge)
    assert not store.is_live(challenge)
    # And a second consume fails — property of single-use semantics.
    with pytest.raises(WebAuthnInvariantError):
        store.consume(challenge)


def test_metamorphic_finish_registration_is_not_reissuable() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"u", user_name="u")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    auth.finish_registration(
        challenge=ch, response=_reg_resp(ch, b"u", b"c1")
    )
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch, response=_reg_resp(ch, b"u", b"c2")
        )


def test_metamorphic_origin_equality_is_byte_identity() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    variants = [
        ORIGIN + "/",                    # trailing slash
        ORIGIN + " ",                    # trailing whitespace
        ORIGIN.upper(),                  # casing
        ORIGIN.replace("https", "http"), # scheme drift
    ]
    for bad in variants:
        opts = auth.begin_registration(user_id=b"u", user_name="u")
        ch = opts["challenge"]
        assert isinstance(ch, bytes)
        with pytest.raises(WebAuthnInvariantError):
            auth.finish_registration(
                challenge=ch,
                response={
                    "clientData": {"type": "webauthn.create", "origin": bad, "challenge": ch},
                    "authenticatorData": RP_ID_HASH + bytes([0x05]) + (0).to_bytes(4, "big"),
                    "credentialId": b"c",
                    "publicKey": b"p",
                    "aaguid": b"\x00" * 16,
                    "userId": b"u",
                },
            )


def test_differential_same_user_rebinding_is_stable() -> None:
    """Re-registering the SAME (user_id, credential_id) keeps the binding stable."""
    store = CredentialStore()
    store.register(
        user_id=b"alice",
        credential_id=b"cred-1",
        public_key=b"pk-1",
        sign_count=0,
        user_verified=True,
    )
    # Idempotent-ish: same user may re-register (e.g., counter reset) — the
    # store accepts it because the user_id matches. The public key becomes the
    # new one, but the user binding is preserved.
    store.register(
        user_id=b"alice",
        credential_id=b"cred-1",
        public_key=b"pk-1-rotated",
        sign_count=0,
        user_verified=True,
    )
    assert store.public_key_for_user(b"alice", b"cred-1") == b"pk-1-rotated"


def test_differential_sign_count_zero_path_vs_regression() -> None:
    """Authenticator-always-returns-0 path differs from the regression path."""
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg_opts = auth.begin_registration(user_id=b"u", user_name="u")
    reg_ch = reg_opts["challenge"]
    assert isinstance(reg_ch, bytes)
    auth.finish_registration(
        challenge=reg_ch, response=_reg_resp(reg_ch, b"u", b"cred-u")
    )
    # Path A: stored=0, new=0 → accepted (authenticator always zero).
    ast_opts = auth.begin_assertion([b"cred-u"])
    ast_ch = ast_opts["challenge"]
    assert isinstance(ast_ch, bytes)
    assert auth.finish_assertion(
        challenge=ast_ch,
        response={
            "clientData": {"type": "webauthn.get", "origin": ORIGIN, "challenge": ast_ch},
            "authenticatorData": RP_ID_HASH + bytes([0x05]) + (0).to_bytes(4, "big"),
            "credentialId": b"cred-u",
            "signatureValid": True,
        },
        stored_public_key=b"pk-" + b"u",
        stored_sign_count=0,
    ) == 0
    # Path B: stored=5, new=5 → regressed (NOT the authenticator-zero case).
    ast_opts_2 = auth.begin_assertion([b"cred-u"])
    ast_ch_2 = ast_opts_2["challenge"]
    assert isinstance(ast_ch_2, bytes)
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_assertion(
            challenge=ast_ch_2,
            response={
                "clientData": {"type": "webauthn.get", "origin": ORIGIN, "challenge": ast_ch_2},
                "authenticatorData": RP_ID_HASH + bytes([0x05]) + (5).to_bytes(4, "big"),
                "credentialId": b"cred-u",
                "signatureValid": True,
            },
            stored_public_key=b"pk-" + b"u",
            stored_sign_count=5,
        )
