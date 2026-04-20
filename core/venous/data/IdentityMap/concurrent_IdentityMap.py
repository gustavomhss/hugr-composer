"""Concurrency / linearizability harness for IdentityMap.

Confirms that concurrent reads, writes, and duplicate-insert attempts from
many threads within one session NEVER weaken referential identity.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from IdentityMap import (
    IdentityMapInvariantError,
    InMemoryIdentityMap,
)


@dataclass
class Order:
    id: int


def test_concurrent_distinct_writes_preserve_identity() -> None:
    imap = InMemoryIdentityMap()
    orders = [Order(id=i) for i in range(500)]
    errors: list[BaseException] = []
    lock = threading.Lock()

    def writer(start: int, stop: int) -> None:
        try:
            for i in range(start, stop):
                imap.add(orders[i])
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(i * 125, (i + 1) * 125))
        for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for i in range(500):
        assert imap.get(Order, i) is orders[i]
    assert imap.size() == 500


def test_concurrent_duplicate_insert_attempts_serialize() -> None:
    imap = InMemoryIdentityMap()
    canonical = Order(id=1)
    imap.add(canonical)

    lock = threading.Lock()
    accepted: list[int] = []
    rejected: list[int] = []

    def attacker() -> None:
        try:
            imap.add(Order(id=1))
            with lock:
                accepted.append(1)
        except IdentityMapInvariantError:
            with lock:
                rejected.append(1)

    threads = [threading.Thread(target=attacker) for _ in range(64)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert accepted == []
    assert len(rejected) == 64
    # Canonical reference is intact.
    assert imap.get(Order, 1) is canonical


def test_concurrent_readers_see_consistent_reference() -> None:
    imap = InMemoryIdentityMap()
    order = Order(id=42)
    imap.add(order)

    lock = threading.Lock()
    reads: list[object] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            for _ in range(250):
                ref = imap.get(Order, 42)
                with lock:
                    reads.append(ref)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Every single read saw the SAME canonical reference.
    assert all(r is order for r in reads)
    assert len(reads) == 8 * 250


def test_concurrent_idempotent_re_add_same_reference() -> None:
    imap = InMemoryIdentityMap()
    order = Order(id=7)

    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(100):
                imap.add(order)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert imap.get(Order, 7) is order
    assert imap.size() == 1


def test_concurrent_dispose_during_reads_stays_consistent() -> None:
    imap = InMemoryIdentityMap()
    for i in range(100):
        imap.add(Order(id=i))

    errors: list[str] = []
    lock = threading.Lock()

    def reader() -> None:
        try:
            for _ in range(200):
                try:
                    imap.get(Order, 0)
                except IdentityMapInvariantError:
                    return
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(repr(exc))

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    imap.dispose()
    for t in threads:
        t.join()
    assert not errors
    assert imap.state == "disposed"
