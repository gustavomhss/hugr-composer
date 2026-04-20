"""Chaos / game-day tests for SessionStore.

Exercises fixation replay, rotation races, revoke-all during create storm,
clock-skew, broken RNG, and massive session fan-out.
"""

from __future__ import annotations

import itertools
import threading

import pytest

from SessionStore import InMemorySessionStore, SessionInvariantError


def test_chaos_rotate_replay_of_old_cookie_fails() -> None:
    store = InMemorySessionStore()
    old = store.create("alice")
    new = store.rotate(old.id)
    # Replaying the old cookie MUST fail even though rotation just happened.
    assert store.load(old.id) is None
    assert store.load(new.id) is not None
    assert store.is_revoked(old.id)


def test_chaos_revoke_all_during_create_storm() -> None:
    store = InMemorySessionStore()
    stop = threading.Event()
    created: list[str] = []
    lock = threading.Lock()

    def creator() -> None:
        while not stop.is_set():
            try:
                s = store.create("alice")
                with lock:
                    created.append(s.id)
            except SessionInvariantError:
                # Our guarded RNG never collides; if it ever did, tolerate it.
                return

    ts = [threading.Thread(target=creator) for _ in range(4)]
    for t in ts:
        t.start()
    # Let creators run, then hit the big red button.
    for _ in range(50):
        store.revoke_all_for_subject("alice")
    stop.set()
    for t in ts:
        t.join(timeout=2.0)
    # Final revoke_all: any stragglers MUST be gone after this call.
    store.revoke_all_for_subject("alice")
    for sid in created:
        assert store.load(sid) is None


def test_chaos_broken_rng_collision_is_detected() -> None:
    # An RNG that emits only one value should NOT silently overwrite the first session.
    collide = "chaos" + "z" * 40
    factory = itertools.chain([collide], itertools.repeat(collide))
    store = InMemorySessionStore(id_factory=lambda: next(factory))
    store.create("alice")
    with pytest.raises(SessionInvariantError):
        store.create("bob")


def test_chaos_clock_moves_backward_does_not_resurrect() -> None:
    # Clock-skew: the clock jumps backward after creation. The session MUST
    # still respect absolute_expires_at (which is absolute unix seconds, not
    # relative) — so moving the clock backward just makes the session older.
    clock = {"t": 10_000}
    store = InMemorySessionStore(
        idle_timeout_s=60,
        absolute_timeout_s=120,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    clock["t"] = s.absolute_expires_at + 5
    assert store.load(s.id) is None
    # Clock jumps back before absolute; session MUST NOT resurrect because
    # we dropped the record on natural expiry.
    clock["t"] = s.created_at + 10
    assert store.load(s.id) is None


def test_chaos_revoke_of_unknown_id_is_idempotent_tombstone() -> None:
    store = InMemorySessionStore()
    unknown = "zzzz" + "y" * 40
    store.revoke(unknown)  # MUST NOT raise
    assert store.is_revoked(unknown)
    # A later matching create (astronomically unlikely) MUST not resurrect it.


def test_chaos_massive_revoke_all_fans_out() -> None:
    store = InMemorySessionStore()
    for _ in range(5_000):
        store.create("alice")
    n = store.revoke_all_for_subject("alice")
    assert n == 5_000
    assert store.live_session_ids() == frozenset()


def test_chaos_concurrent_rotate_same_session_one_wins() -> None:
    store = InMemorySessionStore()
    s = store.create("alice")
    winners: list[str] = []
    losers: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            new = store.rotate(s.id)
            with lock:
                winners.append(new.id)
        except SessionInvariantError as exc:
            with lock:
                losers.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(winners) == 1
    assert len(winners) + len(losers) == 16
    assert store.load(s.id) is None
