"""Behavioral end-to-end scenarios for SessionStore — prove invariants at runtime."""

from __future__ import annotations

import pytest

from SessionStore import (
    CookieConfig,
    InMemorySessionStore,
    SessionInvariantError,
    validate_cookie_host,
)


def test_scenario_login_then_load_roundtrip() -> None:
    # Login: create a session, the server-side record resolves back to the caller.
    store = InMemorySessionStore()
    issued = store.create("alice")
    loaded = store.load(issued.id)
    assert loaded is not None
    assert loaded.subject == "alice"
    assert loaded.id == issued.id


def test_scenario_logout_revokes_everywhere() -> None:
    # Logout = revoke: any replay of the cookie after revoke MUST fail even
    # inside the original lifetime window.
    clock = {"t": 5000}
    store = InMemorySessionStore(clock=lambda: clock["t"])
    s = store.create("alice")
    store.revoke(s.id)
    clock["t"] += 10  # still fresh
    assert store.load(s.id) is None


def test_scenario_privilege_escalation_rotates_id() -> None:
    # Classic fixation guard: after escalation the old id MUST NOT resolve,
    # and the new id MUST carry the same subject.
    store = InMemorySessionStore()
    before = store.create("alice")
    after = store.rotate(before.id)
    assert after.id != before.id
    assert after.subject == before.subject
    assert store.load(before.id) is None
    assert store.load(after.id) is not None


def test_scenario_password_change_terminates_all_sessions() -> None:
    # On password change the app calls revoke_all_for_subject(subject) — every
    # live session for that subject (across devices) MUST stop resolving.
    store = InMemorySessionStore()
    ids = [store.create("alice").id for _ in range(4)]
    other = store.create("bob").id
    removed = store.revoke_all_for_subject("alice")
    assert removed == 4
    for sid in ids:
        assert store.load(sid) is None
    assert store.load(other) is not None


def test_scenario_sliding_window_keeps_active_user_signed_in() -> None:
    # Active user: each load before idle expiry refreshes the idle clock; the
    # session survives far longer than the idle window but NEVER past absolute.
    clock = {"t": 1000}
    store = InMemorySessionStore(
        idle_timeout_s=60,
        absolute_timeout_s=1000,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    # Step in 30-second increments (half the idle window) for 15 steps.
    for _ in range(15):
        clock["t"] += 30
        assert store.load(s.id) is not None
    # Jump past absolute: session MUST be gone.
    clock["t"] = s.absolute_expires_at + 1
    assert store.load(s.id) is None


def test_scenario_cookie_bind_refuses_broader_than_host() -> None:
    # The web layer asks the store to validate its cookie configuration for a
    # specific application host. A Domain= broader than that host is rejected.
    cfg_broad = CookieConfig(domain="example.com")
    with pytest.raises(SessionInvariantError):
        validate_cookie_host(cfg_broad, "app.example.com")
    # The happy path is host-only (Domain=None), which always validates.
    cfg_ok = CookieConfig()
    validate_cookie_host(cfg_ok, "app.example.com")
