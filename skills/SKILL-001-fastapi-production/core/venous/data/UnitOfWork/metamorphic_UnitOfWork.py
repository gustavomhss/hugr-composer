"""Metamorphic + differential tests for UnitOfWork.

Algebraic properties:
- rollback() is idempotent after terminal
- commit order of buckets is always (new, dirty, removed)
- registering N objects then rolling back leaves buckets empty
- registering then committing preserves insertion order
"""

from __future__ import annotations

from UnitOfWork import InMemoryUnitOfWork


def test_metamorphic_rollback_idempotent() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        u.register_new(object())
    assert uow.state == "rolled_back"
    for _ in range(10):
        uow.rollback()
    assert uow.state == "rolled_back"


def test_metamorphic_flush_order_new_dirty_removed() -> None:
    seen: list[str] = []

    def flush(n: list[object], d: list[object], r: list[object]) -> None:
        for _ in n:
            seen.append("new")
        for _ in d:
            seen.append("dirty")
        for _ in r:
            seen.append("removed")

    uow = InMemoryUnitOfWork(flush_fn=flush)
    with uow as u:
        u.register_removed(object())
        u.register_dirty(object())
        u.register_new(object())
        u.commit()
    assert seen == ["new", "dirty", "removed"]


def test_metamorphic_rollback_empties_buckets() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        for _ in range(5):
            u.register_new(object())
    assert uow.new_snapshot == ()


def test_metamorphic_insertion_order_preserved() -> None:
    captured: list[object] = []

    def flush(n: list[object], d: list[object], r: list[object]) -> None:
        captured.extend(n)

    uow = InMemoryUnitOfWork(flush_fn=flush)
    items = [object() for _ in range(5)]
    with uow as u:
        for it in items:
            u.register_new(it)
        u.commit()
    assert captured == items


def test_differential_terminal_state_after_exception_vs_rollback() -> None:
    # Both paths MUST reach state == "rolled_back" with empty buckets.
    uow_a = InMemoryUnitOfWork()
    try:
        with uow_a as u:
            u.register_new(object())
            raise RuntimeError("x")
    except RuntimeError:
        pass

    uow_b = InMemoryUnitOfWork()
    with uow_b as u:
        u.register_new(object())
        u.rollback()

    assert uow_a.state == uow_b.state == "rolled_back"
    assert uow_a.new_snapshot == uow_b.new_snapshot == ()
