"""Behavioral end-to-end scenarios for BoundedContext — proves invariants at runtime."""

from __future__ import annotations

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
    _OwnershipLedger,
)


class _SalesOrder:
    pass


class _BillingInvoice:
    pass


def _fresh_triple() -> tuple[SimpleBoundedContext, SimpleBoundedContext, ContextMap]:
    ledger = _OwnershipLedger()
    cmap = ContextMap()
    sales = SimpleBoundedContext("sales", context_map=cmap, ledger=ledger)
    billing = SimpleBoundedContext("billing", context_map=cmap, ledger=ledger)
    return sales, billing, cmap


def test_scenario_each_context_owns_its_aggregates() -> None:
    sales, billing, _cmap = _fresh_triple()
    sales.claim(_SalesOrder)
    billing.claim(_BillingInvoice)
    assert sales.owns(_SalesOrder) and not sales.owns(_BillingInvoice)
    assert billing.owns(_BillingInvoice) and not billing.owns(_SalesOrder)


def test_scenario_second_context_cannot_hijack_aggregate() -> None:
    sales, billing, _cmap = _fresh_triple()
    sales.claim(_SalesOrder)
    with pytest.raises(SharedOwnershipError):
        billing.claim(_SalesOrder)


def test_scenario_conformist_requires_translator_and_translates() -> None:
    sales, billing, cmap = _fresh_triple()
    acl = NoopAntiCorruptionLayer()
    billing.publish_integration(sales, REL_CONFORMIST, direction="upstream", translator=acl)
    # Billing is downstream of sales — billing MUST translate inbound sales payloads.
    assert cmap.relationship("sales", "billing") == REL_CONFORMIST
    foreign_payload = {"order_id": 42}
    local_payload = acl.to_local(foreign_payload)
    assert local_payload == {"local_of": {"order_id": 42}}


def test_scenario_partnership_lists_both_endpoints_on_context_map() -> None:
    sales, billing, cmap = _fresh_triple()
    sales.publish_integration(billing, REL_PARTNERSHIP)
    integrations = tuple(cmap.integrations())
    assert integrations == (("sales", "billing", REL_PARTNERSHIP),)
    assert set(cmap.contexts()) == {"sales", "billing"}


def test_scenario_raw_cross_context_object_leak_is_blocked() -> None:
    sales, billing, _cmap = _fresh_triple()
    acl = NoopAntiCorruptionLayer()
    sales.publish_integration(billing, REL_CUSTOMER_SUPPLIER, translator=acl)

    class _SalesDomainEntity:
        pass

    # Forwarding a raw sales domain object to billing — without translation —
    # MUST raise so billing NEVER imports sales vocabulary.
    with pytest.raises(CrossContextLeakError):
        sales.forward(billing, _SalesDomainEntity(), local_types=(_SalesDomainEntity,))


def test_scenario_language_conflict_between_contexts_is_allowed() -> None:
    # The SAME term can legitimately have DIFFERENT meanings in different
    # contexts — that is the entire reason BoundedContext exists. What is
    # forbidden is two meanings inside ONE context.
    sales, billing, _cmap = _fresh_triple()
    sales.define_term("customer", "a purchaser of products")
    billing.define_term("customer", "an entity that receives an invoice")
    assert sales.language["customer"] != billing.language["customer"]
    with pytest.raises(UbiquitousLanguageConflictError):
        sales.define_term("customer", "a prospect in the CRM")


def test_scenario_open_host_has_no_translator_requirement() -> None:
    # Open Host exposes a published-language schema; no per-consumer ACL is
    # mandated by this primitive (consumers install their own ACLs).
    sales, billing, cmap = _fresh_triple()
    sales.publish_integration(billing, REL_OPEN_HOST)
    assert cmap.relationship("sales", "billing") == REL_OPEN_HOST


def test_scenario_acl_integration_refuses_without_translator() -> None:
    sales, billing, _cmap = _fresh_triple()
    with pytest.raises(CrossContextLeakError):
        sales.publish_integration(billing, REL_ACL)  # no translator supplied
