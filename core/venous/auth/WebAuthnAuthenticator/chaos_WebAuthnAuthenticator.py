"""Chaos / game-day tests for WebAuthnAuthenticator."""

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


def _reg_resp(challenge: bytes, user_id: bytes, credential_id: bytes) -> dict[str, object]:
    return {
        "clientData": {"type": "webauthn.create", "origin": ORIGIN, "challenge": challenge},
        "authenticatorData": RP_ID_HASH + bytes([0x05]) + (0).to_bytes(4, "big"),
        "credentialId": credential_id,
        "publicKey": b"pk-" + user_id,
        "aaguid": b"\x00" * 16,
        "userId": user_id,
    }


def test_chaos_parallel_challenge_replay_rejected() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_registration(user_id=b"alice", user_name="alice")
    ch = opts["challenge"]
    assert isinstance(ch, bytes)

    results: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            auth.finish_registration(
                challenge=ch,
                response=_reg_resp(ch, b"alice", b"cred-" + bytes([i])),
            )
            with lock:
                results.append("ok")
        except WebAuthnInvariantError:
            with lock:
                results.append("rejected")

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count("ok") == 1
    assert results.count("rejected") == 15


def test_chaos_malformed_authenticator_data_rejected() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    bad_shapes = [
        b"",                       # empty
        b"\x00" * 5,               # too short for rp_id_hash
        b"\x00" * 32,              # truncated (missing flags + counter)
        b"\x00" * 36,              # truncated counter
    ]
    for data in bad_shapes:
        opts = auth.begin_registration(user_id=b"u", user_name="u")
        ch = opts["challenge"]
        assert isinstance(ch, bytes)
        with pytest.raises(WebAuthnInvariantError):
            auth.finish_registration(
                challenge=ch,
                response={
                    "clientData": {"type": "webauthn.create", "origin": ORIGIN, "challenge": ch},
                    "authenticatorData": data,
                    "credentialId": b"c",
                    "publicKey": b"p",
                    "aaguid": b"\x00" * 16,
                    "userId": b"u",
                },
            )


def test_chaos_credential_store_concurrent_register_single_owner() -> None:
    store = CredentialStore()
    errors: list[BaseException] = []
    ok: list[bytes] = []
    lock = threading.Lock()

    def worker(user: bytes) -> None:
        try:
            store.register(
                user_id=user,
                credential_id=b"shared",
                public_key=b"pk-" + user,
                sign_count=0,
                user_verified=True,
            )
            with lock:
                ok.append(user)
        except WebAuthnInvariantError as exc:
            with lock:
                errors.append(exc)

    users = [bytes([i]) * 4 for i in range(1, 33)]
    ts = [threading.Thread(target=worker, args=(u,)) for u in users]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(ok) == 1
    assert len(errors) == len(users) - 1


def test_chaos_challenge_store_concurrent_issue_distinct() -> None:
    store = ChallengeStore()
    errors: list[BaseException] = []
    issued: list[bytes] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        ch = i.to_bytes(32, "big")
        try:
            store.issue(ch)
            with lock:
                issued.append(ch)
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert len(issued) == 100


def test_chaos_signature_invalid_blocks_login() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg_opts = auth.begin_registration(user_id=b"u", user_name="u")
    reg_ch = reg_opts["challenge"]
    assert isinstance(reg_ch, bytes)
    auth.finish_registration(
        challenge=reg_ch, response=_reg_resp(reg_ch, b"u", b"cred-u")
    )

    ast_opts = auth.begin_assertion([b"cred-u"])
    ast_ch = ast_opts["challenge"]
    assert isinstance(ast_ch, bytes)
    with pytest.raises(WebAuthnInvariantError):
        auth.finish_assertion(
            challenge=ast_ch,
            response={
                "clientData": {"type": "webauthn.get", "origin": ORIGIN, "challenge": ast_ch},
                "authenticatorData": RP_ID_HASH + bytes([0x05]) + (2).to_bytes(4, "big"),
                "credentialId": b"cred-u",
                "signatureValid": False,
            },
            stored_public_key=b"pk-" + b"u",
            stored_sign_count=0,
        )


def test_chaos_empty_credential_ids_list_is_safe() -> None:
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    opts = auth.begin_assertion([])
    assert isinstance(opts["challenge"], bytes)
    assert opts["allowCredentials"] == []
