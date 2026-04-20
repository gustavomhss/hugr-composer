"""Concurrency / linearizability harness for SessionStore.

Exercises concurrent create, rotate, revoke, and revoke_all under multi-thread
contention and asserts the state machine stays consistent.
"""

from __future__ import annotations

import threading

from SessionStore import InMemorySessionStore, SessionInvariantError


def test_concurrent_creates_produce_unique_ids() -> None:
    store = InMemorySessionStore()
    errors: list[BaseException] = []
    lock = threading.Lock()
    ids: list[str] = []

    def worker() -> None:
        try:
            for _ in range(100):
                s = store.create("alice")
                with lock:
                    ids.append(s.id)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    # 8 * 100 = 800 sessions, all ids distinct (CSPRNG, no collisions).
    assert len(ids) == 800
    assert len(set(ids)) == 800


def test_concurrent_rotate_yields_single_winner() -> None:
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

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(winners) == 1
    assert len(winners) + len(losers) == 32
    # The losing rotations MUST cite the fixation invariant.
    for exc in losers:
        assert "SESSION-INV-02" in str(exc)


def test_concurrent_revoke_and_load_is_consistent() -> None:
    store = InMemorySessionStore()
    sids = [store.create("alice").id for _ in range(200)]
    results: list[bool] = []
    lock = threading.Lock()

    def revoker(sid: str) -> None:
        store.revoke(sid)

    def loader(sid: str) -> None:
        loaded = store.load(sid)
        with lock:
            results.append(loaded is not None)

    ts: list[threading.Thread] = []
    for sid in sids:
        ts.append(threading.Thread(target=revoker, args=(sid,)))
        ts.append(threading.Thread(target=loader, args=(sid,)))
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Final pass: every sid MUST be unreadable.
    for sid in sids:
        assert store.load(sid) is None
        assert store.is_revoked(sid)


def test_concurrent_revoke_all_is_atomic() -> None:
    # Two simultaneous revoke_all_for_subject calls MUST sum to exactly the
    # number of live sessions at the start — no double-count, no miss.
    store = InMemorySessionStore()
    n_sessions = 500
    for _ in range(n_sessions):
        store.create("alice")

    counts: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        n = store.revoke_all_for_subject("alice")
        with lock:
            counts.append(n)

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(counts) == n_sessions
    assert store.live_session_ids() == frozenset()
