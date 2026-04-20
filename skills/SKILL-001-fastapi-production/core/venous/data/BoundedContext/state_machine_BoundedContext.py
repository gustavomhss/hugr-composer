"""Hypothesis state-machine exploration of BoundedContext + ContextMap."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from BoundedContext import (
    CANONICAL_RELATIONSHIPS,
    ContextMap,
    SharedOwnershipError,
    SimpleBoundedContext,
    UbiquitousLanguageConflictError,
    UnmappedIntegrationError,
    _OwnershipLedger,
)


class _AggA:
    pass


class _AggB:
    pass


_AGG_TYPES = (_AggA, _AggB)
_REL_KINDS = tuple(sorted(CANONICAL_RELATIONSHIPS))


class BoundedContextMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.ledger = _OwnershipLedger()
        self.cmap = ContextMap()
        self.ctx_a = SimpleBoundedContext("a", context_map=self.cmap, ledger=self.ledger)
        self.ctx_b = SimpleBoundedContext("b", context_map=self.cmap, ledger=self.ledger)
        self.owner_expected: dict[type, str] = {}
        self.term_meanings: dict[tuple[str, str], str] = {}

    @rule(
        ctx_name=st.sampled_from(("a", "b")),
        agg_idx=st.integers(min_value=0, max_value=len(_AGG_TYPES) - 1),
    )
    def claim_op(self, ctx_name: str, agg_idx: int) -> None:
        ctx = self.ctx_a if ctx_name == "a" else self.ctx_b
        agg = _AGG_TYPES[agg_idx]
        owner = self.owner_expected.get(agg)
        if owner is None or owner == ctx_name:
            ctx.claim(agg)
            self.owner_expected[agg] = ctx_name
        else:
            try:
                ctx.claim(agg)
                raise AssertionError("shared ownership unexpectedly accepted")
            except SharedOwnershipError:
                return

    @rule(
        ctx_name=st.sampled_from(("a", "b")),
        term=st.sampled_from(("order", "invoice", "shipment")),
        meaning=st.sampled_from(("meaning1", "meaning2")),
    )
    def define_term_op(self, ctx_name: str, term: str, meaning: str) -> None:
        ctx = self.ctx_a if ctx_name == "a" else self.ctx_b
        key = (ctx_name, term)
        existing = self.term_meanings.get(key)
        if existing is None or existing == meaning:
            ctx.define_term(term, meaning)
            self.term_meanings[key] = meaning
        else:
            try:
                ctx.define_term(term, meaning)
                raise AssertionError("language conflict unexpectedly accepted")
            except UbiquitousLanguageConflictError:
                return

    @rule(kind_idx=st.integers(min_value=0, max_value=len(_REL_KINDS) - 1))
    def publish_partnership_op(self, kind_idx: int) -> None:
        kind = _REL_KINDS[kind_idx]
        # Use Partnership / Open Host which do NOT need a translator to keep
        # the state-machine rules simple and still exercise the ContextMap.
        if kind not in ("Partnership", "Open Host"):
            return
        self.cmap.add_relationship("a", "b", kind)

    @invariant()
    def ownership_agrees_with_ledger(self) -> None:
        if not hasattr(self, "ledger"):
            return
        for agg, expected in self.owner_expected.items():
            assert self.ledger.owner_of(agg) == expected

    @invariant()
    def unmapped_lookups_raise(self) -> None:
        if not hasattr(self, "cmap"):
            return
        # Looking up an edge that was never published must raise.
        if not self.cmap.has_relationship("ghost", "phantom"):
            try:
                self.cmap.relationship("ghost", "phantom")
                raise AssertionError("unmapped integration silently accepted")
            except UnmappedIntegrationError:
                return

    @invariant()
    def canonical_kinds_only(self) -> None:
        if not hasattr(self, "cmap"):
            return
        for _u, _d, k in self.cmap.integrations():
            assert k in CANONICAL_RELATIONSHIPS


# Hypothesis hook
TestBoundedContextMachine = BoundedContextMachine.TestCase
