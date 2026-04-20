"""Chaos / fault-injection for ContextMap.

Game-day scenarios — the four invariants MUST survive each:

- Flood of malformed context names (empty / whitespace / control chars / oversized).
- Storm of cycle-inducing Customer-Supplier edges from many threads.
- Mixed storm of valid and invalid mutations — valid ones retained, audit
  counter equals exactly the number of successful mutations.
- Repeated relationship() lookups across threads — no state drift.
- Self-loop attempts and shadow-edge lookups from a worker pool.
"""

from __future__ import annotations

import threading

import pytest

from ContextMap import (
    ContextMapInvariantError,
    InMemoryContextMap,
)


def test_chaos_malformed_context_names_all_refused() -> None:
    m = InMemoryContextMap()
    bad_names = ["", "   ", "a\x00b", "a\x7f", "x" * 200]
    for bad in bad_names:
        with pytest.raises(ContextMapInvariantError):
            m.add_relationship(bad, "B", "Conformist")
        with pytest.raises(ContextMapInvariantError):
            m.add_relationship("A", bad, "Conformist")
    # None of the failed calls should have registered a context.
    assert tuple(m.contexts()) == ()


def test_chaos_cycle_storm_never_corrupts_graph() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Customer-Supplier")
    m.add_relationship("B", "C", "Customer-Supplier")

    errors: list[BaseException] = []

    def attacker() -> None:
        try:
            m.add_relationship("C", "A", "Customer-Supplier")
        except ContextMapInvariantError:
            pass  # expected: CTXMAP-INV-02
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=attacker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # No cycle introduced — original two edges intact.
    assert not m.has_edge("C", "A")
    assert m.has_edge("A", "B")
    assert m.has_edge("B", "C")


def test_chaos_mixed_storm_audit_counter_matches_successes() -> None:
    m = InMemoryContextMap()
    successes = 0
    attempts = [
        ("A", "B", "Conformist", True),
        ("B", "C", "bogus", False),
        ("C", "D", "Published Language", True),
        ("", "Z", "Conformist", False),
        ("D", "E", "Open Host Service", True),
        ("E", "E", "Conformist", False),  # self-loop
    ]
    for u, d, k, should_pass in attempts:
        try:
            m.add_relationship(u, d, k)
            successes += 1
            assert should_pass, f"expected to fail: {(u, d, k)}"
        except ContextMapInvariantError:
            assert not should_pass, f"expected to pass: {(u, d, k)}"
    assert m.version == successes == 3


def test_chaos_repeated_lookup_is_stable() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Conformist")
    results: list[str] = []
    lock = threading.Lock()

    def reader() -> None:
        for _ in range(25):
            val = m.relationship("A", "B")
            with lock:
                results.append(val)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8 * 25
    assert all(v == "Conformist" for v in results)


def test_chaos_shadow_edge_lookup_always_raises() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Conformist")
    # Many attackers probing shadow integrations — every call MUST raise.
    for probe in [("X", "Y"), ("B", "A"), ("A", "C"), ("Orders", "Payments")]:
        with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-03"):
            m.relationship(*probe)


def test_chaos_partnership_promotion_preserves_order_independence() -> None:
    # Promoting to Partnership is the sanctioned escape hatch; verify it
    # doesn't corrupt the existing directional structure.
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Customer-Supplier")
    m.add_relationship("B", "C", "Customer-Supplier")
    m.add_relationship("C", "A", "Partnership")
    # Still able to enumerate, still able to look up each edge.
    assert m.relationship("A", "B") == "Customer-Supplier"
    assert m.relationship("B", "C") == "Customer-Supplier"
    assert m.relationship("C", "A") == "Partnership"
