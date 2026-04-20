"""Chaos / game-day tests for Repository.

Simulates boundary violations, concurrent registrations, loader crashes, and
adversarial spec inputs to confirm the Repository never leaks bypass writes
or stale copies.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest

from Repository import (
    ConcreteRepository,
    InMemoryIdentityMap,
    RepositoryInvariantError,
)


@dataclass
class Customer:
    id: int
    name: str = ""


class _StubUoW:
    def __init__(self) -> None:
        self.counts = {"new": 0, "dirty": 0, "removed": 0}

    def register_new(self, obj: object) -> None:
        self.counts["new"] += 1

    def register_dirty(self, obj: object) -> None:
        self.counts["dirty"] += 1

    def register_removed(self, obj: object) -> None:
        self.counts["removed"] += 1


class MalformedSpec:
    """Not a Specification — has no is_satisfied_by."""


def test_chaos_malformed_spec_rejected() -> None:
    repo: ConcreteRepository[Customer] = ConcreteRepository(
        Customer, _StubUoW(), shard="chaos-1",
    )
    try:
        with pytest.raises(RepositoryInvariantError):
            list(repo.find(MalformedSpec()))
    finally:
        repo.close()


def test_chaos_loader_returning_wrong_type_raises() -> None:
    def bad_loader(id_: object) -> object:
        return "not-a-customer"

    repo: ConcreteRepository[Customer] = ConcreteRepository(
        Customer,
        _StubUoW(),
        load_fn=bad_loader,  # type: ignore[arg-type] — REPO-INV-01: loader output type audited by the Repository.
        shard="chaos-2",
    )
    try:
        with pytest.raises(RepositoryInvariantError):
            repo.get(1)
    finally:
        repo.close()


def test_chaos_concurrent_add_remove_leaves_consistent_state() -> None:
    uow = _StubUoW()
    repo: ConcreteRepository[Customer] = ConcreteRepository(Customer, uow, shard="chaos-3")
    try:
        customers = [Customer(id=i) for i in range(200)]

        def writer(c: Customer) -> None:
            repo.add(c)

        def remover(c: Customer) -> None:
            try:
                repo.remove(c)
            except RepositoryInvariantError:
                pass

        writers = [threading.Thread(target=writer, args=(c,)) for c in customers]
        for t in writers:
            t.start()
        for t in writers:
            t.join()
        assert uow.counts["new"] == 200
        removers = [threading.Thread(target=remover, args=(c,)) for c in customers]
        for t in removers:
            t.start()
        for t in removers:
            t.join()
        assert repo.tracked_ids == ()
    finally:
        repo.close()


def test_chaos_duplicate_repo_rejected_under_storm() -> None:
    uow = _StubUoW()
    first: ConcreteRepository[Customer] = ConcreteRepository(
        Customer, uow, shard="chaos-4",
    )
    try:
        failures = 0
        for _ in range(50):
            try:
                ConcreteRepository(Customer, uow, shard="chaos-4")
            except RepositoryInvariantError:
                failures += 1
        assert failures == 50
    finally:
        first.close()


def test_chaos_entity_without_id_rejected() -> None:
    repo: ConcreteRepository[Customer] = ConcreteRepository(
        Customer, _StubUoW(), shard="chaos-5",
    )
    try:
        broken = Customer(id=0)
        broken.id = None  # type: ignore[assignment] — REPO-INV-01: synthetic missing id drives the reject path.
        with pytest.raises(RepositoryInvariantError):
            repo.add(broken)
    finally:
        repo.close()


def test_chaos_identity_map_returns_wrong_type_raises() -> None:
    idmap = InMemoryIdentityMap()
    idmap.put(Customer, 1, "not-a-customer")
    repo: ConcreteRepository[Customer] = ConcreteRepository(
        Customer, _StubUoW(), identity_map=idmap, shard="chaos-6",
    )
    try:
        with pytest.raises(RepositoryInvariantError):
            repo.get(1)
    finally:
        repo.close()


def test_chaos_find_empty_collection_yields_empty() -> None:
    class Spec:
        def is_satisfied_by(self, entity: object) -> bool:
            return True

    repo: ConcreteRepository[Customer] = ConcreteRepository(
        Customer, _StubUoW(), shard="chaos-7",
    )
    try:
        assert list(repo.find(Spec())) == []
    finally:
        repo.close()
