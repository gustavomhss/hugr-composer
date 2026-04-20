"""Tests for the lock-free + serializable example."""
from __future__ import annotations

import threading
import time

import pytest

from app import CasStore, ConflictError, Record


def test_reads_do_not_take_locks_under_write_contention() -> None:
    store = CasStore()
    store.cas("r1", expected_rev=0, a=1, b=1, c=1)

    stop = threading.Event()
    errors: list[str] = []

    def writer():
        rev = 1
        while not stop.is_set():
            try:
                new = store.cas("r1", expected_rev=rev, a=rev, b=rev, c=rev)
                rev = new.rev
            except ConflictError as e:
                rev = e.current_rev

    def reader():
        # Lots of reads, all lock-free.
        for _ in range(10_000):
            r = store.read("r1")
            if r is None:
                errors.append("missing")

    writers = [threading.Thread(target=writer) for _ in range(10)]
    for w in writers:
        w.start()
    reader()
    stop.set()
    for w in writers:
        w.join()

    assert errors == []
    # Reader never acquired a lock — instrumentation confirms zero reads
    # incremented the counter (it would if we'd held the write lock).
    assert store.read_lock_acquires == 0


def test_concurrent_writers_one_winner_one_retryable_error() -> None:
    store = CasStore()
    store.cas("r1", expected_rev=0, a=0, b=0, c=0)
    # Two writers both think they're at rev=1.
    w1 = store.cas("r1", expected_rev=1, a=1, b=1, c=1)
    assert w1.rev == 2
    with pytest.raises(ConflictError) as exc:
        store.cas("r1", expected_rev=1, a=2, b=2, c=2)
    assert exc.value.current_rev == 2


def test_reads_are_self_consistent_no_torn_multifield_read() -> None:
    store = CasStore()
    store.cas("r1", expected_rev=0, a=1, b=1, c=1)

    stop = threading.Event()

    def writer():
        rev = 1
        n = 1
        while not stop.is_set():
            try:
                # Always write (n, n, n) so all fields are equal in every version.
                new = store.cas("r1", expected_rev=rev, a=n, b=n, c=n)
                rev = new.rev
                n += 1
            except ConflictError as e:
                rev = e.current_rev

    threads = [threading.Thread(target=writer) for _ in range(5)]
    for t in threads:
        t.start()
    try:
        for _ in range(10_000):
            r = store.read("r1")
            # Invariant: a == b == c in every version. A torn read would break this.
            assert r.a == r.b == r.c
    finally:
        stop.set()
        for t in threads:
            t.join()


def test_reads_after_write_observe_it() -> None:
    store = CasStore()
    store.cas("r1", expected_rev=0, a=5, b=5, c=5)
    # Simulate 100 ms elapsed.
    time.sleep(0.01)
    r = store.read("r1")
    assert r is not None and r.a == 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
