"""Concurrency / linearizability harness for InboxDeduplicator.

The inbox allows ONE active transaction per instance (INBOX-INV-01). Readers
of ``seen`` and ``store_snapshot``, and purgers of old rows, may run
concurrently with each other. These tests confirm that the shared store
stays consistent across all interleavings.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from InboxDeduplicator import (
    InboxDeduplicatorInvariantError,
    InMemoryInboxDeduplicator,
)


def test_concurrent_serialized_first_deliveries_unique_pairs() -> None:
    """Threads deliver distinct pairs in parallel, each acquiring the writer
    lock — every pair lands exactly once with no conflicts."""
    inbox = InMemoryInboxDeduplicator()
    errs: list[BaseException] = []
    err_lock = threading.Lock()
    writer_lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            with writer_lock:
                with inbox.handle(f"m-{i}", "c", lambda: None):
                    pass
        except BaseException as exc:  # noqa: BLE001 — concurrency harness records any failure for diagnostics
            with err_lock:
                errs.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errs
    assert len(inbox.store_snapshot) == 50


def test_concurrent_duplicates_of_same_pair_collapse_to_one_record() -> None:
    """Same (message_id, consumer) submitted by many threads → store has one row."""
    inbox = InMemoryInboxDeduplicator()
    errs: list[BaseException] = []
    err_lock = threading.Lock()
    writer_lock = threading.Lock()
    effect_runs: list[int] = []

    def worker() -> None:
        try:
            with writer_lock:
                with inbox.handle("shared", "c", lambda: effect_runs.append(1)):
                    pass
        except BaseException as exc:  # noqa: BLE001 — concurrency harness records any failure for diagnostics
            with err_lock:
                errs.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(30)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errs
    assert sum(effect_runs) == 1  # effect ran exactly once
    assert len(inbox.store_snapshot) == 1


def test_concurrent_readers_see_consistent_seen_across_writes() -> None:
    """Parallel readers NEVER observe seen=True flipping back to False."""
    inbox = InMemoryInboxDeduplicator()
    writer_lock = threading.Lock()

    def writer() -> None:
        with writer_lock:
            with inbox.handle("m", "c", lambda: None):
                pass

    flips_to_false: list[int] = []
    flip_lock = threading.Lock()
    stop = threading.Event()

    def reader() -> None:
        observed_true = False
        while not stop.is_set():
            v = inbox.seen("m", "c")
            if v is True:
                observed_true = True
            elif observed_true and v is False:
                with flip_lock:
                    flips_to_false.append(1)

    readers = [threading.Thread(target=reader) for _ in range(8)]
    for r in readers:
        r.start()
    writer()
    # Give readers a window to observe post-write state.
    import time as _t
    _t.sleep(0.05)
    stop.set()
    for r in readers:
        r.join()

    assert flips_to_false == []
    assert inbox.seen("m", "c") is True


def test_concurrent_nested_begin_rejected_across_threads() -> None:
    inbox = InMemoryInboxDeduplicator()
    rejected: list[int] = []
    reject_lock = threading.Lock()

    def attempter() -> None:
        try:
            scope = inbox.begin()
            scope.rollback()
        except InboxDeduplicatorInvariantError:
            with reject_lock:
                rejected.append(1)

    outer = inbox.begin()
    try:
        ts = [threading.Thread(target=attempter) for _ in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        outer.rollback()
    assert len(rejected) == 10


def test_concurrent_purge_excluding_fresh_rows_is_safe() -> None:
    """A thread purging old rows cannot evict a row younger than retention."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    # Mix of old (purgeable) and new (protected) records.
    clock_state["t"] = now - timedelta(days=30)
    for i in range(20):
        with inbox.handle(f"old-{i}", "c", lambda: None):
            pass
    clock_state["t"] = now
    for i in range(20):
        with inbox.handle(f"new-{i}", "c", lambda: None):
            pass

    errs: list[BaseException] = []
    err_lock = threading.Lock()

    def purger() -> None:
        try:
            cutoff = (clock_state["t"] - timedelta(days=14)).isoformat()
            inbox.purge_older_than(cutoff)
        except BaseException as exc:  # noqa: BLE001 — concurrency harness records any failure for diagnostics
            with err_lock:
                errs.append(exc)

    ts = [threading.Thread(target=purger) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errs
    remaining_ids = {r["message_id"] for r in inbox.store_snapshot}
    assert all(mid.startswith("new-") for mid in remaining_ids)
    assert len(remaining_ids) == 20
