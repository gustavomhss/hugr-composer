"""Unit tests for ContextMap — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import pytest

from ContextMap import (
    RELATIONSHIP_KINDS,
    ContextMapInvariantError,
    InMemoryContextMap,
)


# ---------------------------------------------------------------------------
# CTXMAP_INV_01 — canonical relationship kinds only
# ---------------------------------------------------------------------------
def test_inv_canonical_kind_confirms() -> None:
    m = InMemoryContextMap()
    for kind in sorted(RELATIONSHIP_KINDS):
        m.add_relationship(f"U-{kind}", f"D-{kind}", kind)
    # Every edge classified with a canonical kind.
    for (_u, _d, k) in m.integrations():
        assert k in RELATIONSHIP_KINDS


def test_inv_canonical_kind_prevents() -> None:
    m = InMemoryContextMap()
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-01"):
        m.add_relationship("Orders", "Billing", "ad-hoc")
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-01"):
        m.add_relationship("Orders", "Billing", "")
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-01"):
        m.add_relationship("Orders", "Billing", "CustomerSupplier")  # missing hyphen


def test_inv_canonical_kind_under_failure() -> None:
    m = InMemoryContextMap()
    # Non-string kind MUST be refused loudly.
    with pytest.raises(ContextMapInvariantError):
        m.add_relationship("A", "B", 42)  # type: ignore[arg-type]  # CTXMAP-INV-01 supporting: non-string kind MUST be rejected.
    with pytest.raises(ContextMapInvariantError):
        m.add_relationship("A", "B", None)  # type: ignore[arg-type]  # CTXMAP-INV-01 supporting: None kind MUST be rejected.


# ---------------------------------------------------------------------------
# CTXMAP_INV_02 — Customer-Supplier graph is directional-acyclic
# ---------------------------------------------------------------------------
def test_inv_directional_acyclic_confirms() -> None:
    m = InMemoryContextMap()
    m.add_relationship("Orders", "Billing", "Customer-Supplier")
    m.add_relationship("Billing", "Ledger", "Customer-Supplier")
    m.add_relationship("Ledger", "Reporting", "Customer-Supplier")
    # Linear chain — acyclic.
    assert len(tuple(m.integrations())) == 3


def test_inv_directional_acyclic_prevents() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Customer-Supplier")
    m.add_relationship("B", "C", "Customer-Supplier")
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-02"):
        m.add_relationship("C", "A", "Customer-Supplier")


def test_inv_directional_acyclic_under_failure() -> None:
    # Promotion to Partnership is permitted even when Customer-Supplier would cycle.
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Customer-Supplier")
    m.add_relationship("B", "C", "Customer-Supplier")
    # Partnership is symmetric; CTXMAP-INV-02 only constrains Customer-Supplier.
    m.add_relationship("C", "A", "Partnership")
    assert m.has_edge("C", "A")


# ---------------------------------------------------------------------------
# CTXMAP_INV_03 — no shadow integrations; invalid context names rejected
# ---------------------------------------------------------------------------
def test_inv_no_shadow_integration_confirms() -> None:
    m = InMemoryContextMap()
    m.add_relationship("Sales", "Fulfillment", "Open Host Service")
    assert m.relationship("Sales", "Fulfillment") == "Open Host Service"
    assert "Sales" in tuple(m.contexts())
    assert "Fulfillment" in tuple(m.contexts())


def test_inv_no_shadow_integration_prevents() -> None:
    m = InMemoryContextMap()
    # Looking up an unregistered edge raises loudly — shadow integrations surfaced.
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-03"):
        m.relationship("Ghost", "Fulfillment")


def test_inv_no_shadow_integration_under_failure() -> None:
    m = InMemoryContextMap()
    # Invalid context names MUST be refused at mutation time too.
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-03"):
        m.add_relationship("", "B", "Conformist")
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-03"):
        m.add_relationship("   ", "B", "Conformist")
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-03"):
        m.add_relationship("A", "A", "Conformist")  # self-loop
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-03"):
        m.add_relationship("A\x00", "B", "Conformist")  # control char


# ---------------------------------------------------------------------------
# CTXMAP_INV_04 — all mutations flow through add_relationship (version bumps)
# ---------------------------------------------------------------------------
def test_inv_auditable_mutation_confirms() -> None:
    m = InMemoryContextMap()
    assert m.version == 0
    m.add_relationship("A", "B", "Conformist")
    assert m.version == 1
    m.add_relationship("B", "C", "Published Language")
    assert m.version == 2


def test_inv_auditable_mutation_prevents() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Conformist")
    # A failed mutation (invalid kind) MUST NOT bump the audit counter.
    with pytest.raises(ContextMapInvariantError):
        m.add_relationship("B", "C", "bogus-kind")
    assert m.version == 1


def test_inv_auditable_mutation_under_failure() -> None:
    m = InMemoryContextMap()
    m.add_relationship("A", "B", "Customer-Supplier")
    m.add_relationship("B", "C", "Customer-Supplier")
    before = m.version
    # A failed cycle insertion MUST NOT bump the audit counter either.
    with pytest.raises(ContextMapInvariantError, match="CTXMAP-INV-02"):
        m.add_relationship("C", "A", "Customer-Supplier")
    assert m.version == before
