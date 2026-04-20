"""Behavioral end-to-end scenarios for UnitOfWork — proves invariants at runtime."""

from __future__ import annotations

import pytest

from UnitOfWork import (
    EnlistingRepository,
    InMemoryUnitOfWork,
    UnitOfWorkInvariantError,
)


def test_scenario_transfer_commits_atomically() -> None:
    flushed: list[tuple[int, int, int]] = []

    def flush(new: list[object], dirty: list[object], removed: list[object]) -> None:
        flushed.append((len(new), len(dirty), len(removed)))

    uow = InMemoryUnitOfWork(flush_fn=flush)
    src = {"balance": 100}
    dst = {"balance": 0}
    with uow as u:
        src["balance"] -= 40
        dst["balance"] += 40
        u.register_dirty(src)
        u.register_dirty(dst)
        u.commit()
    assert flushed == [(0, 2, 0)]
    assert src["balance"] == 60
    assert dst["balance"] == 40


def test_scenario_flush_error_rolls_back_both_rows() -> None:
    def fail(n: list[object], d: list[object], r: list[object]) -> None:
        raise RuntimeError("db unavailable")

    uow = InMemoryUnitOfWork(flush_fn=fail)
    with pytest.raises(RuntimeError):
        with uow as u:
            u.register_dirty({"id": 1})
            u.register_dirty({"id": 2})
            u.commit()
    assert uow.state == "rolled_back"


def test_scenario_exception_inside_unit_triggers_rollback() -> None:
    uow = InMemoryUnitOfWork()
    with pytest.raises(ZeroDivisionError):
        with uow as u:
            u.register_new(object())
            _ = 1 / 0
    assert uow.state == "rolled_back"


def test_scenario_repository_enlistment_observable_in_unit() -> None:
    uow = InMemoryUnitOfWork()
    repo = EnlistingRepository(uow)
    with uow as u:
        entity = object()
        repo.add(entity)
        assert entity in u.new_snapshot
        u.commit()


def test_scenario_hook_registration_fires_in_order() -> None:
    fired: list[str] = []
    uow = InMemoryUnitOfWork()
    uow.register_before_commit(lambda _u: fired.append("before"))
    uow.register_on_commit(lambda _u: fired.append("on"))
    uow.register_after_commit(lambda _u: fired.append("after"))
    with uow as u:
        u.register_new(object())
        u.commit()
    assert fired == ["before", "on", "after"]


def test_scenario_reuse_after_commit_is_forbidden() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        u.register_new(object())
        u.commit()
    with pytest.raises(UnitOfWorkInvariantError):
        with uow:
            pass
