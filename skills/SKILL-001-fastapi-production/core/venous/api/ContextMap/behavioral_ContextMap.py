"""Behavioral end-to-end scenarios for ContextMap.

Each scenario walks a realistic DDD topology and asserts named invariant
outcomes. Scenarios cover:

- Upstream/downstream e-commerce topology (Orders / Billing / Catalog / Shipping).
- Partnership promotion to resolve a Customer-Supplier cycle.
- Anticorruption Layer around a legacy context.
- Published Language + Open Host Service for platform-wide broadcast.
- Conformist + Separate Ways for constrained vendor integrations.
"""

from __future__ import annotations

import pytest

from ContextMap import (
    ContextMapInvariantError,
    InMemoryContextMap,
)


def test_scenario_ecommerce_topology_fully_classified() -> None:
    m = InMemoryContextMap()
    m.add_relationship("Catalog", "Orders", "Published Language")
    m.add_relationship("Orders", "Billing", "Customer-Supplier")
    m.add_relationship("Orders", "Shipping", "Customer-Supplier")
    m.add_relationship("Billing", "Ledger", "Customer-Supplier")
    m.add_relationship("Legacy-ERP", "Ledger", "Anticorruption Layer")
    # Every edge has a canonical kind and every context is surfaced on the map.
    expected_contexts = {"Catalog", "Orders", "Billing", "Shipping", "Ledger", "Legacy-ERP"}
    assert set(m.contexts()) == expected_contexts
    for (_u, _d, k) in m.integrations():
        assert k != ""


def test_scenario_partnership_resolves_customer_supplier_cycle() -> None:
    m = InMemoryContextMap()
    m.add_relationship("TeamA", "TeamB", "Customer-Supplier")
    m.add_relationship("TeamB", "TeamC", "Customer-Supplier")
    # TeamC → TeamA as Customer-Supplier would cycle — forbidden.
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-02"):
        m.add_relationship("TeamC", "TeamA", "Customer-Supplier")
    # Promote to Partnership — permitted, and audit counter moves forward.
    before = m.version
    m.add_relationship("TeamC", "TeamA", "Partnership")
    assert m.version == before + 1


def test_scenario_shadow_integration_surfaces_loudly() -> None:
    m = InMemoryContextMap()
    m.add_relationship("Orders", "Billing", "Customer-Supplier")
    # An auditor asks "what's the integration between Orders and Payments?" —
    # CTXMAP-INV-03 answers with a loud error because nobody registered it.
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-03"):
        m.relationship("Orders", "Payments")


def test_scenario_published_language_plus_open_host_platform() -> None:
    m = InMemoryContextMap()
    m.add_relationship("Platform", "Orders", "Open Host Service")
    m.add_relationship("Platform", "Billing", "Open Host Service")
    m.add_relationship("Platform", "Ledger", "Published Language")
    # Multiple downstream consumers share a single Platform upstream — all edges
    # use canonical kinds.
    ints = tuple(m.integrations())
    assert len(ints) == 3
    kinds = {k for (_u, _d, k) in ints}
    assert kinds == {"Open Host Service", "Published Language"}


def test_scenario_conformist_and_separate_ways_coexist() -> None:
    m = InMemoryContextMap()
    m.add_relationship("Vendor", "Orders", "Conformist")
    # Separate Ways is a legitimate integration kind for "we deliberately don't talk".
    m.add_relationship("Orders", "Analytics", "Separate Ways")
    assert m.relationship("Vendor", "Orders") == "Conformist"
    assert m.relationship("Orders", "Analytics") == "Separate Ways"


def test_scenario_every_mutation_is_audited() -> None:
    m = InMemoryContextMap()
    history: list[int] = []
    history.append(m.version)
    m.add_relationship("A", "B", "Conformist")
    history.append(m.version)
    m.add_relationship("B", "C", "Conformist")
    history.append(m.version)
    # Audit counter strictly increases on every successful mutation.
    assert history == [0, 1, 2]
    assert history == sorted(history)
