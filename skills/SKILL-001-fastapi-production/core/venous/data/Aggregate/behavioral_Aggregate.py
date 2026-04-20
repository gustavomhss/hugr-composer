"""Behavioral end-to-end scenarios for Aggregate — proves invariants at runtime."""

from __future__ import annotations

import pytest

from Aggregate import (
    AggregateInvariantError,
    ForbiddenReferenceError,
    InMemoryAggregateRepository,
    OptimisticConcurrencyError,
    OrderAggregate,
    require_identifier_reference,
)


def test_scenario_order_lifecycle_emits_events_in_order() -> None:
    """End-to-end: create order, add lines, save → events drained in order."""
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("order-1", "cust-1")
    order.add_line("sku-A", 2)
    order.add_line("sku-B", 3)
    events = repo.save(order)
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["OrderPlaced", "LineAdded", "LineAdded"]
    # After save+drain, the repository has the aggregate at the latest version.
    stored = repo.get("order-1")
    assert stored.version == order.version
    # Draining twice returns empty — pull_events cleared the buffer.
    assert list(order.pull_events()) == []


def test_scenario_stale_save_is_rejected_by_optimistic_concurrency() -> None:
    repo = InMemoryAggregateRepository[str]()
    first = OrderAggregate("order-2", "cust-2")
    first.add_line("sku", 1)
    repo.save(first)

    # A separately-created aggregate at v0 cannot overwrite the stored v>0.
    stale = OrderAggregate("order-2", "cust-2")
    with pytest.raises(OptimisticConcurrencyError):
        repo.save(stale)


def test_scenario_invariant_violation_rolls_back_state() -> None:
    order = OrderAggregate("order-3", "cust-3")
    order.add_line("good", 1)
    prior_summary = order.line_summary()
    prior_version = order.version

    with pytest.raises(AggregateInvariantError):
        order.add_line("bad", 0)

    # Rollback: no partial mutation survives the failed command.
    assert order.line_summary() == prior_summary
    assert order.version == prior_version


def test_scenario_cross_aggregate_reference_rejected() -> None:
    order_a = OrderAggregate("order-A", "cust-A")
    with pytest.raises(ForbiddenReferenceError):
        # Attempt to pass another AggregateRoot where an id was expected.
        require_identifier_reference(order_a)


def test_scenario_only_root_references_exposed_externally() -> None:
    """Children (_OrderLine) NEVER leak across the aggregate boundary."""
    order = OrderAggregate("order-4", "cust-4")
    order.add_line("sku", 7)
    summary = order.line_summary()
    assert summary == (("sku", 7),)
    # The projection is a tuple of tuples — no private class escapes.
    for item in summary:
        assert isinstance(item, tuple)
        assert not hasattr(item, "__dict__")  # no Python object with mutable attrs


def test_scenario_save_publishes_events_after_commit() -> None:
    """AGG-INV-02: events are the cross-aggregate coordination primitive.

    The repository drains pending events as part of save — subscribers never
    see events for state that is not yet persisted.
    """
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("order-5", "cust-5")
    order.add_line("x", 1)
    # Before save: events are pending (creation + line).
    assert order.pending_event_count > 0
    events = repo.save(order)
    # After save: events have been drained and returned to the caller.
    assert len(events) > 0
    assert order.pending_event_count == 0
