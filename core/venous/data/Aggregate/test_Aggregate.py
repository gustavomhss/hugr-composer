"""Unit tests for Aggregate — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from Aggregate import (
    AggregateInvariantError,
    ForbiddenReferenceError,
    InMemoryAggregateRepository,
    OptimisticConcurrencyError,
    OrderAggregate,
    require_identifier_reference,
)


# ---------------------------------------------------------------------------
# AGG_INV_01 — root-only external access (children stay encapsulated)
# ---------------------------------------------------------------------------
def test_inv_root_only_access_confirms() -> None:
    order = OrderAggregate("O-1", "C-1")
    order.add_line("SKU-A", 2)
    # External view is a tuple projection, NEVER the internal _OrderLine instances.
    summary = order.line_summary()
    assert summary == (("SKU-A", 2),)
    assert isinstance(summary, tuple)


def test_inv_root_only_access_prevents() -> None:
    order = OrderAggregate("O-2", "C-2")
    order.add_line("SKU-X", 1)
    # line_summary MUST return copies/tuples; mutating the returned structure
    # CANNOT mutate internal _OrderLine state.
    summary = order.line_summary()
    # Attempt to modify the exposed projection — tuples reject it.
    with pytest.raises((TypeError, AttributeError)):
        summary[0] = ("HACK", 999)  # type: ignore[index] — tuples are immutable
    assert order.line_summary() == (("SKU-X", 1),)


def test_inv_root_only_access_under_failure() -> None:
    # Even when commands fail, no internal child leaks through the API.
    order = OrderAggregate("O-3", "C-3")
    prior = order.line_summary()
    with pytest.raises(AggregateInvariantError):
        order.add_line("BAD", -5)  # negative qty → AGG-INV-03 rejects
    # After failure, external surface is unchanged — still no children exposed.
    assert order.line_summary() == prior


# ---------------------------------------------------------------------------
# AGG_INV_02 — single aggregate per transaction (save) + events coordinate
# ---------------------------------------------------------------------------
def test_inv_single_aggregate_tx_confirms() -> None:
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("O-A", "C-A")
    order.add_line("SKU", 1)
    events = repo.save(order)
    # Events are published AFTER save; cross-aggregate updates travel via events.
    assert any(type(e).__name__ == "OrderPlaced" for e in events)
    assert any(type(e).__name__ == "LineAdded" for e in events)


def test_inv_single_aggregate_tx_prevents() -> None:
    # `save` accepts one aggregate; there is no bulk-save API. A multi-aggregate
    # call path simply does not exist — verify the surface by inspection.
    repo = InMemoryAggregateRepository[str]()
    assert not hasattr(repo, "save_all")
    assert not hasattr(repo, "save_many")


def test_inv_single_aggregate_tx_under_failure() -> None:
    # Under a mid-operation failure, events are NOT drained — they remain
    # pending until a successful save publishes them atomically.
    order = OrderAggregate("O-B", "C-B")
    try:
        order.add_line("SKU", -1)  # AGG-INV-03 rejects
    except AggregateInvariantError:
        pass
    # The failure did NOT rot the pending-event buffer; OrderPlaced is still there.
    pending = list(order.pull_events())
    assert any(type(e).__name__ == "OrderPlaced" for e in pending)


# ---------------------------------------------------------------------------
# AGG_INV_03 — root invariants hold at the end of every public method
# ---------------------------------------------------------------------------
def test_inv_root_invariants_confirms() -> None:
    order = OrderAggregate("O-C", "C-C")
    for i in range(5):
        order.add_line(f"SKU-{i}", 1)
    assert order.line_count == 5
    # Every intermediate state that was exposed satisfies the checker.


def test_inv_root_invariants_prevents() -> None:
    order = OrderAggregate("O-D", "C-D")
    with pytest.raises(AggregateInvariantError):
        order.add_line("SKU", 0)  # zero qty is illegal
    with pytest.raises(AggregateInvariantError):
        order.add_line("SKU", -10)


def test_inv_root_invariants_under_failure() -> None:
    # A failing command MUST restore the prior snapshot — no partial mutations.
    order = OrderAggregate("O-E", "C-E")
    order.add_line("GOOD", 1)
    prior_count = order.line_count
    prior_version = order.version
    with pytest.raises(AggregateInvariantError):
        order.add_line("BAD", 0)
    assert order.line_count == prior_count
    assert order.version == prior_version


# ---------------------------------------------------------------------------
# AGG_INV_04 — version monotonicity + optimistic concurrency
# ---------------------------------------------------------------------------
def test_inv_version_monotonic_confirms() -> None:
    order = OrderAggregate("O-F", "C-F")
    v0 = order.version
    order.add_line("A", 1)
    v1 = order.version
    order.add_line("B", 1)
    v2 = order.version
    assert v0 < v1 < v2


def test_inv_version_monotonic_prevents() -> None:
    # Optimistic-concurrency save: the second save of a stale snapshot MUST fail.
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("O-G", "C-G")
    order.add_line("A", 1)
    repo.save(order)
    # Simulate a stale aggregate: create another aggregate with same id at v0.
    stale = OrderAggregate("O-G", "C-G")  # version lower than repo's stored copy
    with pytest.raises(OptimisticConcurrencyError):
        repo.save(stale)


def test_inv_version_monotonic_under_failure() -> None:
    # When a command fails, the version MUST NOT advance.
    order = OrderAggregate("O-H", "C-H")
    pre = order.version
    with pytest.raises(AggregateInvariantError):
        order.add_line("BAD", -1)
    assert order.version == pre  # no phantom increment under failure


# ---------------------------------------------------------------------------
# AGG_INV_05 — id-only cross-aggregate references
# ---------------------------------------------------------------------------
def test_inv_id_only_reference_confirms() -> None:
    order = OrderAggregate("O-I", "customer-42")
    # customer is stored by string identifier — not an object.
    # Access via private attribute for assertion (contract: id-only).
    assert order._customer_id == "customer-42"
    require_identifier_reference("customer-42")  # strings are fine


def test_inv_id_only_reference_prevents() -> None:
    other = OrderAggregate("O-OTHER", "C-OTHER")
    with pytest.raises(ForbiddenReferenceError):
        require_identifier_reference(other)


def test_inv_id_only_reference_under_failure() -> None:
    # Concurrent threads repeatedly attempting forbidden references all fail cleanly.
    other = OrderAggregate("O-J", "C-J")
    failures = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal failures
        try:
            require_identifier_reference(other)
        except ForbiddenReferenceError:
            with lock:
                failures += 1

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == 20
