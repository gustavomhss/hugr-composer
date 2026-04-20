"""Hypothesis state-machine exploration of IdentityMap lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from IdentityMap import IdentityMapInvariantError, InMemoryIdentityMap


@dataclass
class Entity:
    id: int


class IdentityMapMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.imap = InMemoryIdentityMap()
        # model: id -> canonical reference we expect to see on get
        self.canonical: dict[int, Entity] = {}
        self.disposed = False

    @rule(eid=st.integers(min_value=0, max_value=9))
    def add_new(self, eid: int) -> None:
        if self.disposed:
            return
        if eid in self.canonical:
            # Attempting to add a DIFFERENT instance MUST be rejected.
            attacker = Entity(id=eid)
            try:
                self.imap.add(attacker)
                raise AssertionError("duplicate-identity add was accepted")
            except IdentityMapInvariantError:
                return
        e = Entity(id=eid)
        self.imap.add(e)
        self.canonical[eid] = e

    @rule(eid=st.integers(min_value=0, max_value=9))
    def readd_same_ref(self, eid: int) -> None:
        if self.disposed or eid not in self.canonical:
            return
        # Re-adding the SAME reference MUST be idempotent.
        self.imap.add(self.canonical[eid])

    @rule(eid=st.integers(min_value=0, max_value=9))
    def get_op(self, eid: int) -> None:
        if self.disposed:
            return
        ref = self.imap.get(Entity, eid)
        if eid in self.canonical:
            assert ref is self.canonical[eid]
        else:
            assert ref is None

    @rule(eid=st.integers(min_value=0, max_value=9))
    def remove_op(self, eid: int) -> None:
        if self.disposed:
            return
        self.imap.remove(Entity, eid)
        self.canonical.pop(eid, None)

    @rule(eid=st.integers(min_value=0, max_value=9))
    def contains_op(self, eid: int) -> None:
        if self.disposed:
            return
        assert self.imap.contains(Entity, eid) == (eid in self.canonical)

    @rule()
    def dispose_op(self) -> None:
        self.imap.dispose()
        self.disposed = True
        self.canonical.clear()

    @invariant()
    def same_reference_per_id(self) -> None:
        if not hasattr(self, "imap"):
            return
        if self.disposed:
            assert self.imap.state == "disposed"
            return
        for eid, expected in self.canonical.items():
            got = self.imap.get(Entity, eid)
            assert got is expected

    @invariant()
    def disposed_has_no_entries(self) -> None:
        if not hasattr(self, "imap"):
            return
        if self.disposed:
            # Any catalog method MUST raise.
            try:
                self.imap.get(Entity, 0)
                raise AssertionError("disposed map served a get")
            except IdentityMapInvariantError:
                pass


TestIdentityMapMachine = IdentityMapMachine.TestCase
