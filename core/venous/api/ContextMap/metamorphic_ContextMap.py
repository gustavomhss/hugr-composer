"""Metamorphic + differential tests for ContextMap.

Algebraic laws:
- Insertion-order independence: the final set of edges is order-independent.
- Idempotent re-assertion: re-adding the same edge is a no-op semantically
  (the edge set is unchanged; version still bumps to preserve audit trail).
- relationship() is pure: reading does not mutate state.
- integrations() is sorted and stable — two readers see the same tuple.
- Differential: every registered edge is reachable via relationship().
"""

from __future__ import annotations

from ContextMap import InMemoryContextMap


def test_metamorphic_insertion_order_independence() -> None:
    a = InMemoryContextMap()
    b = InMemoryContextMap()
    edges = [
        ("Catalog", "Orders", "Published Language"),
        ("Orders", "Billing", "Customer-Supplier"),
        ("Billing", "Ledger", "Customer-Supplier"),
    ]
    for u, d, k in edges:
        a.add_relationship(u, d, k)
    for u, d, k in reversed(edges):
        b.add_relationship(u, d, k)
    assert tuple(a.integrations()) == tuple(b.integrations())
    assert set(a.contexts()) == set(b.contexts())


def test_metamorphic_relationship_is_pure() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Conformist")
    before = m.version
    snapshot = tuple(m.integrations())
    for _ in range(5):
        assert m.relationship("A", "B") == "Conformist"
    # Neither version nor edge set mutated.
    assert m.version == before
    assert tuple(m.integrations()) == snapshot


def test_metamorphic_integrations_sorted_and_stable() -> None:
    m = InMemoryContextMap()
    m.add_relationship("Z", "Y", "Conformist")
    m.add_relationship("A", "B", "Conformist")
    m.add_relationship("M", "N", "Conformist")
    ints = tuple(m.integrations())
    # Sorted by (upstream, downstream) ascending.
    keys = [(u, d) for (u, d, _k) in ints]
    assert keys == sorted(keys)
    # Two reads return identical tuples.
    assert ints == tuple(m.integrations())


def test_metamorphic_re_assertion_preserves_edge_set() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Conformist")
    snapshot_edges = tuple(m.integrations())
    # Re-asserting the same edge keeps the edge set intact (value unchanged).
    m.add_relationship("A", "B", "Conformist")
    assert tuple(m.integrations()) == snapshot_edges


def test_differential_every_registered_edge_is_readable() -> None:
    m = InMemoryContextMap()
    cases = [
        ("A", "B", "Partnership"),
        ("B", "C", "Shared Kernel"),
        ("C", "D", "Customer-Supplier"),
        ("D", "E", "Conformist"),
        ("E", "F", "Anticorruption Layer"),
        ("F", "G", "Open Host Service"),
        ("G", "H", "Published Language"),
        ("H", "I", "Separate Ways"),
    ]
    for u, d, k in cases:
        m.add_relationship(u, d, k)
    # Differential: for every edge inserted, relationship() returns the same kind.
    for u, d, k in cases:
        assert m.relationship(u, d) == k
    # And integrations() enumerates exactly the inserted set.
    assert set(m.integrations()) == set(cases)
