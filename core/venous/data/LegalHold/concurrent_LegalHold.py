"""Concurrency tests for LegalHold."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from LegalHold import InMemoryLegalHoldRegistry, LegalHold

UTC = UTC


def test_concurrent_opens_distinct_holds() -> None:
    r = InMemoryLegalHoldRegistry()

    def worker(i: int) -> None:
        r.open(LegalHold(
            hold_id=f"h{i}",
            scope_query=f"record_id = 'r{i}'",
            opened_at=datetime.now(UTC),
            opened_by="c",
        ))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert r.size == 30


def test_concurrent_covers_consistent() -> None:
    r = InMemoryLegalHoldRegistry()
    r.open(LegalHold(
        hold_id="h", scope_query="record_id = 'x'",
        opened_at=datetime.now(UTC), opened_by="c",
    ))
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        res = r.covers("x")
        with lock:
            results.append(res)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(results)
