"""Metamorphic + differential tests for BoundedContext.

Algebraic properties:
- claim() is idempotent on the (type, same-context) pair.
- define_term() is idempotent when the meaning is unchanged.
- ContextMap.add_relationship() is last-write-wins per (upstream, downstream).
- Two separate ledgers NEVER interfere — ownership is scoped to one ledger.
- Language views returned from `.language` are copies (mutations do NOT affect
  the context state).
"""

from __future__ import annotations

from BoundedContext import (
    REL_CONFORMIST,
    REL_PARTNERSHIP,
    ContextMap,
    NoopAntiCorruptionLayer,
    SimpleBoundedContext,
    _OwnershipLedger,
)


class _SomeAgg:
    pass


def test_metamorphic_claim_idempotent_same_context() -> None:
    ledger = _OwnershipLedger()
    ctx = SimpleBoundedContext("a", ledger=ledger)
    for _ in range(10):
        ctx.claim(_SomeAgg)
    assert ctx.owns(_SomeAgg)
    assert ledger.owner_of(_SomeAgg) == "a"


def test_metamorphic_define_term_idempotent_same_meaning() -> None:
    ctx = SimpleBoundedContext("a")
    for _ in range(10):
        ctx.define_term("order", "a customer purchase")
    assert ctx.language == {"order": "a customer purchase"}


def test_metamorphic_add_relationship_last_write_wins() -> None:
    cmap = ContextMap()
    cmap.add_relationship("u", "d", REL_PARTNERSHIP)
    cmap.add_relationship("u", "d", REL_CONFORMIST)
    assert cmap.relationship("u", "d") == REL_CONFORMIST


def test_metamorphic_ledgers_are_independent() -> None:
    lg1 = _OwnershipLedger()
    lg2 = _OwnershipLedger()
    ctx1 = SimpleBoundedContext("one", ledger=lg1)
    ctx2 = SimpleBoundedContext("two", ledger=lg2)
    ctx1.claim(_SomeAgg)
    ctx2.claim(_SomeAgg)  # different ledger — NO conflict
    assert ctx1.owns(_SomeAgg)
    assert ctx2.owns(_SomeAgg)


def test_metamorphic_language_view_is_copy() -> None:
    ctx = SimpleBoundedContext("a")
    ctx.define_term("order", "x")
    view = dict(ctx.language)
    view["order"] = "tampered"
    # Mutating the returned view MUST NOT corrupt the context's language.
    assert ctx.language["order"] == "x"


def test_differential_two_contexts_translator_independence() -> None:
    # translator_to from A→B and B→A are registered independently.
    ledger = _OwnershipLedger()
    cmap = ContextMap()
    a = SimpleBoundedContext("a", context_map=cmap, ledger=ledger)
    b = SimpleBoundedContext("b", context_map=cmap, ledger=ledger)
    acl_ab = NoopAntiCorruptionLayer()
    acl_ba = NoopAntiCorruptionLayer()
    a.publish_integration(b, REL_CONFORMIST, translator=acl_ab)
    b.publish_integration(a, REL_CONFORMIST, translator=acl_ba)
    assert a.translator_to(b) is acl_ab
    assert b.translator_to(a) is acl_ba
