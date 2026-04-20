"""Chaos / game-day tests for Aggregate.

Simulates invariant-violation storms, concurrent mutations, snapshot rollback
under exceptions, and large batches to confirm the aggregate never exposes an
illegal state and the version is always monotonic.
"""

from __future__ import annotations

import threading

import pytest

from Aggregate import (
    AggregateInvariantError,
    InMemoryAggregateRepository,
    OptimisticConcurrencyError,
    OrderAggregate,
)


def test_chaos_repeated_invariant_violations_preserve_state() -> None:
    order = OrderAggregate("C-1", "c")
    order.add_line("good", 1)
    snapshot = order.line_summary()
    version = order.version
    for _ in range(200):
        with pytest.raises(AggregateInvariantError):
            order.add_line("bad", 0)
    assert order.line_summary() == snapshot
    assert order.version == version


def test_chaos_concurrent_commands_preserve_version_monotonicity() -> None:
    order = OrderAggregate("C-2", "c")
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            order.add_line(f"sku-{i}", 1)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Exactly 50 successful commands after the constructor's version==1.
    assert order.version == 1 + 50
    assert order.line_count == 50


def test_chaos_large_batch_respects_max_lines() -> None:
    """Adding lines up to the documented MAX_LINES succeeds; one more is rejected."""
    order = OrderAggregate("C-3", "c")
    for i in range(OrderAggregate.MAX_LINES):
        order.add_line(f"sku-{i}", 1)
    assert order.line_count == OrderAggregate.MAX_LINES
    with pytest.raises(AggregateInvariantError):
        order.add_line("overflow", 1)


def test_chaos_stale_save_storm_never_corrupts_repository() -> None:
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("C-4", "c")
    order.add_line("sku", 1)
    repo.save(order)

    rejected = 0
    for _ in range(50):
        stale = OrderAggregate("C-4", "c")
        try:
            repo.save(stale)
        except OptimisticConcurrencyError:
            rejected += 1
    assert rejected == 50
    # Repo still has the latest version intact.
    stored = repo.get("C-4")
    assert stored.version == order.version


def test_chaos_snapshot_restore_runs_under_rollback() -> None:
    """When _check_invariants raises, the pre-mutation snapshot is restored."""
    order = OrderAggregate("C-5", "c")
    order.add_line("ok", 1)
    prior_summary = order.line_summary()
    # Multiple failures in a row cannot mutate the underlying list.
    for _ in range(25):
        with pytest.raises(AggregateInvariantError):
            order.add_line("bad", -999)
    assert order.line_summary() == prior_summary


def test_chaos_pull_events_thread_safe_under_drain_storm() -> None:
    order = OrderAggregate("C-6", "c")
    for i in range(20):
        order.add_line(f"sku-{i}", 1)

    drained: list[int] = []
    lock = threading.Lock()

    def drain() -> None:
        n = len(list(order.pull_events()))
        with lock:
            drained.append(n)

    threads = [threading.Thread(target=drain) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Exactly one thread sees events, the rest see empty. Total events drained == produced.
    assert sum(drained) == 21  # 1 OrderPlaced + 20 LineAdded


def test_chaos_empty_aggregate_publishes_creation_event() -> None:
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("C-7", "c")
    events = repo.save(order)
    assert [type(e).__name__ for e in events] == ["OrderPlaced"]
    assert order.pending_event_count == 0
