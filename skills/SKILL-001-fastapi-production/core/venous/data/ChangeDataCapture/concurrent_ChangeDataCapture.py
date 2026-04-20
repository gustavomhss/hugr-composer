"""Concurrency / linearizability harness for ChangeDataCapture.

Confirms that under concurrent staging, commit, rollback, subscribe, and
checkpoint calls:
- positions are strictly monotonic with no duplicates (CDC-INV-02);
- per-transaction ordering survives concurrent interleavings (CDC-INV-01);
- subscribe snapshots never expose uncommitted events (CDC-INV-03);
- checkpoint rewind is rejected even under racing writers (CDC-INV-02).
"""

from __future__ import annotations

import threading

from ChangeDataCapture import (
    ChangeDataCaptureInvariantError,
    InMemoryChangeDataCapture,
)


def test_concurrent_commits_preserve_position_monotonicity() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    errors: list[BaseException] = []
    lock = threading.Lock()
    N = 100

    def worker(tag: int) -> None:
        try:
            for i in range(N):
                txid = f"w{tag}-{i}"
                cdc.begin_tx(txid)
                cdc.stage_change(txid, "t", "insert", tag * 10_000 + i, None, {"id": i})
                cdc.commit_tx(txid)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    events = [e for e in cdc.subscribe("t", 0) if e["op"] != "schema"]
    assert len(events) == 4 * N
    positions = [int(e["pos"]) for e in events]  # type: ignore[arg-type]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)


def test_concurrent_per_tx_ordering_preserved() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    errors: list[BaseException] = []
    lock = threading.Lock()
    STAGES_PER_TX = 50

    def worker(tag: int) -> None:
        try:
            for i in range(10):
                txid = f"w{tag}-{i}"
                cdc.begin_tx(txid)
                for j in range(STAGES_PER_TX):
                    cdc.stage_change(txid, "t", "insert", tag * 1_000_000 + i * 1000 + j, None, {"j": j})
                cdc.commit_tx(txid)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    events = [e for e in cdc.subscribe("t", 0) if e["op"] != "schema"]
    # Group by txid and verify that within each tx, positions are strictly
    # increasing AND contiguous (no other tx's events interleaved).
    by_tx: dict[str, list[int]] = {}
    for e in events:
        by_tx.setdefault(str(e["txid"]), []).append(int(e["pos"]))  # type: ignore[arg-type]
    for txid, positions in by_tx.items():
        assert positions == sorted(positions), f"tx {txid} reordered"
        assert positions[-1] - positions[0] == len(positions) - 1, f"tx {txid} was interleaved"


def test_concurrent_subscribe_never_sees_uncommitted() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    stop = threading.Event()
    errors: list[BaseException] = []
    seen_uncommitted = [0]
    lock = threading.Lock()

    def producer() -> None:
        try:
            i = 0
            while not stop.is_set():
                txid = f"p-{i}"
                cdc.begin_tx(txid)
                cdc.stage_change(txid, "t", "insert", i, None, {"id": i})
                cdc.stage_change(txid, "t", "update", i, None, {"id": i, "x": 1})
                if i % 2 == 0:
                    cdc.commit_tx(txid)
                else:
                    cdc.rollback_tx(txid)
                i += 1
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(200):
                for ev in cdc.subscribe("t", 0):
                    if not ev.get("committed", False):
                        with lock:
                            seen_uncommitted[0] += 1
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
    assert seen_uncommitted[0] == 0


def test_concurrent_checkpoint_rewind_always_rejected() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    for i in range(20):
        cdc.begin_tx(f"t{i}")
        cdc.stage_change(f"t{i}", "t", "insert", i, None, {"id": i})
        cdc.commit_tx(f"t{i}")
    cdc.checkpoint(50)

    rejected = [0]
    lock = threading.Lock()

    def rewinder() -> None:
        for _ in range(50):
            try:
                cdc.checkpoint(1)
            except ChangeDataCaptureInvariantError:
                with lock:
                    rejected[0] += 1

    ts = [threading.Thread(target=rewinder) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert rejected[0] == 6 * 50
    assert cdc.checkpoint_of() == 50
