"""Concurrency / linearizability harness for EventStream.

Confirms that under concurrent appends, reads, and truncations:
- per-partition seqs are strictly monotonic and contiguous (ES-INV-01);
- read_from snapshots never observe torn state (ES-INV-03);
- truncate rewind is rejected even under racing writers (ES-INV-04);
- stored events survive caller mutation across threads (ES-INV-02).
"""

from __future__ import annotations

import threading

from EventStream import (
    EventStreamInvariantError,
    InMemoryEventStream,
)


def test_concurrent_appends_preserve_seq_monotonicity_on_single_partition() -> None:
    es = InMemoryEventStream()
    errors: list[BaseException] = []
    lock = threading.Lock()
    WORKERS = 4
    PER = 50

    def worker(tag: int) -> None:
        try:
            for i in range(PER):
                es.append("shared", {"tag": tag, "i": i})
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    seqs = [int(e["seq"]) for e in es.log_snapshot("shared")]  # type: ignore[arg-type]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, WORKERS * PER + 1))
    assert len(set(seqs)) == len(seqs)


def test_concurrent_appends_multiple_partitions_isolated() -> None:
    # Concurrent appenders target different partitions — each partition's
    # sequence stays contiguous 1..PER regardless of global interleaving.
    es = InMemoryEventStream()
    errors: list[BaseException] = []
    lock = threading.Lock()
    PER = 40
    PARTITIONS = ("a", "b", "c", "d")

    def worker(key: str) -> None:
        try:
            for i in range(PER):
                es.append(key, {"i": i})
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in PARTITIONS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    for key in PARTITIONS:
        seqs = [int(e["seq"]) for e in es.log_snapshot(key)]  # type: ignore[arg-type]
        assert seqs == list(range(1, PER + 1))


def test_concurrent_read_never_sees_torn_events() -> None:
    es = InMemoryEventStream()
    stop = threading.Event()
    errors: list[BaseException] = []
    torn = [0]
    lock = threading.Lock()

    def producer() -> None:
        try:
            i = 0
            # Cap producer work so the reader's repeated full-log scans stay
            # bounded — the test is about torn events, not throughput.
            while not stop.is_set() and i < 500:
                es.append("p", {"i": i, "payload": [1, 2, 3]})
                i += 1
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    def reader() -> None:
        try:
            # The tail cursor advances, so we use it to only scan the new
            # suffix each round — still catches torn reads without going
            # quadratic against the producer's growth.
            cursor = 1
            for _ in range(50):
                for ev in es.read_from("p", cursor):
                    if not isinstance(ev, dict) or "i" not in ev or "payload" not in ev:
                        with lock:
                            torn[0] += 1
                cursor = es.tail("p")
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    pt = threading.Thread(target=producer)
    rt = threading.Thread(target=reader)
    pt.start()
    rt.start()
    rt.join()
    stop.set()
    pt.join()
    assert not errors
    assert torn[0] == 0


def test_concurrent_truncate_rewind_always_rejected() -> None:
    es = InMemoryEventStream(retention_min_entries=0)
    for i in range(30):
        es.append("p", {"i": i})
    es.truncate_before(15)

    rejected = [0]
    lock = threading.Lock()

    def rewinder() -> None:
        for _ in range(40):
            try:
                es.truncate_before(1)
            except EventStreamInvariantError:
                with lock:
                    rejected[0] += 1

    ts = [threading.Thread(target=rewinder) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert rejected[0] == 5 * 40
    assert es.truncated_before_of("p") == 15


def test_concurrent_mutation_does_not_leak_to_log() -> None:
    # Appenders mutate their payloads right after appending; the stored log
    # remains untouched thanks to deep-copy on ingress (ES-INV-02).
    es = InMemoryEventStream()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(tag: int) -> None:
        try:
            for i in range(30):
                p: dict[str, object] = {"tag": tag, "i": i, "items": [0, 1]}
                es.append("p", p)
                # Torch the caller's copy right after append.
                items = p["items"]
                if isinstance(items, list):
                    items.clear()
                p["i"] = -1
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    snap = es.log_snapshot("p")
    # Every stored event has its original, untouched payload.
    for entry in snap:
        ev = entry["event"]
        assert isinstance(ev, dict)
        assert ev.get("items") == [0, 1]
        assert isinstance(ev.get("i"), int)
        val_i = ev["i"]
        assert isinstance(val_i, int)
        assert val_i >= 0
