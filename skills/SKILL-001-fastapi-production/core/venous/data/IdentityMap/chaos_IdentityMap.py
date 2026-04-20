"""Chaos / game-day tests for IdentityMap.

Simulates pathological access patterns — disposing mid-flight, mass reads
against a disposed map, attempting cross-session reference leaks, large-scale
registrations, and racy duplicate inserts — to confirm the map NEVER
weakens referential identity or leaks references past dispose.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest

from IdentityMap import (
    IdentityMapInvariantError,
    InMemoryIdentityMap,
    session_scope,
)


@dataclass
class Order:
    id: int
    total: int = 0


def test_chaos_many_duplicates_rejected() -> None:
    imap = InMemoryIdentityMap()
    original = Order(id=1)
    imap.add(original)
    rejections = 0
    for _ in range(200):
        try:
            imap.add(Order(id=1))
        except IdentityMapInvariantError:
            rejections += 1
    assert rejections == 200
    assert imap.get(Order, 1) is original


def test_chaos_dispose_then_mass_read_rejects() -> None:
    imap = InMemoryIdentityMap()
    for i in range(1000):
        imap.add(Order(id=i))
    imap.dispose()
    failures = 0
    for i in range(1000):
        try:
            imap.get(Order, i)
        except IdentityMapInvariantError:
            failures += 1
    assert failures == 1000


def test_chaos_large_batch_preserves_identity() -> None:
    imap = InMemoryIdentityMap()
    refs = [Order(id=i) for i in range(10_000)]
    for o in refs:
        imap.add(o)
    # Sample every 100th entry and confirm exact reference identity.
    for i in range(0, 10_000, 100):
        assert imap.get(Order, i) is refs[i]
    assert imap.size() == 10_000


def test_chaos_race_duplicate_insert_preserves_canonical() -> None:
    imap = InMemoryIdentityMap()
    canonical = Order(id=1)
    imap.add(canonical)

    lock = threading.Lock()
    accepted: list[int] = []
    rejected: list[int] = []

    def worker() -> None:
        try:
            imap.add(Order(id=1))
            with lock:
                accepted.append(1)
        except IdentityMapInvariantError:
            with lock:
                rejected.append(1)

    threads = [threading.Thread(target=worker) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Zero accepted — the canonical reference survives.
    assert accepted == []
    assert len(rejected) == 32
    assert imap.get(Order, 1) is canonical


def test_chaos_cross_session_does_not_leak() -> None:
    captured: list[InMemoryIdentityMap] = []
    with session_scope() as m1:
        m1.add(Order(id=500))
        captured.append(m1)
    # m1 disposed.
    with session_scope() as m2:
        assert m2.get(Order, 500) is None
        captured.append(m2)
    # Neither map retains live references post-scope.
    for m in captured:
        assert m.state == "disposed"
        with pytest.raises(IdentityMapInvariantError):
            m.get(Order, 500)


def test_chaos_hook_exception_does_not_corrupt_cache() -> None:
    imap = InMemoryIdentityMap()

    def angry_hook(_t: type, _i: object, _obj: object) -> None:
        raise ValueError("hook refused")

    imap.register_eviction_hook(angry_hook)
    imap.add(Order(id=1))
    # Hook exception surfaces to the caller — we do NOT silently swallow it.
    with pytest.raises(ValueError):
        imap.remove(Order, 1)
    # Even though the hook raised, the eviction itself completed, so the map
    # is consistent and a fresh add for the same id succeeds.
    imap.add(Order(id=1))
    assert imap.get(Order, 1) is not None


def test_chaos_empty_session_disposes_cleanly() -> None:
    with session_scope() as imap:
        assert imap.size() == 0
    assert imap.state == "disposed"
