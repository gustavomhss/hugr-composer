"""Metamorphic + differential tests for CsrfGuard.

Algebraic properties:
- issue_verify_roundtrip: verify(sid, issue(sid)) MUST never raise.
- session_swap_fails: verify(sid', issue(sid)) MUST raise for sid' != sid.
- bit_flip_invalidates: any bit flip in the MAC invalidates the token.
- secret_rotation_invalidates: a fresh guard (new secret) rejects old tokens.
- nonce_uniqueness: each issue() returns a distinct token even for the same sid.
"""

from __future__ import annotations

import secrets

import pytest

from CsrfGuard import MIN_SECRET_BYTES, CsrfGuardError, HmacCsrfGuard


def _guard() -> HmacCsrfGuard:
    return HmacCsrfGuard(secret=secrets.token_bytes(MIN_SECRET_BYTES))


def test_metamorphic_issue_verify_roundtrip() -> None:
    g = _guard()
    for sid in ("a", "another", "with-dash", "漢字", "123"):
        g.verify(sid, g.issue(sid))


def test_metamorphic_session_swap_fails() -> None:
    g = _guard()
    t = g.issue("alpha")
    for other in ("beta", "alph", "ALPHA", " alpha", "alpha "):
        with pytest.raises(CsrfGuardError):
            g.verify(other, t)


def test_metamorphic_bit_flip_invalidates() -> None:
    g = _guard()
    t = g.issue("s")
    nonce_hex, mac_hex = t.split(".", 1)
    # Flip least-significant bit of each byte in the MAC; all variants MUST fail.
    for i in range(len(mac_hex) // 2):
        mac_bytes = bytearray(bytes.fromhex(mac_hex))
        mac_bytes[i] ^= 0x01
        forged = nonce_hex + "." + mac_bytes.hex()
        with pytest.raises(CsrfGuardError):
            g.verify("s", forged)


def test_differential_secret_rotation_invalidates() -> None:
    g1 = _guard()
    g2 = _guard()  # fresh secret
    t = g1.issue("s")
    with pytest.raises(CsrfGuardError):
        g2.verify("s", t)


def test_metamorphic_nonce_uniqueness() -> None:
    g = _guard()
    tokens = {g.issue("s") for _ in range(32)}
    assert len(tokens) == 32


def test_metamorphic_token_length_stable() -> None:
    g = _guard()
    lengths = {len(g.issue("sid")) for _ in range(16)}
    assert len(lengths) == 1  # fixed-length format


def test_differential_two_guards_same_secret_verify_each_other() -> None:
    secret = secrets.token_bytes(MIN_SECRET_BYTES)
    g1 = HmacCsrfGuard(secret=secret)
    g2 = HmacCsrfGuard(secret=secret)
    t = g1.issue("s")
    g2.verify("s", t)  # parity — same secret, same result
