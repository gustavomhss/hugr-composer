"""Hypothesis state-machine exploration of UnitOfWork lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from UnitOfWork import InMemoryUnitOfWork, UnitOfWorkInvariantError


class UnitOfWorkMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.uow = InMemoryUnitOfWork()
        self.registered: set[int] = set()
        self.terminal = False

    @rule(tag=st.integers(min_value=0, max_value=9))
    def register_new_op(self, tag: int) -> None:
        obj = (tag,)
        oid = id(obj)
        if self.terminal:
            try:
                self.uow.register_new(obj)
                raise AssertionError("terminal unit accepted registration")
            except UnitOfWorkInvariantError:
                return
        if oid in self.registered:
            try:
                self.uow.register_new(obj)
                raise AssertionError("duplicate registration accepted")
            except UnitOfWorkInvariantError:
                return
        self.uow.register_new(obj)
        self.registered.add(oid)

    @rule()
    def commit_op(self) -> None:
        if self.terminal:
            try:
                self.uow.commit()
                raise AssertionError("terminal unit accepted commit")
            except UnitOfWorkInvariantError:
                return
        self.uow.commit()
        self.terminal = True

    @rule()
    def rollback_op(self) -> None:
        self.uow.rollback()
        if not self.terminal:
            self.terminal = True

    @invariant()
    def buckets_disjoint(self) -> None:
        if not hasattr(self, "uow"):
            return
        new_ids = {id(o) for o in self.uow.new_snapshot}
        dirty_ids = {id(o) for o in self.uow.dirty_snapshot}
        removed_ids = {id(o) for o in self.uow.removed_snapshot}
        assert new_ids.isdisjoint(dirty_ids)
        assert new_ids.isdisjoint(removed_ids)
        assert dirty_ids.isdisjoint(removed_ids)

    @invariant()
    def terminal_is_empty(self) -> None:
        if not hasattr(self, "uow"):
            return
        if self.uow.state == "rolled_back":
            assert self.uow.new_snapshot == ()
            assert self.uow.dirty_snapshot == ()
            assert self.uow.removed_snapshot == ()


# Hypothesis hook
TestUnitOfWorkMachine = UnitOfWorkMachine.TestCase
