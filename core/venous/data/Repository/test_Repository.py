"""Unit tests for Repository — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterator

import pytest

from Repository import (
    ConcreteRepository,
    InMemoryIdentityMap,
    RepositoryInvariantError,
)


# ---------------------------------------------------------------------------
# Test fixtures: a pair of aggregate-root / child-entity classes + a stub UoW.
# ---------------------------------------------------------------------------
@dataclass
class Account:
    id: int
    balance: int = 0


@dataclass
class LineItem:
    """A CHILD entity — REPO-INV-01 forbids exposing this via Account's repo."""

    id: int


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


class BalanceAbove:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold

    def is_satisfied_by(self, entity: object) -> bool:
        return isinstance(entity, Account) and entity.balance > self.threshold


@pytest.fixture
def uow() -> StubUoW:
    return StubUoW()


@pytest.fixture
def repo(uow: StubUoW) -> Iterator[ConcreteRepository[Account]]:
    r: ConcreteRepository[Account] = ConcreteRepository(Account, uow)
    yield r
    r.close()


# ---------------------------------------------------------------------------
# REPO_INV_01 — aggregate-root-only surface
# ---------------------------------------------------------------------------
def test_inv_aggregate_root_only_confirms(repo: ConcreteRepository[Account]) -> None:
    a = Account(id=1, balance=100)
    repo.add(a)
    assert repo.get(1) is a


def test_inv_aggregate_root_only_prevents(repo: ConcreteRepository[Account]) -> None:
    child = LineItem(id=42)
    with pytest.raises(RepositoryInvariantError):
        repo.add(child)  # type: ignore[arg-type] — REPO-INV-01: child entity MUST be rejected.


def test_inv_aggregate_root_only_under_failure(repo: ConcreteRepository[Account]) -> None:
    # Under 100 mixed-type attacks, not a single child entity leaks through.
    rejected = 0
    for i in range(100):
        try:
            repo.add(LineItem(id=i))  # type: ignore[arg-type] — REPO-INV-01: child entity MUST be rejected.
        except RepositoryInvariantError:
            rejected += 1
    assert rejected == 100
    assert repo.tracked_ids == ()


# ---------------------------------------------------------------------------
# REPO_INV_02 — Specification / named-finder surface
# ---------------------------------------------------------------------------
def test_inv_specification_surface_confirms(repo: ConcreteRepository[Account]) -> None:
    for i in range(5):
        repo.add(Account(id=i, balance=i * 10))
    out = list(repo.find(BalanceAbove(threshold=20)))
    assert {a.id for a in out} == {3, 4}


def test_inv_specification_surface_prevents(repo: ConcreteRepository[Account]) -> None:
    # Raw SQL-looking strings MUST NOT be accepted as a query surface.
    with pytest.raises(RepositoryInvariantError):
        list(repo.find("SELECT * FROM accounts WHERE balance > 10"))
    with pytest.raises(RepositoryInvariantError):
        list(repo.find(42))  # non-Specification, non-string, non-finder


def test_inv_specification_surface_under_failure(repo: ConcreteRepository[Account]) -> None:
    # Registering a named finder and then invoking it keeps the surface clean.
    repo.add(Account(id=1, balance=50))
    repo.add(Account(id=2, balance=500))
    repo.register_finder("rich", lambda _: [a for a in (repo.get(1), repo.get(2)) if a and a.balance >= 100])
    out = list(repo.find("rich"))
    assert [a.id for a in out] == [2]


# ---------------------------------------------------------------------------
# REPO_INV_03 — one repository per aggregate root
# ---------------------------------------------------------------------------
def test_inv_singleton_root_confirms(uow: StubUoW) -> None:
    r: ConcreteRepository[Account] = ConcreteRepository(Account, uow, shard="isolated-A")
    try:
        assert r.root_type is Account
    finally:
        r.close()


def test_inv_singleton_root_prevents(uow: StubUoW) -> None:
    r1: ConcreteRepository[Account] = ConcreteRepository(Account, uow, shard="isolated-B")
    try:
        with pytest.raises(RepositoryInvariantError):
            ConcreteRepository(Account, uow, shard="isolated-B")
    finally:
        r1.close()


def test_inv_singleton_root_under_failure(uow: StubUoW) -> None:
    # Even under concurrent construction attempts, only one wins.
    winners: list[ConcreteRepository[Account]] = []
    losers: list[BaseException] = []
    lock = threading.Lock()

    def build() -> None:
        try:
            r: ConcreteRepository[Account] = ConcreteRepository(Account, uow, shard="race-shard")
            with lock:
                winners.append(r)
        except RepositoryInvariantError as exc:
            with lock:
                losers.append(exc)

    ts = [threading.Thread(target=build) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    try:
        assert len(winners) == 1
        assert len(losers) == 11
    finally:
        for r in winners:
            r.close()


# ---------------------------------------------------------------------------
# REPO_INV_04 — mutations enlist with the UnitOfWork
# ---------------------------------------------------------------------------
def test_inv_enlist_mutations_confirms(repo: ConcreteRepository[Account], uow: StubUoW) -> None:
    a = Account(id=1)
    repo.add(a)
    assert uow.new == [a]
    repo.mark_dirty(a)
    assert uow.dirty == [a]
    repo.remove(a)
    assert uow.removed == [a]


def test_inv_enlist_mutations_prevents(repo: ConcreteRepository[Account]) -> None:
    with pytest.raises(RepositoryInvariantError):
        repo.direct_write(Account(id=2))


def test_inv_enlist_mutations_under_failure(repo: ConcreteRepository[Account], uow: StubUoW) -> None:
    # Every add enlists exactly once; 500 concurrent adds → 500 enlistments, no drops.
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(start: int) -> None:
        try:
            for i in range(start, start + 50):
                repo.add(Account(id=i))
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(k * 50,)) for k in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert len(uow.new) == 500
    assert len(repo.tracked_ids) == 500


# ---------------------------------------------------------------------------
# REPO_INV_05 — IdentityMap consulted before storage
# ---------------------------------------------------------------------------
def test_inv_identity_map_first_confirms(uow: StubUoW) -> None:
    idmap = InMemoryIdentityMap()
    r: ConcreteRepository[Account] = ConcreteRepository(
        Account, uow, identity_map=idmap, shard="idmap-A",
    )
    try:
        a = Account(id=7, balance=10)
        r.add(a)
        # The cached reference must win over any fresh load.
        assert r.get(7) is a
        assert idmap.get(Account, 7) is a
    finally:
        r.close()


def test_inv_identity_map_first_prevents(uow: StubUoW) -> None:
    idmap = InMemoryIdentityMap()
    loads = {"count": 0}

    def loader(id_: object) -> Account | None:
        loads["count"] += 1
        return Account(id=id_ if isinstance(id_, int) else 0, balance=999)

    r: ConcreteRepository[Account] = ConcreteRepository(
        Account, uow, identity_map=idmap, load_fn=loader, shard="idmap-B",
    )
    try:
        cached = Account(id=1, balance=1)
        idmap.put(Account, 1, cached)
        got = r.get(1)
        assert got is cached  # REPO-INV-05: never materialise a fresh copy.
        assert loads["count"] == 0  # loader MUST NOT run when the map is warm.
    finally:
        r.close()


def test_inv_identity_map_first_under_failure(uow: StubUoW) -> None:
    idmap = InMemoryIdentityMap()

    def bad_loader(id_: object) -> Account | None:
        return Account(id=id_ if isinstance(id_, int) else 0, balance=500)

    r: ConcreteRepository[Account] = ConcreteRepository(
        Account, uow, identity_map=idmap, load_fn=bad_loader, shard="idmap-C",
    )
    try:
        a = Account(id=3)
        r.add(a)
        for _ in range(100):
            assert r.get(3) is a  # Repeated reads must keep returning the cached root.
    finally:
        r.close()
