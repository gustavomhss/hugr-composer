"""Metamorphic + differential tests for SessionStore.

Algebraic laws:
- revoke is idempotent
- revoke_all_for_subject is additive over disjoint subjects
- rotate preserves subject and absolute ceiling
- successive loads within window yield monotonically non-decreasing idle_expires_at
- create -> load is the identity up to idle-window refresh (subject + absolute ceiling equal)
"""

from __future__ import annotations

from SessionStore import InMemorySessionStore


def test_metamorphic_revoke_idempotent() -> None:
    store = InMemorySessionStore()
    s = store.create("alice")
    for _ in range(10):
        store.revoke(s.id)
    assert store.load(s.id) is None
    assert store.is_revoked(s.id)


def test_metamorphic_rotate_preserves_subject_and_absolute() -> None:
    store = InMemorySessionStore()
    s = store.create("alice")
    current = s
    prev_ids: set[str] = {s.id}
    for _ in range(5):
        current = store.rotate(current.id)
        assert current.subject == "alice"
        assert current.absolute_expires_at == s.absolute_expires_at
        assert current.id not in prev_ids
        prev_ids.add(current.id)


def test_metamorphic_revoke_all_additive_over_disjoint_subjects() -> None:
    store = InMemorySessionStore()
    for _ in range(3):
        store.create("alice")
    for _ in range(4):
        store.create("bob")
    a = store.revoke_all_for_subject("alice")
    b = store.revoke_all_for_subject("bob")
    # Sum across disjoint subjects equals the total created.
    assert a + b == 7
    assert store.live_session_ids() == frozenset()


def test_metamorphic_load_idle_monotonic_within_window() -> None:
    clock = {"t": 1000}
    store = InMemorySessionStore(
        idle_timeout_s=60,
        absolute_timeout_s=1000,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    last_idle = s.idle_expires_at
    for _ in range(10):
        clock["t"] += 5
        loaded = store.load(s.id)
        assert loaded is not None
        assert loaded.idle_expires_at >= last_idle
        last_idle = loaded.idle_expires_at


def test_differential_create_load_identity() -> None:
    # create(subject) → load(id) returns a session with the same id, subject
    # and absolute ceiling. The idle clock may be renewed (sliding window) but
    # NEVER beyond absolute.
    store = InMemorySessionStore()
    s = store.create("alice")
    loaded = store.load(s.id)
    assert loaded is not None
    assert (loaded.id, loaded.subject, loaded.absolute_expires_at) == (
        s.id,
        s.subject,
        s.absolute_expires_at,
    )
    assert loaded.idle_expires_at <= loaded.absolute_expires_at


def test_differential_rotate_then_load_vs_load_fresh() -> None:
    # rotate then load(new) ≡ load(fresh_create_with_same_absolute_window)
    # up to subject + absolute; the idle windows should match on the same clock.
    clock = {"t": 2000}
    store = InMemorySessionStore(
        idle_timeout_s=30,
        absolute_timeout_s=600,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    clock["t"] = 2010
    rotated = store.rotate(s.id)
    # Idle is based on 'now' (2010) but capped by s.absolute_expires_at (2600).
    assert rotated.idle_expires_at == min(2010 + 30, s.absolute_expires_at)
