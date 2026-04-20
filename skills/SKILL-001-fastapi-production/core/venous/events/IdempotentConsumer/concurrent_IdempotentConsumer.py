"""Concurrency / linearizability harness for IdempotentConsumer.

The consumer wraps an InboxDeduplicator that allows ONE active transaction
per instance. These tests serialize writer access with an external lock (the
recommended deployment pattern) and confirm the exactly-once-effect
invariant survives arbitrary concurrent delivery orderings.
"""

from __future__ import annotations

import threading

from IdempotentConsumer import EchoMessage, build_echo_consumer


def test_concurrent_identical_keys_collapse_to_one_effect() -> None:
    c, inbox, outbox = build_echo_consumer()
    gate = threading.Lock()

    def worker() -> None:
        with gate:
            c.handle(EchoMessage(id="shared"))

    ts = [threading.Thread(target=worker) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert c.effect_runs == 1
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1


def test_concurrent_distinct_keys_all_processed_exactly_once() -> None:
    c, inbox, outbox = build_echo_consumer()
    gate = threading.Lock()

    def worker(i: int) -> None:
        with gate:
            c.handle(EchoMessage(id=f"k-{i}"))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert c.effect_runs == 50
    assert len(inbox.store_snapshot) == 50
    assert len(outbox.store_snapshot) == 50


def test_concurrent_readers_see_monotone_effect_count() -> None:
    """Concurrent readers of c.effect_runs NEVER see it decrease."""
    c, _, _ = build_echo_consumer()
    gate = threading.Lock()
    stop = threading.Event()
    violations: list[int] = []
    v_lock = threading.Lock()

    def reader() -> None:
        last = 0
        while not stop.is_set():
            cur = c.effect_runs
            if cur < last:
                with v_lock:
                    violations.append(1)
            last = cur

    def writer() -> None:
        for i in range(30):
            with gate:
                c.handle(EchoMessage(id=f"w-{i}"))

    readers = [threading.Thread(target=reader) for _ in range(5)]
    for r in readers:
        r.start()
    writer()
    import time as _t
    _t.sleep(0.02)
    stop.set()
    for r in readers:
        r.join()

    assert violations == []
    assert c.effect_runs == 30


def test_concurrent_duplicate_floor_never_applies_twice() -> None:
    """Even under heavy duplicate racing, the effect runs exactly once."""
    c, _, outbox = build_echo_consumer()
    gate = threading.Lock()
    barrier = threading.Barrier(16)

    def worker() -> None:
        barrier.wait()
        with gate:
            c.handle(EchoMessage(id="race"))

    ts = [threading.Thread(target=worker) for _ in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert c.effect_runs == 1
    assert len(outbox.store_snapshot) == 1
