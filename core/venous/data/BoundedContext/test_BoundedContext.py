"""Unit tests for BoundedContext — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from BoundedContext import (
    REL_ACL,
    REL_CONFORMIST,
    REL_CUSTOMER_SUPPLIER,
    REL_OPEN_HOST,
    REL_PARTNERSHIP,
    ContextMap,
    CrossContextLeakError,
    NoopAntiCorruptionLayer,
    SharedOwnershipError,
    SimpleBoundedContext,
    UbiquitousLanguageConflictError,
    UnmappedIntegrationError,
    _OwnershipLedger,
)


def _fresh_pair(
    a_name: str = "sales",
    b_name: str = "billing",
) -> tuple[SimpleBoundedContext, SimpleBoundedContext, ContextMap]:
    # Use a fresh ledger + context map so tests don't leak state across runs.
    ledger = _OwnershipLedger()
    cmap = ContextMap()
    a = SimpleBoundedContext(a_name, context_map=cmap, ledger=ledger)
    b = SimpleBoundedContext(b_name, context_map=cmap, ledger=ledger)
    return a, b, cmap


# ---------------------------------------------------------------------------
# BC_INV_01 — single ownership of Aggregate types
# ---------------------------------------------------------------------------
class _OrderAgg:
    pass


class _InvoiceAgg:
    pass


def test_inv_single_ownership_confirms() -> None:
    a, _b, _cmap = _fresh_pair()
    a.claim(_OrderAgg)
    assert a.owns(_OrderAgg) is True


def test_inv_single_ownership_prevents() -> None:
    a, b, _cmap = _fresh_pair()
    a.claim(_OrderAgg)
    with pytest.raises(SharedOwnershipError):
        b.claim(_OrderAgg)


def test_inv_single_ownership_under_failure() -> None:
    a, b, _cmap = _fresh_pair()
    a.claim(_OrderAgg)
    # Repeated rejection attempts MUST NOT corrupt the ledger — the second
    # context still cannot claim the type and the first context still owns it.
    for _ in range(20):
        try:
            b.claim(_OrderAgg)
        except SharedOwnershipError:
            pass
    assert a.owns(_OrderAgg) is True
    assert b.owns(_OrderAgg) is False


# ---------------------------------------------------------------------------
# BC_INV_02 — cross-context calls go through an ACL
# ---------------------------------------------------------------------------
def test_inv_acl_translation_confirms() -> None:
    a, b, _cmap = _fresh_pair()
    acl = NoopAntiCorruptionLayer()
    a.publish_integration(b, REL_CONFORMIST, translator=acl)
    result = a.forward(b, {"event": "x"})
    assert acl.guarded == [{"event": "x"}]
    assert result == {"foreign_of": {"event": "x"}}


def test_inv_acl_translation_prevents() -> None:
    a, b, _cmap = _fresh_pair()
    # Integration kind that requires an ACL — omitting the translator is rejected.
    with pytest.raises(CrossContextLeakError):
        a.publish_integration(b, REL_ACL)
    # Without any integration at all, translator_to raises.
    with pytest.raises(CrossContextLeakError):
        a.translator_to(b)


def test_inv_acl_translation_under_failure() -> None:
    a, b, _cmap = _fresh_pair()
    acl = NoopAntiCorruptionLayer()
    a.publish_integration(b, REL_CUSTOMER_SUPPLIER, translator=acl)

    class _LocalOrder:
        pass

    # Passing a raw local object through forward must be rejected — the ACL
    # NEVER sees the local type directly.
    with pytest.raises(CrossContextLeakError):
        a.forward(b, _LocalOrder(), local_types=(_LocalOrder,))


# ---------------------------------------------------------------------------
# BC_INV_03 — ubiquitous language is locally consistent
# ---------------------------------------------------------------------------
def test_inv_language_consistent_confirms() -> None:
    a, _b, _cmap = _fresh_pair()
    a.define_term("order", "a customer purchase")
    # Idempotent redefinition with the same meaning is allowed.
    a.define_term("order", "a customer purchase")
    assert a.language["order"] == "a customer purchase"


def test_inv_language_consistent_prevents() -> None:
    a, _b, _cmap = _fresh_pair()
    a.define_term("order", "a customer purchase")
    with pytest.raises(UbiquitousLanguageConflictError):
        a.define_term("order", "an invoice with tax lines")


def test_inv_language_consistent_under_failure() -> None:
    a, _b, _cmap = _fresh_pair()
    a.define_term("shipment", "physical dispatch")
    for _ in range(10):
        try:
            a.define_term("shipment", "an email notification")
        except UbiquitousLanguageConflictError:
            pass
    # The original meaning survives every failed redefinition attempt.
    assert a.language["shipment"] == "physical dispatch"


# ---------------------------------------------------------------------------
# BC_INV_04 — integrations are published on a ContextMap
# ---------------------------------------------------------------------------
def test_inv_context_map_confirms() -> None:
    a, b, cmap = _fresh_pair()
    a.publish_integration(b, REL_PARTNERSHIP)
    assert cmap.relationship("sales", "billing") == REL_PARTNERSHIP
    assert ("sales", "billing", REL_PARTNERSHIP) in tuple(cmap.integrations())


def test_inv_context_map_prevents() -> None:
    _a, _b, cmap = _fresh_pair()
    # No integration registered yet — shadow lookup MUST fail loudly.
    with pytest.raises(UnmappedIntegrationError):
        cmap.relationship("sales", "billing")
    # Unknown relationship kinds MUST be rejected.
    with pytest.raises(UnmappedIntegrationError):
        cmap.add_relationship("sales", "billing", "RandomKind")
    # Self-loops are forbidden.
    with pytest.raises(UnmappedIntegrationError):
        cmap.add_relationship("sales", "sales", REL_PARTNERSHIP)


def test_inv_context_map_under_failure() -> None:
    a, b, cmap = _fresh_pair()
    # Canonical kinds that do NOT require an ACL.
    a.publish_integration(b, REL_OPEN_HOST)
    # Concurrent readers MUST always see the edge exactly once.
    seen: list[str] = []
    lock = threading.Lock()

    def reader() -> None:
        try:
            kind = cmap.relationship("sales", "billing")
        except UnmappedIntegrationError:  # pragma: no cover — defensive
            kind = "missing"
        with lock:
            seen.append(kind)

    ts = [threading.Thread(target=reader) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(s == REL_OPEN_HOST for s in seen)
