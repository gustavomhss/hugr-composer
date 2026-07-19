"""Unit tests for UnitOfWork — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from UnitOfWork import (
    EnlistingRepository,
    InMemoryUnitOfWork,
    UnitOfWorkInvariantError,
)


# ---------------------------------------------------------------------------
# UOW_INV_01 — atomic commit / rollback on exception
# ---------------------------------------------------------------------------
def test_inv_atomic_commit_confirms() -> None:
    flushed: list[tuple[list[object], list[object], list[object]]] = []

    def flush(n: list[object], d: list[object], r: list[object]) -> None:
        flushed.append((list(n), list(d), list(r)))

    uow = InMemoryUnitOfWork(flush_fn=flush)
    a, b, c = object(), object(), object()
    with uow as u:
        u.register_new(a)
        u.register_dirty(b)
        u.register_removed(c)
        u.commit()
    assert len(flushed) == 1
    assert flushed[0] == ([a], [b], [c])
    assert uow.state == "committed"


def test_inv_atomic_commit_prevents() -> None:
    # Registering after commit must be rejected (terminal unit).
    uow = InMemoryUnitOfWork()
    with uow as u:
        u.commit()
    with pytest.raises(UnitOfWorkInvariantError):
        uow.register_new(object())


def test_inv_atomic_commit_under_failure() -> None:
    def boom(n: list[object], d: list[object], r: list[object]) -> None:
        raise RuntimeError("flush failed")

    uow = InMemoryUnitOfWork(flush_fn=boom)
    obj = object()
    with pytest.raises(RuntimeError), uow as u:
        u.register_new(obj)
        u.commit()
    assert uow.state == "rolled_back"
    assert uow.new_snapshot == ()


# ---------------------------------------------------------------------------
# UOW_INV_02 — no double registration
# ---------------------------------------------------------------------------
def test_inv_single_bucket_confirms() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        obj = object()
        u.register_new(obj)
        assert u.new_snapshot == (obj,)


def test_inv_single_bucket_prevents() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        obj = object()
        u.register_new(obj)
        with pytest.raises(UnitOfWorkInvariantError):
            u.register_dirty(obj)
        with pytest.raises(UnitOfWorkInvariantError):
            u.register_removed(obj)
        with pytest.raises(UnitOfWorkInvariantError):
            u.register_new(obj)


def test_inv_single_bucket_under_failure() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        obj = object()
        u.register_new(obj)
        for _ in range(10):
            try:
                u.register_dirty(obj)
            except UnitOfWorkInvariantError:
                pass
        # Single registration survived the repeated failure attempts.
        assert len(u.new_snapshot) == 1
        u.commit()
    assert uow.state == "committed"


# ---------------------------------------------------------------------------
# UOW_INV_03 — no reuse post-terminal
# ---------------------------------------------------------------------------
def test_inv_no_reuse_confirms() -> None:
    uow = InMemoryUnitOfWork()
    with uow:
        uow.commit()
    assert uow.state == "committed"


def test_inv_no_reuse_prevents() -> None:
    uow = InMemoryUnitOfWork()
    with uow:
        uow.commit()
    with pytest.raises(UnitOfWorkInvariantError), uow:
        pass  # pragma: no cover — __enter__ should have raised


def test_inv_no_reuse_under_failure() -> None:
    uow = InMemoryUnitOfWork()
    try:
        with uow:
            raise ValueError("boom")
    except ValueError:
        pass
    assert uow.state == "rolled_back"
    with pytest.raises(UnitOfWorkInvariantError):
        uow.register_new(object())


# ---------------------------------------------------------------------------
# UOW_INV_04 — context-manager drives rollback on exception
# ---------------------------------------------------------------------------
def test_inv_ctxmgr_rollback_confirms() -> None:
    uow = InMemoryUnitOfWork()
    try:
        with uow as u:
            u.register_new(object())
            raise RuntimeError("injected")
    except RuntimeError:
        pass
    assert uow.state == "rolled_back"
    assert uow.new_snapshot == ()


def test_inv_ctxmgr_rollback_prevents() -> None:
    # Exiting without commit rolls back — nothing is silently persisted.
    flushed: list[int] = []
    uow = InMemoryUnitOfWork(flush_fn=lambda n, d, r: flushed.append(1))
    with uow as u:
        u.register_new(object())
        # No commit!
    assert flushed == []
    assert uow.state == "rolled_back"


def test_inv_ctxmgr_rollback_under_failure() -> None:
    uow = InMemoryUnitOfWork()
    try:
        with uow as u:
            u.register_new(object())
            u.register_dirty(object())
            raise KeyError("db-timeout")
    except KeyError:
        pass
    assert uow.new_snapshot == ()
    assert uow.dirty_snapshot == ()


# ---------------------------------------------------------------------------
# UOW_INV_05 — repository enlistment
# ---------------------------------------------------------------------------
def test_inv_enlist_confirms() -> None:
    uow = InMemoryUnitOfWork()
    repo = EnlistingRepository(uow)
    with uow as u:
        entity = object()
        repo.add(entity)
        assert u.new_snapshot == (entity,)


def test_inv_enlist_prevents() -> None:
    uow = InMemoryUnitOfWork()
    repo = EnlistingRepository(uow)
    with uow, pytest.raises(UnitOfWorkInvariantError):
        repo.direct_write(object())


def test_inv_enlist_under_failure() -> None:
    uow = InMemoryUnitOfWork()
    repo = EnlistingRepository(uow)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            repo.add(object())
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    with uow as u:
        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(u.new_snapshot) == 20
        u.commit()
