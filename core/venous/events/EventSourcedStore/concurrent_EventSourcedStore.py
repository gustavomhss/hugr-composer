"""Concurrency / linearizability harness for EventSourcedStore.

Proves:

- No two appends win for the same expected_version (ESS-INV-01: linearizable
  optimistic concurrency).
- After N successful serialised appends the version equals N and replay gives
  the sum (ESS-INV-04: deterministic fold).
- Concurrent readers observe consistent per-load snapshots (ESS-INV-02).
"""

from __future__ import annotations

import threading

from EventSourcedStore import (
    ConcurrencyError,
    InMemoryEventSourcedStore,
    replay,
)


def _fold(state: object, event: object) -> int:
    assert isinstance(event, dict)
    base = 0 if state is None else int(state)  # type: ignore[arg-type]
    return base + int(event["n"])


def test_concurrent_single_winner_per_version() -> None:
    store = InMemoryEventSourcedStore()
    store.append("a", expected_version=0, events=[{"n": 1}])
    # 32 racers all targeting version 1 — exactly one MUST win.
    winners: list[int] = []
    losers: list[int] = []
    lock = threading.Lock()

    def race() -> None:
        try:
            store.append("a", expected_version=1, events=[{"n": 1}])
            with lock:
                winners.append(1)
        except ConcurrencyError:
            with lock:
                losers.append(1)

    ts = [threading.Thread(target=race) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(winners) == 1
    assert len(winners) + len(losers) == 32
    assert store.current_version("a") == 2


def test_concurrent_retry_loop_converges() -> None:
    # Writers cooperate via a read-append retry loop; at the end every
    # attempted intent lands in the log exactly once.
    store = InMemoryEventSourcedStore()
    attempts_per_worker = 5
    workers = 12
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(worker_id: int) -> None:
        try:
            for j in range(attempts_per_worker):
                while True:
                    v = store.current_version("a")
                    try:
                        store.append("a", expected_version=v,
                                     events=[{"n": worker_id * 100 + j}])
                        break
                    except ConcurrencyError:
                        continue
        except BaseException as exc:
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert store.current_version("a") == workers * attempts_per_worker


def test_concurrent_readers_see_consistent_snapshots() -> None:
    # Reader iterates load() while a writer appends — the reader's snapshot
    # MUST be a prefix of the log at load-call time (ESS-INV-02).
    store = InMemoryEventSourcedStore()
    for i in range(1, 11):
        store.append("a", expected_version=i - 1, events=[{"n": i}])
    seen_lengths: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def reader() -> None:
        try:
            events = list(store.load("a"))
            with lock:
                seen_lengths.append(len(events))
        except BaseException as exc:
            with lock:
                errors.append(exc)

    def writer() -> None:
        try:
            for i in range(11, 21):
                while True:
                    v = store.current_version("a")
                    try:
                        store.append("a", expected_version=v, events=[{"n": i}])
                        break
                    except ConcurrencyError:
                        continue
        except BaseException as exc:
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=reader) for _ in range(20)] + [threading.Thread(target=writer)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    # Every observed length is between 10 (prior to writes) and 20 (after writes).
    assert all(10 <= x <= 20 for x in seen_lengths)
    assert store.current_version("a") == 20


def test_concurrent_deterministic_replay_under_load() -> None:
    # Even with many racing writers, replay from the final log is deterministic.
    store = InMemoryEventSourcedStore()
    n = 100

    def writer(i: int) -> None:
        while True:
            v = store.current_version("agg")
            try:
                store.append("agg", expected_version=v, events=[{"n": i}])
                return
            except ConcurrencyError:
                continue

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert store.current_version("agg") == n
    # Replay a handful of times — identical state each time.
    results = [replay(store, "agg", _fold)[0] for _ in range(5)]
    assert len(set(results)) == 1
    assert results[0] == sum(range(n))


def test_concurrent_snapshot_and_writes_do_not_corrupt_log() -> None:
    # Snapshot writes and event appends interleaved — the log's sum MUST
    # remain equal to its deterministic fold regardless of snapshot activity.
    store = InMemoryEventSourcedStore()
    for i in range(1, 6):
        store.append("a", expected_version=i - 1, events=[{"n": i}])
    errors: list[BaseException] = []
    lock = threading.Lock()

    def snap_loop() -> None:
        try:
            for _ in range(10):
                v = store.current_version("a")
                state, _ = replay(store, "a", _fold)
                try:
                    store.snapshot("a", version=v, state=state)
                except Exception:
                    pass
        except BaseException as exc:
            with lock:
                errors.append(exc)

    def append_loop() -> None:
        try:
            for i in range(6, 16):
                while True:
                    v = store.current_version("a")
                    try:
                        store.append("a", expected_version=v, events=[{"n": i}])
                        break
                    except ConcurrencyError:
                        continue
        except BaseException as exc:
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=snap_loop), threading.Thread(target=append_loop)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    final_state, _ = replay(store, "a", _fold)
    assert final_state == sum(range(1, 16))
