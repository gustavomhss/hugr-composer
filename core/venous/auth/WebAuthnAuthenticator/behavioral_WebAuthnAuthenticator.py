"""Behavioral end-to-end scenarios for WebAuthnAuthenticator — proves invariants at runtime."""

from __future__ import annotations

import hashlib

import pytest

from WebAuthnAuthenticator import (
    ReferenceWebAuthnAuthenticator,
    WebAuthnInvariantError,
)

RP_ID = "passkeys.example.com"
ORIGIN = "https://passkeys.example.com"
RP_ID_HASH = hashlib.sha256(RP_ID.encode()).digest()


def _auth_data(flags: int = 0x05, sign_count: int = 1) -> bytes:
    return RP_ID_HASH + bytes([flags]) + sign_count.to_bytes(4, "big")


def _reg_resp(
    *,
    challenge: bytes,
    user_id: bytes,
    credential_id: bytes,
    public_key: bytes,
    origin: str = ORIGIN,
    flags: int = 0x05,
    sign_count: int = 0,
) -> dict[str, object]:
    return {
        "clientData": {"type": "webauthn.create", "origin": origin, "challenge": challenge},
        "authenticatorData": _auth_data(flags, sign_count),
        "credentialId": credential_id,
        "publicKey": public_key,
        "aaguid": b"\xaa" * 16,
        "userId": user_id,
    }


def _assert_resp(
    *,
    challenge: bytes,
    credential_id: bytes,
    flags: int = 0x05,
    sign_count: int = 2,
    origin: str = ORIGIN,
) -> dict[str, object]:
    return {
        "clientData": {"type": "webauthn.get", "origin": origin, "challenge": challenge},
        "authenticatorData": _auth_data(flags, sign_count),
        "credentialId": credential_id,
        "signatureValid": True,
    }


# ---------------------------------------------------------------------------
# Scenario 1 — happy-path passkey registration + login
# ---------------------------------------------------------------------------
def test_scenario_register_then_assert_happy_path() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)

    reg_opts = auth.begin_registration(user_id=b"alice", user_name="alice")
    reg_ch = reg_opts["challenge"]
    assert isinstance(reg_ch, bytes)
    result = auth.finish_registration(
        challenge=reg_ch,
        response=_reg_resp(
            challenge=reg_ch,
            user_id=b"alice",
            credential_id=b"cred-alice",
            public_key=b"pk-alice",
        ),
    )
    assert result.credential_id == b"cred-alice"
    assert result.public_key == b"pk-alice"

    # Login ceremony.
    ast_opts = auth.begin_assertion([b"cred-alice"])
    ast_ch = ast_opts["challenge"]
    assert isinstance(ast_ch, bytes)
    new_count = auth.finish_assertion(
        challenge=ast_ch,
        response=_assert_resp(challenge=ast_ch, credential_id=b"cred-alice", sign_count=7),
        stored_public_key=b"pk-alice",
        stored_sign_count=0,
    )
    assert new_count == 7


# ---------------------------------------------------------------------------
# Scenario 2 — phishing attempt on lookalike domain
# ---------------------------------------------------------------------------
def test_scenario_phishing_origin_blocked() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"bob", user_name="bob")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch,
            response=_reg_resp(
                challenge=ch,
                user_id=b"bob",
                credential_id=b"cred-bob",
                public_key=b"pk-bob",
                origin="https://passkeys.example.com.phishing.io",
            ),
        )


# ---------------------------------------------------------------------------
# Scenario 3 — cloned authenticator detected by counter regression
# ---------------------------------------------------------------------------
def test_scenario_cloned_authenticator_counter_regression() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg_opts = auth.begin_registration(user_id=b"carol", user_name="carol")
    reg_ch = reg_opts["challenge"]
    assert isinstance(reg_ch, bytes)
    auth.finish_registration(
        challenge=reg_ch,
        response=_reg_resp(
            challenge=reg_ch,
            user_id=b"carol",
            credential_id=b"cred-carol",
            public_key=b"pk-carol",
        ),
    )
    # Legitimate login bumps counter to 10.
    ast_opts = auth.begin_assertion([b"cred-carol"])
    ast_ch = ast_opts["challenge"]
    assert isinstance(ast_ch, bytes)
    auth.finish_assertion(
        challenge=ast_ch,
        response=_assert_resp(challenge=ast_ch, credential_id=b"cred-carol", sign_count=10),
        stored_public_key=b"pk-carol",
        stored_sign_count=0,
    )
    # Clone tries to assert with counter=3 (regression).
    ast_opts_2 = auth.begin_assertion([b"cred-carol"])
    ast_ch_2 = ast_opts_2["challenge"]
    assert isinstance(ast_ch_2, bytes)
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_assertion(
            challenge=ast_ch_2,
            response=_assert_resp(challenge=ast_ch_2, credential_id=b"cred-carol", sign_count=3),
            stored_public_key=b"pk-carol",
            stored_sign_count=10,
        )


# ---------------------------------------------------------------------------
# Scenario 4 — replay of captured ceremony
# ---------------------------------------------------------------------------
def test_scenario_challenge_replay_blocked() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg_opts = auth.begin_registration(user_id=b"dan", user_name="dan")
    ch = reg_opts["challenge"]
    assert isinstance(ch, bytes)
    auth.finish_registration(
        challenge=ch,
        response=_reg_resp(
            challenge=ch,
            user_id=b"dan",
            credential_id=b"cred-dan",
            public_key=b"pk-dan",
        ),
    )
    # Capturing and replaying the SAME ceremony MUST fail.
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch,
            response=_reg_resp(
                challenge=ch,
                user_id=b"dan",
                credential_id=b"cred-dan-2",
                public_key=b"pk-dan-2",
            ),
        )


# ---------------------------------------------------------------------------
# Scenario 5 — cross-user credential hijack blocked
# ---------------------------------------------------------------------------
def test_scenario_cross_user_credential_hijack_blocked() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg_a = auth.begin_registration(user_id=b"alice", user_name="alice")
    ch_a = reg_a["challenge"]
    assert isinstance(ch_a, bytes)
    auth.finish_registration(
        challenge=ch_a,
        response=_reg_resp(
            challenge=ch_a,
            user_id=b"alice",
            credential_id=b"shared-cred",
            public_key=b"pk-alice",
        ),
    )
    # Mallory tries to register the same credential_id for herself.
    reg_m = auth.begin_registration(user_id=b"mallory", user_name="mallory")
    ch_m = reg_m["challenge"]
    assert isinstance(ch_m, bytes)
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch_m,
            response=_reg_resp(
                challenge=ch_m,
                user_id=b"mallory",
                credential_id=b"shared-cred",
                public_key=b"pk-mallory",
            ),
        )


# ---------------------------------------------------------------------------
# Scenario 6 — forged RP ID in authenticator-data
# ---------------------------------------------------------------------------
def test_scenario_rp_id_hash_forgery_blocked() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"eve", user_name="eve")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)
    wrong_hash = hashlib.sha256(b"attacker.example.com").digest()
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_registration(
            challenge=ch,
            response={
                "clientData": {"type": "webauthn.create", "origin": ORIGIN, "challenge": ch},
                "authenticatorData": wrong_hash + bytes([0x05]) + (0).to_bytes(4, "big"),
                "credentialId": b"cred-eve",
                "publicKey": b"pk-eve",
                "aaguid": b"\x00" * 16,
                "userId": b"eve",
            },
        )
