"""Metamorphic + differential tests for Aggregate.

Algebraic properties:
- pull_events is idempotent after drain (returns empty twice in a row)
- version increments monotonically with each successful command
- rollback-on-failure leaves (state, version, events) equivalent to the prior
- save is a no-op on an already-saved aggregate if no further commands ran
  (differential: second save raises OptimisticConcurrencyError)
"""

from __future__ import annotations

import pytest

from Aggregate import (
    AggregateInvariantError,
    InMemoryAggregateRepository,
    OptimisticConcurrencyError,
    OrderAggregate,
)


def test_metamorphic_pull_events_idempotent_after_drain() -> None:
    order = OrderAggregate("M-1", "c")
    order.add_line("sku", 1)
    first = list(order.pull_events())
    assert first  # non-empty first drain
    second = list(order.pull_events())
    assert second == []  # subsequent drains return empty until new mutations


def test_metamorphic_version_matches_successful_commands() -> None:
    order = OrderAggregate("M-2", "c")
    # Constructor mutates once (OrderPlaced) → version==1.
    base = order.version
    for i in range(10):
        order.add_line(f"sku-{i}", 1)
    assert order.version == base + 10


def test_metamorphic_rollback_equivalence() -> None:
    """State after failed command ≡ state just before the failing command."""
    a = OrderAggregate("M-3", "c")
    a.add_line("sku", 1)
    before = (a.line_summary(), a.version, a.pending_event_count)

    with pytest.raises(AggregateInvariantError):
        a.add_line("bad", 0)

    after = (a.line_summary(), a.version, a.pending_event_count)
    assert before == after


def test_differential_double_save_without_change_rejected() -> None:
    """Saving an aggregate twice without any mutation is rejected (version unchanged)."""
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("M-4", "c")
    order.add_line("sku", 1)
    repo.save(order)
    # No new command → version unchanged → second save is stale.
    with pytest.raises(OptimisticConcurrencyError):
        repo.save(order)


def test_metamorphic_event_count_equals_version_minus_noop_mutations() -> None:
    """Every successful mutation produces exactly one version bump.

    Because the reference impl emits exactly one event per _mutate call (when
    event != None), the count of pending events equals the number of emitting
    commands since the last drain.
    """
    order = OrderAggregate("M-5", "c")
    # Drain the construction event so we start the check at zero.
    list(order.pull_events())
    pre_version = order.version
    for i in range(4):
        order.add_line(f"sku-{i}", 1)
    assert order.pending_event_count == 4
    assert order.version - pre_version == 4
