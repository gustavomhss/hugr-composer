"""Behavioral end-to-end scenarios for CsrfGuard."""

from __future__ import annotations

import secrets

import pytest

from CsrfGuard import (
    MIN_SECRET_BYTES,
    CsrfGuardError,
    HmacCsrfGuard,
    is_safe_method,
)


def _guard() -> HmacCsrfGuard:
    return HmacCsrfGuard(secret=secrets.token_bytes(MIN_SECRET_BYTES))


def test_scenario_form_submission_flow() -> None:
    g = _guard()
    sid = "user-session-42"
    token = g.issue(sid)  # server renders this on GET /form
    # Client submits POST /form with the token in a hidden field / header.
    g.verify(sid, token)  # no raise → controller proceeds


def test_scenario_attacker_replays_other_users_token() -> None:
    g = _guard()
    victim_token = g.issue("victim-session")
    with pytest.raises(CsrfGuardError):
        g.verify("attacker-session", victim_token)


def test_scenario_token_rotated_on_session_rotation() -> None:
    g = _guard()
    old = g.issue("sid-before-login")
    # After login, SessionStore rotates the session id; CSRF guard issues a new token.
    with pytest.raises(CsrfGuardError):
        g.verify("sid-after-login", old)
    new = g.issue("sid-after-login")
    g.verify("sid-after-login", new)


def test_scenario_safe_methods_skip_guard() -> None:
    # Controllers MUST only invoke verify() on unsafe methods; the helper lets
    # them short-circuit GET/HEAD/OPTIONS without constructing a token.
    assert is_safe_method("GET") is True
    assert is_safe_method("POST") is False


def test_scenario_logout_invalidates_token_via_session_change() -> None:
    g = _guard()
    pre_logout = g.issue("sid-logged-in")
    g.verify("sid-logged-in", pre_logout)
    # Logout destroys the session; any token issued for the old id no longer works.
    with pytest.raises(CsrfGuardError):
        g.verify("sid-logged-out", pre_logout)


def test_scenario_tampered_token_raises_without_leaking_mac() -> None:
    g = _guard()
    t = g.issue("s")
    nonce_hex, mac_hex = t.split(".", 1)
    forged = nonce_hex + "." + ("0" * len(mac_hex))
    with pytest.raises(CsrfGuardError) as err:
        g.verify("s", forged)
    # The error message MUST NOT echo the attacker-submitted MAC hex or the
    # server-expected MAC hex.
    assert mac_hex not in str(err.value)


def test_scenario_guard_rejects_short_secret() -> None:
    with pytest.raises(CsrfGuardError):
        HmacCsrfGuard(secret=b"short")
