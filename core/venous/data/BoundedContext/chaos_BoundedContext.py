"""Chaos / game-day tests for BoundedContext.

Simulates hostile or buggy downstream usage: rapid repeated claims under
contention, hostile redefinitions of ubiquitous-language terms, unmapped
integration lookups, and translators going missing mid-flight.
"""

from __future__ import annotations

import threading

import pytest

from BoundedContext import (
    REL_ACL,
    REL_CUSTOMER_SUPPLIER,
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


class _Agg:
    pass


def test_chaos_many_hostile_claims_rejected() -> None:
    ledger = _OwnershipLedger()
    a = SimpleBoundedContext("a", ledger=ledger)
    b = SimpleBoundedContext("b", ledger=ledger)
    a.claim(_Agg)
    failures = 0
    for _ in range(200):
        try:
            b.claim(_Agg)
        except SharedOwnershipError:
            failures += 1
    assert failures == 200
    assert a.owns(_Agg) and not b.owns(_Agg)


def test_chaos_hostile_redefinitions_never_stick() -> None:
    ctx = SimpleBoundedContext("a")
    ctx.define_term("order", "legit")
    errors = 0
    for i in range(100):
        try:
            ctx.define_term("order", f"attacker-{i}")
        except UbiquitousLanguageConflictError:
            errors += 1
    assert errors == 100
    assert ctx.language["order"] == "legit"


def test_chaos_unmapped_integration_lookup_fails_loud() -> None:
    cmap = ContextMap()
    with pytest.raises(UnmappedIntegrationError):
        cmap.relationship("sales", "billing")


def test_chaos_concurrent_claim_race_has_exactly_one_winner() -> None:
    ledger = _OwnershipLedger()
    contexts = [SimpleBoundedContext(f"ctx-{i}", ledger=ledger) for i in range(10)]
    winners: list[str] = []
    losers: list[str] = []
    lock = threading.Lock()

    def worker(ctx: SimpleBoundedContext) -> None:
        try:
            ctx.claim(_Agg)
            with lock:
                winners.append(ctx.name)
        except SharedOwnershipError:
            with lock:
                losers.append(ctx.name)

    threads = [threading.Thread(target=worker, args=(c,)) for c in contexts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1
    assert len(losers) == 9
    assert ledger.owner_of(_Agg) == winners[0]


def test_chaos_publish_integration_acl_without_translator_blocked() -> None:
    ledger = _OwnershipLedger()
    cmap = ContextMap()
    a = SimpleBoundedContext("a", context_map=cmap, ledger=ledger)
    b = SimpleBoundedContext("b", context_map=cmap, ledger=ledger)
    with pytest.raises(CrossContextLeakError):
        a.publish_integration(b, REL_ACL)
    # No partial edge was published on the map.
    assert not cmap.has_relationship("a", "b")


def test_chaos_forward_without_any_translator_raises() -> None:
    ledger = _OwnershipLedger()
    cmap = ContextMap()
    a = SimpleBoundedContext("a", context_map=cmap, ledger=ledger)
    b = SimpleBoundedContext("b", context_map=cmap, ledger=ledger)
    with pytest.raises(CrossContextLeakError):
        a.forward(b, {"payload": 1})


def test_chaos_self_integration_rejected() -> None:
    cmap = ContextMap()
    with pytest.raises(UnmappedIntegrationError):
        cmap.add_relationship("same", "same", REL_PARTNERSHIP)


def test_chaos_large_context_map_remains_queryable() -> None:
    cmap = ContextMap()
    for i in range(1000):
        cmap.add_relationship(f"u{i}", f"d{i}", REL_PARTNERSHIP)
    integrations = list(cmap.integrations())
    assert len(integrations) == 1000
    assert cmap.relationship("u500", "d500") == REL_PARTNERSHIP


def test_chaos_translator_replaced_mid_flight() -> None:
    ledger = _OwnershipLedger()
    cmap = ContextMap()
    a = SimpleBoundedContext("a", context_map=cmap, ledger=ledger)
    b = SimpleBoundedContext("b", context_map=cmap, ledger=ledger)
    acl1 = NoopAntiCorruptionLayer()
    acl2 = NoopAntiCorruptionLayer()
    a.publish_integration(b, REL_CUSTOMER_SUPPLIER, translator=acl1)
    a.register_translator("b", acl2)  # hot-swap
    assert a.translator_to(b) is acl2
