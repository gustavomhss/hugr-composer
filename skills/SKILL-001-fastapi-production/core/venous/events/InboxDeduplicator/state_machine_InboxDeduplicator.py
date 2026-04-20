"""Hypothesis state-machine exploration of InboxDeduplicator lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from InboxDeduplicator import (
    InboxDeduplicatorInvariantError,
    InMemoryInboxDeduplicator,
)


class InboxMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.inbox = InMemoryInboxDeduplicator()
        self.scope = None
        # Ground-truth model of committed pairs.
        self.committed: set[tuple[str, str]] = set()
        # Pairs staged in the currently-open scope (if any).
        self.staged: set[tuple[str, str]] = set()

    @rule()
    def begin_op(self) -> None:
        if self.scope is not None:
            try:
                self.inbox.begin()
                raise AssertionError("nested begin accepted")
            except InboxDeduplicatorInvariantError:
                return
        self.scope = self.inbox.begin()
        self.staged.clear()

    @rule(
        mid=st.integers(min_value=0, max_value=4),
        cons=st.integers(min_value=0, max_value=2),
    )
    def record_op(self, mid: int, cons: int) -> None:
        pair = (f"m{mid}", f"c{cons}")
        if self.scope is None:
            try:
                self.inbox.record(*pair)
                raise AssertionError("record outside txn accepted")
            except InboxDeduplicatorInvariantError:
                return
        if pair in self.committed or pair in self.staged:
            try:
                self.inbox.record(*pair)
                raise AssertionError("duplicate record accepted")
            except InboxDeduplicatorInvariantError:
                return
        self.inbox.record(*pair)
        self.staged.add(pair)

    @rule(
        mid=st.integers(min_value=0, max_value=4),
        cons=st.integers(min_value=0, max_value=2),
    )
    def seen_op(self, mid: int, cons: int) -> None:
        if not hasattr(self, "inbox"):
            return
        pair = (f"m{mid}", f"c{cons}")
        observed = self.inbox.seen(*pair)
        expected = pair in self.committed or (
            self.scope is not None and pair in self.staged
        )
        assert observed == expected, (
            f"seen({pair}) = {observed} but model expected {expected}"
        )

    @rule()
    def commit_op(self) -> None:
        if self.scope is None:
            return
        self.scope.commit()
        self.committed |= self.staged
        self.staged.clear()
        self.scope = None

    @rule()
    def rollback_op(self) -> None:
        if self.scope is None:
            return
        self.scope.rollback()
        self.staged.clear()
        self.scope = None

    @invariant()
    def store_matches_committed_keys(self) -> None:
        if not hasattr(self, "inbox"):
            return
        stored = {
            (r["message_id"], r["consumer"])
            for r in self.inbox.store_snapshot
        }
        assert stored == self.committed

    @invariant()
    def seen_is_monotone_for_committed(self) -> None:
        if not hasattr(self, "inbox"):
            return
        for pair in self.committed:
            assert self.inbox.seen(*pair) is True, (
                f"committed pair {pair} not seen by inbox"
            )

    @invariant()
    def no_active_txn_after_commit_or_rollback(self) -> None:
        if not hasattr(self, "inbox"):
            return
        if self.scope is None:
            cur = self.inbox.current_transaction
            assert cur is None or cur.state != "active"


# Hypothesis hook
TestInboxMachine = InboxMachine.TestCase
