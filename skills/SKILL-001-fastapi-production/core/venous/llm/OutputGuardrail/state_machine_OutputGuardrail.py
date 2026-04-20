"""Hypothesis state-machine tests for the VerdictLedger.

Explores the reachable states of `VerdictLedger` under arbitrary interleavings
of record / clear / query operations. The shadow model is a plain Python list
of (guardrail_name, action) pairs; the ledger MUST agree with it on:

- size()                      — length of the shadow
- entries()                   — length + per-name attribution
- entries_for(name)           — subset of shadow where the name matches
- clear()                     — resets to empty

This exercises GUARD-INV-05 across arbitrary operation sequences.
"""

from __future__ import annotations

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from hypothesis.strategies import sampled_from, text

from OutputGuardrail import Verdict, VerdictLedger

_NAMES = ("alpha", "beta", "gamma", "safety", "policy.v1")
_ACTIONS = ("pass", "block")  # rewrite requires replacement so we exercise it separately below


class LedgerModel(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.ledger = VerdictLedger()
        self.shadow: list[tuple[str, str]] = []

    @rule(
        name=sampled_from(_NAMES),
        action=sampled_from(_ACTIONS),
        reason_suffix=text(alphabet="abcxyz ", min_size=0, max_size=6),
    )
    def record_pass_or_block(self, name: str, action: str, reason_suffix: str) -> None:
        v = Verdict(action=action, reason=f"reason{reason_suffix}".strip() or "r")  # type: ignore[arg-type] — constrained by _ACTIONS.
        self.ledger.record(name, v)
        self.shadow.append((name, action))

    @rule(name=sampled_from(_NAMES), suffix=text(alphabet="xyz", min_size=0, max_size=4))
    def record_rewrite(self, name: str, suffix: str) -> None:
        v = Verdict(action="rewrite", reason="r", replacement=f"new{suffix}")
        self.ledger.record(name, v)
        self.shadow.append((name, "rewrite"))

    @rule()
    def clear(self) -> None:
        self.ledger.clear()
        self.shadow.clear()

    @invariant()
    def size_matches_shadow(self) -> None:
        assert self.ledger.size() == len(self.shadow)

    @invariant()
    def entries_match_shadow_shape(self) -> None:
        entries = self.ledger.entries()
        assert len(entries) == len(self.shadow)
        # Each entry is (name, Verdict) and the order MUST match the shadow append order.
        for (name_exp, action_exp), (name_got, v_got) in zip(self.shadow, entries, strict=True):
            assert name_got == name_exp
            assert v_got.action == action_exp

    @invariant()
    def entries_for_name_is_subset(self) -> None:
        for target in _NAMES:
            got = self.ledger.entries_for(target)
            want_count = sum(1 for n, _ in self.shadow if n == target)
            assert len(got) == want_count


TestLedger = LedgerModel.TestCase
TestLedger.settings = settings(max_examples=50, deadline=None)
