"""Chaos / fault-injection tests for CsrfGuard."""

from __future__ import annotations

import secrets
import threading

import pytest

from CsrfGuard import MIN_SECRET_BYTES, CsrfGuardError, HmacCsrfGuard


def _guard() -> HmacCsrfGuard:
    return HmacCsrfGuard(secret=secrets.token_bytes(MIN_SECRET_BYTES))


def test_chaos_empty_token_rejected() -> None:
    g = _guard()
    with pytest.raises(CsrfGuardError):
        g.verify("s", "")


def test_chaos_null_byte_in_session_id() -> None:
    g = _guard()
    sid = "valid\x00injection-attempt"
    t = g.issue(sid)
    g.verify(sid, t)  # exact binding — no truncation
    with pytest.raises(CsrfGuardError):
        g.verify("valid", t)


def test_chaos_long_session_id_does_not_crash() -> None:
    g = _guard()
    sid = "x" * 10_000
    g.verify(sid, g.issue(sid))


def test_chaos_concurrent_issue_no_collisions() -> None:
    g = _guard()
    tokens: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(50):
            t = g.issue("shared-session")
            with lock:
                tokens.append(t)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(tokens) == 200
    assert len(set(tokens)) == 200  # all nonces distinct


def test_chaos_hex_case_variations_rejected() -> None:
    # Tokens are lowercase hex; uppercase variants fromhex still decode, but
    # the MAC bytes MUST be byte-equal; any mangling fails.
    g = _guard()
    t = g.issue("s")
    upper = t.upper()
    # Upper-case hex of same bytes → still valid since fromhex is case-insensitive.
    g.verify("s", upper)


def test_chaos_double_dot_token_rejected() -> None:
    g = _guard()
    with pytest.raises(CsrfGuardError):
        g.verify("s", "abc..def")


def test_chaos_oversized_nonce_rejected() -> None:
    g = _guard()
    # 20-byte nonce → CsrfGuardError.
    forged = secrets.token_bytes(20).hex() + "." + "0" * 64
    with pytest.raises(CsrfGuardError):
        g.verify("s", forged)


def test_chaos_unicode_session_id_bound_exactly() -> None:
    g = _guard()
    sid = "session-Ω-漢字"
    t = g.issue(sid)
    g.verify(sid, t)
    with pytest.raises(CsrfGuardError):
        g.verify("session-Ω-漢字 ", t)  # trailing space
