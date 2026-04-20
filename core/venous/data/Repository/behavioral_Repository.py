"""Behavioral end-to-end scenarios for Repository — proves invariants at runtime."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from Repository import (
    ConcreteRepository,
    InMemoryIdentityMap,
    RepositoryInvariantError,
)


@dataclass
class Order:
    id: int
    total: int = 0
    status: str = "open"


class StubUoW:
    def __init__(self) -> None:
        self.new: list[object] = []
        self.dirty: list[object] = []
        self.removed: list[object] = []

    def register_new(self, obj: object) -> None:
        self.new.append(obj)

    def register_dirty(self, obj: object) -> None:
        self.dirty.append(obj)

    def register_removed(self, obj: object) -> None:
        self.removed.append(obj)


class StatusEquals:
    def __init__(self, status: str) -> None:
        self.status = status

    def is_satisfied_by(self, entity: object) -> bool:
        return isinstance(entity, Order) and entity.status == self.status


def test_scenario_add_get_remove_round_trip() -> None:
    uow = StubUoW()
    repo: ConcreteRepository[Order] = ConcreteRepository(Order, uow, shard="beh-1")
    try:
        o = Order(id=1, total=100)
        repo.add(o)
        assert repo.get(1) is o
        repo.remove(o)
        assert repo.get(1) is None
        # REPO-INV-04 — every mutation enlisted with the UoW.
        assert uow.new == [o]
        assert uow.removed == [o]
    finally:
        repo.close()


def test_scenario_find_by_specification_over_collection() -> None:
    uow = StubUoW()
    repo: ConcreteRepository[Order] = ConcreteRepository(Order, uow, shard="beh-2")
    try:
        for i in range(6):
            repo.add(Order(id=i, status="closed" if i % 2 == 0 else "open"))
        closed = list(repo.find(StatusEquals("closed")))
        assert {o.id for o in closed} == {0, 2, 4}
    finally:
        repo.close()


def test_scenario_identity_map_hook_prevents_divergence() -> None:
    uow = StubUoW()
    idmap = InMemoryIdentityMap()
    repo: ConcreteRepository[Order] = ConcreteRepository(
        Order, uow, identity_map=idmap, shard="beh-3",
    )
    try:
        o = Order(id=10, total=200)
        repo.add(o)
        # Mutating in place — the identity map returns the SAME object, so
        # subsequent `get` calls observe the mutation (no stale copy).
        o.status = "shipped"
        again = repo.get(10)
        assert again is o
        assert again is not None
        assert again.status == "shipped"
    finally:
        repo.close()


def test_scenario_direct_write_is_always_refused() -> None:
    uow = StubUoW()
    repo: ConcreteRepository[Order] = ConcreteRepository(Order, uow, shard="beh-4")
    try:
        with pytest.raises(RepositoryInvariantError):
            repo.direct_write(Order(id=99))
        # No side effects on tracked state after the refusal.
        assert repo.tracked_ids == ()
        assert uow.new == []
    finally:
        repo.close()


def test_scenario_named_finder_replaces_raw_query_strings() -> None:
    uow = StubUoW()
    repo: ConcreteRepository[Order] = ConcreteRepository(Order, uow, shard="beh-5")
    try:
        repo.add(Order(id=1, total=50))
        repo.add(Order(id=2, total=500))
        repo.register_finder(
            "high_value",
            lambda _: [o for o in (repo.get(1), repo.get(2)) if o and o.total >= 200],
        )
        out = list(repo.find("high_value"))
        assert [o.id for o in out] == [2]
    finally:
        repo.close()


def test_scenario_duplicate_root_rejected_then_released_on_close() -> None:
    uow = StubUoW()
    repo: ConcreteRepository[Order] = ConcreteRepository(Order, uow, shard="beh-6")
    try:
        with pytest.raises(RepositoryInvariantError):
            ConcreteRepository(Order, uow, shard="beh-6")
    finally:
        repo.close()
    # After close() the slot is free again.
    rebuilt: ConcreteRepository[Order] = ConcreteRepository(Order, uow, shard="beh-6")
    rebuilt.close()
