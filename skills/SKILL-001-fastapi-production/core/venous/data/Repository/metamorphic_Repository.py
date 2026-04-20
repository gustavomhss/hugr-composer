"""Metamorphic + differential tests for Repository.

Algebraic properties:
- add(e); get(e.id) == e  (insertion retrievability)
- add(e); remove(e); get(e.id) is None  (round-trip zero)
- find(AlwaysTrue) yields exactly the tracked set
- register_finder is idempotent under overwrite with the same callable
- differential: repo with and without IdentityMap returns the same `get` value
  for a stored root (map only affects identity, not the value shape).
"""

from __future__ import annotations

from dataclasses import dataclass

from Repository import ConcreteRepository, InMemoryIdentityMap


@dataclass
class Widget:
    id: int
    label: str = ""


class _StubUoW:
    def register_new(self, obj: object) -> None: ...
    def register_dirty(self, obj: object) -> None: ...
    def register_removed(self, obj: object) -> None: ...


class AlwaysTrue:
    def is_satisfied_by(self, entity: object) -> bool:
        return True


def test_metamorphic_add_then_get_returns_same_reference() -> None:
    uow = _StubUoW()
    repo: ConcreteRepository[Widget] = ConcreteRepository(Widget, uow, shard="meta-1")
    try:
        for i in range(20):
            w = Widget(id=i)
            repo.add(w)
            assert repo.get(i) is w
    finally:
        repo.close()


def test_metamorphic_add_then_remove_yields_none() -> None:
    uow = _StubUoW()
    repo: ConcreteRepository[Widget] = ConcreteRepository(Widget, uow, shard="meta-2")
    try:
        w = Widget(id=7)
        repo.add(w)
        repo.remove(w)
        assert repo.get(7) is None
    finally:
        repo.close()


def test_metamorphic_find_covers_tracked_set() -> None:
    uow = _StubUoW()
    repo: ConcreteRepository[Widget] = ConcreteRepository(Widget, uow, shard="meta-3")
    try:
        items = [Widget(id=i) for i in range(5)]
        for it in items:
            repo.add(it)
        found_ids = {w.id for w in repo.find(AlwaysTrue())}
        assert found_ids == {0, 1, 2, 3, 4}
    finally:
        repo.close()


def test_metamorphic_register_finder_is_overwritable() -> None:
    uow = _StubUoW()
    repo: ConcreteRepository[Widget] = ConcreteRepository(Widget, uow, shard="meta-4")
    try:
        repo.register_finder("empty", lambda _: [])
        repo.register_finder("empty", lambda _: [])
        assert list(repo.find("empty")) == []
    finally:
        repo.close()


def test_differential_identity_map_vs_no_map_same_value() -> None:
    uow_a = _StubUoW()
    uow_b = _StubUoW()
    repo_plain: ConcreteRepository[Widget] = ConcreteRepository(
        Widget, uow_a, shard="diff-plain",
    )
    repo_mapped: ConcreteRepository[Widget] = ConcreteRepository(
        Widget, uow_b, identity_map=InMemoryIdentityMap(), shard="diff-mapped",
    )
    try:
        w1 = Widget(id=1, label="A")
        w2 = Widget(id=1, label="A")
        repo_plain.add(w1)
        repo_mapped.add(w2)
        a = repo_plain.get(1)
        b = repo_mapped.get(1)
        assert a is not None and b is not None
        assert a.label == b.label == "A"
    finally:
        repo_plain.close()
        repo_mapped.close()
