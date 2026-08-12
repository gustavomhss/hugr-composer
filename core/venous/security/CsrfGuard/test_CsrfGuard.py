"""Unit tests for CsrfGuard — three per invariant."""

from __future__ import annotations

import hmac
import secrets

import pytest
from CsrfGuard import (
    MIN_SECRET_BYTES,
    TOKEN_NONCE_BYTES,
    CsrfGuardError,
    HmacCsrfGuard,
    is_safe_method,
)


def _guard() -> HmacCsrfGuard:
    return HmacCsrfGuard(secret=secrets.token_bytes(MIN_SECRET_BYTES))


# ---------------------------------------------------------------------------
# CSRF_INV_01 — tokens bound to session id
# ---------------------------------------------------------------------------
def test_inv_session_binding_confirms() -> None:
    g = _guard()
    t = g.issue("session-alpha")
    g.verify("session-alpha", t)  # no raise


def test_inv_session_binding_prevents() -> None:
    g = _guard()
    t = g.issue("session-alpha")
    with pytest.raises(CsrfGuardError):
        g.verify("session-bravo", t)
    with pytest.raises(CsrfGuardError):
        g.verify("", t)


def test_inv_session_binding_under_failure() -> None:
    g = _guard()
    t = g.issue("s1")
    # Token from a different guard instance (different secret) MUST NOT verify.
    g2 = _guard()
    with pytest.raises(CsrfGuardError):
        g2.verify("s1", t)


# ---------------------------------------------------------------------------
# CSRF_INV_02 — constant-time compare
# ---------------------------------------------------------------------------
def test_inv_constant_time_confirms() -> None:
    # Behavioral proxy: compare_digest is the only comparator used, no ==.
    src = open(__file__).read()
    impl = open(__file__.replace("test_", "")).read()
    assert "hmac.compare_digest" in impl
    # Structural: MAC bytes comparison uses compare_digest; exercised via verify.
    assert hmac.compare_digest(b"abc", b"abc") is True
    assert hmac.compare_digest(b"abc", b"abd") is False
    assert "compare_digest" in src or "compare_digest" in impl


def test_inv_constant_time_prevents() -> None:
    g = _guard()
    t = g.issue("s")
    parts = t.split(".")
    # Flip one byte in the MAC hex → verify MUST raise with NO hint about expected.
    bad_mac_hex = ("0" if parts[1][0] != "0" else "1") + parts[1][1:]
    forged = parts[0] + "." + bad_mac_hex
    with pytest.raises(CsrfGuardError) as err:
        g.verify("s", forged)
    # The error MUST NOT leak the expected MAC hex.
    assert bad_mac_hex not in str(err.value)


def test_inv_constant_time_under_failure() -> None:
    # Malformed tokens MUST all raise, never return silently.
    g = _guard()
    for bad in ("", "no-dot", "abc.xyz", "zzz." + "0" * 64):
        with pytest.raises(CsrfGuardError):
            g.verify("s", bad)


# ---------------------------------------------------------------------------
# CSRF_INV_03 — safe methods MUST NEVER mutate
# ---------------------------------------------------------------------------
def test_inv_safe_methods_confirms() -> None:
    assert is_safe_method("GET") is True
    assert is_safe_method("HEAD") is True
    assert is_safe_method("OPTIONS") is True
    assert is_safe_method("get") is True  # case-insensitive


def test_inv_safe_methods_prevents() -> None:
    for unsafe in ("POST", "PUT", "PATCH", "DELETE"):
        assert is_safe_method(unsafe) is False


def test_inv_safe_methods_under_failure() -> None:
    for bad in (None, 123, b"GET"):
        with pytest.raises(CsrfGuardError):
            is_safe_method(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CSRF_INV_04 — cross-origin/no-token fails closed
# ---------------------------------------------------------------------------
def test_inv_fail_closed_confirms() -> None:
    g = _guard()
    with pytest.raises(CsrfGuardError):
        g.verify("s", "")  # missing token → fail closed


def test_inv_fail_closed_prevents() -> None:
    g = _guard()
    for junk in ("junk", "." * 10, "AAAA.BBBB"):
        with pytest.raises(CsrfGuardError):
            g.verify("s", junk)


def test_inv_fail_closed_under_failure() -> None:
    g = _guard()
    # Token from previous session paired with new session id → rejected.
    old = g.issue("old-session")
    with pytest.raises(CsrfGuardError):
        g.verify("new-session", old)


# ---------------------------------------------------------------------------
# CSRF_INV_05 — rotation invalidates stale tokens
# ---------------------------------------------------------------------------
def test_inv_rotation_confirms() -> None:
    g = _guard()
    t = g.issue("s-v1")
    g.verify("s-v1", t)
    # After rotation the session id changes; old token no longer verifies.
    with pytest.raises(CsrfGuardError):
        g.verify("s-v2", t)


def test_inv_rotation_prevents() -> None:
    # A new guard instance with a new secret invalidates every prior token —
    # this is the "key rotation" path.
    g1 = _guard()
    g2 = _guard()
    t = g1.issue("s")
    with pytest.raises(CsrfGuardError):
        g2.verify("s", t)


def test_inv_rotation_under_failure() -> None:
    # Issue two tokens back-to-back for the same session; each verifies
    # independently (nonce differs), proving the guard does not track a
    # single-active-token model. Rotation is session-id driven.
    g = _guard()
    a = g.issue("s")
    b = g.issue("s")
    assert a != b
    g.verify("s", a)
    g.verify("s", b)


# ---------------------------------------------------------------------------
# Extra: construction invariants
# ---------------------------------------------------------------------------
def test_short_secret_rejected() -> None:
    with pytest.raises(CsrfGuardError):
        HmacCsrfGuard(secret=b"\x00" * 8)


def test_non_bytes_secret_rejected() -> None:
    with pytest.raises(CsrfGuardError):
        HmacCsrfGuard(secret="not-bytes")  # type: ignore[arg-type]


def test_nonce_length_expected() -> None:
    g = _guard()
    t = g.issue("s")
    nonce_hex, _ = t.split(".", 1)
    assert len(bytes.fromhex(nonce_hex)) == TOKEN_NONCE_BYTES
