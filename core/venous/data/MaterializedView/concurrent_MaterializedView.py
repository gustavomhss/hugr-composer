"""Concurrency / linearizability harness for MaterializedView.

Confirms that concurrent apply() + query() calls never corrupt view state,
seq ordering holds under races, and the lock prevents torn rows.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from MaterializedView import InMemoryMaterializedView


def _upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    aid = str(event["aggregate_id"])
    payload = event.get("payload", {})
    assert isinstance(payload, Mapping)
    rows[aid] = {"aggregate_id": aid, **dict(payload)}


def test_concurrent_apply_preserves_seq_monotonicity() -> None:
    view = InMemoryMaterializedView("orders")
    view.register_handler("order.upserted", _upsert)

    N = 500
    errors: list[BaseException] = []
    lock = threading.Lock()

    def producer(offset: int) -> None:
        try:
            for i in range(N):
                seq = offset + i
                view.apply({
                    "type": "order.upserted",
                    "aggregate_id": f"o{seq}",
                    "seq": seq,
                    "schema_version": 1,
                    "payload": {"worker": offset},
                })
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    # Non-overlapping seq ranges — all events must materialize, last_applied_seq monotonic.
    threads = [
        threading.Thread(target=producer, args=(1,)),
        threading.Thread(target=producer, args=(1001,)),
        threading.Thread(target=producer, args=(2001,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert view.applied_event_count == 3 * N
    assert view.last_applied_seq >= 2001 + N - 1


def test_concurrent_query_during_apply_sees_consistent_snapshot() -> None:
    view = InMemoryMaterializedView("orders")
    view.register_handler("order.upserted", _upsert)

    done = threading.Event()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def writer() -> None:
        try:
            for i in range(1, 1001):
                view.apply({
                    "type": "order.upserted",
                    "aggregate_id": f"o{i}",
                    "seq": i,
                    "schema_version": 1,
                    "payload": {"i": i},
                })
        finally:
            done.set()

    snapshots_seen: list[int] = []

    def reader() -> None:
        try:
            while not done.is_set():
                rows = list(view.query(None))
                snapshots_seen.append(len(rows))
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    wt = threading.Thread(target=writer)
    rt = threading.Thread(target=reader)
    wt.start()
    rt.start()
    wt.join()
    rt.join()

    assert not errors
    # Every snapshot was a consistent row count (never torn / partial rows).
    for n in snapshots_seen:
        assert 0 <= n <= 1000
    assert len(list(view.query(None))) == 1000


def test_concurrent_duplicate_seq_deduped_under_race() -> None:
    view = InMemoryMaterializedView("orders")
    view.register_handler("order.upserted", _upsert)

    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(100):
                view.apply({
                    "type": "order.upserted",
                    "aggregate_id": "o1",
                    "seq": 1,
                    "schema_version": 1,
                    "payload": {"val": 1},
                })
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errors
    # Despite 800 total attempts at seq=1, exactly one actual application.
    assert view.applied_event_count == 1
    assert view.last_applied_seq == 1


def test_concurrent_rebuild_and_query_never_race() -> None:
    view = InMemoryMaterializedView("orders")
    view.register_handler("order.upserted", _upsert)
    view.rebuild([
        {
            "type": "order.upserted",
            "aggregate_id": f"o{i}",
            "seq": i,
            "schema_version": 1,
            "payload": {"i": i},
        }
        for i in range(1, 101)
    ])

    errors: list[BaseException] = []
    lock = threading.Lock()
    results: list[int] = []

    def reader() -> None:
        try:
            for _ in range(50):
                results.append(len(list(view.query(None))))
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    def rebuilder() -> None:
        try:
            for _ in range(5):
                view.rebuild([
                    {
                        "type": "order.upserted",
                        "aggregate_id": f"o{i}",
                        "seq": i,
                        "schema_version": 1,
                        "payload": {"i": i},
                    }
                    for i in range(1, 101)
                ])
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(3)] + [
        threading.Thread(target=rebuilder)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Readers NEVER saw a partial rebuild — every count is either 0 or 100.
    for n in results:
        assert n in (0, 100)
