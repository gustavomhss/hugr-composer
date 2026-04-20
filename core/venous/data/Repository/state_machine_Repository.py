"""Hypothesis state-machine exploration of Repository lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from Repository import ConcreteRepository, RepositoryInvariantError


@dataclass
class Thing:
    id: int


class _NullUoW:
    def register_new(self, obj: object) -> None: ...
    def register_dirty(self, obj: object) -> None: ...
    def register_removed(self, obj: object) -> None: ...


class RepositoryMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.shard = f"sm-{uuid.uuid4().hex[:8]}"
        self.repo: ConcreteRepository[Thing] = ConcreteRepository(
            Thing, _NullUoW(), shard=self.shard,
        )
        self.live: set[int] = set()
        self.removed: set[int] = set()

    def teardown(self) -> None:
        if hasattr(self, "repo"):
            self.repo.close()

    @rule(i=st.integers(min_value=0, max_value=9))
    def add_op(self, i: int) -> None:
        if not hasattr(self, "repo"):
            return
        if i in self.live:
            try:
                self.repo.add(Thing(id=i))
                raise AssertionError("duplicate id accepted")
            except RepositoryInvariantError:
                return
        self.repo.add(Thing(id=i))
        self.live.add(i)
        self.removed.discard(i)

    @rule(i=st.integers(min_value=0, max_value=9))
    def remove_op(self, i: int) -> None:
        if not hasattr(self, "repo"):
            return
        if i not in self.live:
            return
        found = self.repo.get(i)
        if found is not None:
            self.repo.remove(found)
            self.live.discard(i)
            self.removed.add(i)

    @rule(i=st.integers(min_value=0, max_value=9))
    def get_op(self, i: int) -> None:
        if not hasattr(self, "repo"):
            return
        got = self.repo.get(i)
        if i in self.live:
            assert got is not None
            assert got.id == i
        else:
            assert got is None

    @invariant()
    def tracked_matches_live(self) -> None:
        if not hasattr(self, "repo"):
            return
        tracked = set(self.repo.tracked_ids)
        assert tracked == self.live


TestRepositoryMachine = RepositoryMachine.TestCase
