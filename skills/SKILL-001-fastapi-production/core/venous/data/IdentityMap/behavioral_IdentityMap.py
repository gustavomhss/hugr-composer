"""Behavioral end-to-end scenarios for IdentityMap — proves invariants at runtime."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from IdentityMap import (
    IdentityMapInvariantError,
    InMemoryIdentityMap,
    session_scope,
)


@dataclass
class Order:
    id: int
    total: int = 0


@dataclass
class Invoice:
    id: int
    amount: int = 0


def test_scenario_get_or_load_returns_cached_reference() -> None:
    """The classic Fowler get-or-load pattern: the second load MUST NOT hit storage."""

    load_calls: list[int] = []

    def repo_get(order_id: int) -> Order:
        load_calls.append(order_id)
        return Order(id=order_id, total=100)

    def load_order(imap: InMemoryIdentityMap, order_id: int) -> Order:
        cached = imap.get(Order, order_id)
        if cached is not None:
            return cached  # type: ignore[no-any-return]  # IDMAP-INV-01: stored ref narrows at call site.
        fresh = repo_get(order_id)
        imap.add(fresh)
        return fresh

    with session_scope() as imap:
        first = load_order(imap, 1)
        second = load_order(imap, 1)
        # Only ONE repo call — second lookup hits the identity map.
        assert load_calls == [1]
        assert first is second


def test_scenario_two_sessions_do_not_share_references() -> None:
    """Two concurrent UoW sessions MUST NOT see each other's cached entries."""

    with session_scope() as s1:
        s1.add(Order(id=1, total=10))
    # Session s1 is disposed here; its contents are gone.

    with session_scope() as s2:
        assert s2.get(Order, 1) is None
        s2.add(Order(id=1, total=20))
        assert s2.get(Order, 1) is not None
        assert s2.size() == 1


def test_scenario_exception_disposes_the_session() -> None:
    """On exception, the session is disposed and its references cleared."""

    captured: list[InMemoryIdentityMap] = []
    with pytest.raises(RuntimeError):
        with session_scope() as imap:
            captured.append(imap)
            imap.add(Order(id=99))
            raise RuntimeError("downstream failure")
    imap = captured[0]
    assert imap.state == "disposed"
    with pytest.raises(IdentityMapInvariantError):
        imap.get(Order, 99)


def test_scenario_remove_fires_eviction_hook() -> None:
    """Eviction hooks observe removals without weakening referential identity."""

    seen: list[tuple[type, object]] = []
    imap = InMemoryIdentityMap()
    imap.register_eviction_hook(lambda t, i, _obj: seen.append((t, i)))

    order = Order(id=5)
    imap.add(order)
    imap.remove(Order, 5)
    assert seen == [(Order, 5)]
    # Re-adding after removal is allowed (identity was released cleanly).
    imap.add(Order(id=5))
    assert imap.get(Order, 5) is not None


def test_scenario_multiple_types_share_one_map() -> None:
    """One map tracks heterogeneous aggregates by (type, id), with no cross-leak."""

    with session_scope() as imap:
        order = Order(id=1, total=100)
        invoice = Invoice(id=1, amount=50)
        imap.add(order)
        imap.add(invoice)
        assert imap.get(Order, 1) is order
        assert imap.get(Invoice, 1) is invoice
        # Same id across different types is NOT a conflict.
        assert imap.contains(Order, 1) is True
        assert imap.contains(Invoice, 1) is True
        assert imap.get(Order, 1) is not invoice


def test_scenario_add_same_reference_twice_is_idempotent() -> None:
    """Re-adding the same reference is a no-op, preserving IDMAP-INV-01."""

    imap = InMemoryIdentityMap()
    order = Order(id=11)
    imap.add(order)
    imap.add(order)  # identical reference — must not raise
    imap.add(order)
    assert imap.get(Order, 11) is order
    assert imap.size() == 1
