"""Concurrency / linearizability harness for Aggregate.

Confirms that concurrent commands and pull_events never corrupt version
monotonicity or the internal line list, and that optimistic concurrency
under the repository rejects stale writers deterministically.
"""

from __future__ import annotations

import threading

import pytest
from Aggregate import (
    InMemoryAggregateRepository,
    OptimisticConcurrencyError,
    OrderAggregate,
)


def test_concurrent_commands_preserve_version_monotonicity() -> None:
    order = OrderAggregate("CC-1", "cust")
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            order.add_line(f"sku-{i}", 1)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Exactly 40 successful commands; version bumped to constructor + 40.
    assert order.version == 1 + 40
    assert order.line_count == 40
    summary = order.line_summary()
    assert len(summary) == 40
    # All qty values are positive — invariant held throughout.
    for _sku, qty in summary:
        assert qty > 0


def test_concurrent_stale_saves_all_rejected() -> None:
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("CC-2", "cust")
    order.add_line("sku", 1)
    repo.save(order)

    accepted: list[int] = []
    rejected: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        stale = OrderAggregate("CC-2", "cust")
        try:
            repo.save(stale)
            with lock:
                accepted.append(1)
        except OptimisticConcurrencyError:
            with lock:
                rejected.append(1)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert accepted == []  # every stale save MUST be rejected
    assert len(rejected) == 30


def test_concurrent_pull_events_linearized() -> None:
    """Multiple threads draining share the event buffer — total == produced."""
    order = OrderAggregate("CC-3", "cust")
    for i in range(25):
        order.add_line(f"sku-{i}", 1)

    seen: list[int] = []
    lock = threading.Lock()

    def drain() -> None:
        n = len(list(order.pull_events()))
        with lock:
            seen.append(n)

    threads = [threading.Thread(target=drain) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one drain sees all events, the rest see zero → sum == produced.
    assert sum(seen) == 26  # 1 OrderPlaced + 25 LineAdded
    # Buffer now empty.
    assert list(order.pull_events()) == []


def test_concurrent_invariant_violations_never_mutate_state() -> None:
    order = OrderAggregate("CC-4", "cust")
    order.add_line("ok", 1)
    prior_summary = order.line_summary()
    prior_version = order.version

    failures: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            order.add_line("bad", 0)  # AGG-INV-03 rejects
        except Exception:
            with lock:
                failures.append(1)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(failures) == 40
    assert order.line_summary() == prior_summary
    assert order.version == prior_version
    # Suppress mypy/ruff "unused pytest import" — referenced for fixture compat.
    _ = pytest
