"""Chaos / game-day tests for UnitOfWork.

Simulates flush-time failures, repeated registrations, hook errors, and
interleaved rollback/commit sequences to confirm the unit never enters an
inconsistent state.
"""

from __future__ import annotations

import threading

import pytest

from UnitOfWork import InMemoryUnitOfWork, UnitOfWorkInvariantError


def test_chaos_flush_raises_then_unit_is_terminal() -> None:
    def always_fails(n: list[object], d: list[object], r: list[object]) -> None:
        raise OSError("disk full")

    uow = InMemoryUnitOfWork(flush_fn=always_fails)
    with pytest.raises(OSError):
        with uow as u:
            u.register_new(object())
            u.commit()
    assert uow.state == "rolled_back"
    with pytest.raises(UnitOfWorkInvariantError):
        uow.register_new(object())


def test_chaos_hook_raises_triggers_rollback() -> None:
    uow = InMemoryUnitOfWork()

    def angry(_u: InMemoryUnitOfWork) -> None:
        raise ValueError("hook angry")

    uow.register_before_commit(angry)
    with pytest.raises(ValueError):
        with uow as u:
            u.register_new(object())
            u.commit()
    assert uow.state == "rolled_back"


def test_chaos_many_duplicate_registrations_rejected() -> None:
    uow = InMemoryUnitOfWork()
    failures = 0
    with uow as u:
        shared = object()
        u.register_new(shared)
        for _ in range(100):
            try:
                u.register_dirty(shared)
            except UnitOfWorkInvariantError:
                failures += 1
    assert failures == 100


def test_chaos_rollback_is_safe_after_commit() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        u.register_new(object())
        u.commit()
    # Rollback after commit MUST be a no-op (already terminal), not raise.
    uow.rollback()
    assert uow.state == "committed"


def test_chaos_concurrent_commit_attempts() -> None:
    uow = InMemoryUnitOfWork()
    ok: list[int] = []
    rejected: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            uow.commit()
            with lock:
                ok.append(1)
        except UnitOfWorkInvariantError:
            with lock:
                rejected.append(1)

    with uow as u:
        u.register_new(object())
        ts = [threading.Thread(target=worker) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    # At most one commit wins; the rest must be rejected.
    assert len(ok) <= 1
    assert len(ok) + len(rejected) == 8


def test_chaos_empty_unit_commits_cleanly() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        u.commit()
    assert uow.state == "committed"


def test_chaos_large_registration_batch() -> None:
    captured: list[int] = []

    def flush(n: list[object], d: list[object], r: list[object]) -> None:
        captured.append(len(n))

    uow = InMemoryUnitOfWork(flush_fn=flush)
    with uow as u:
        for _ in range(10_000):
            u.register_new(object())
        u.commit()
    assert captured == [10_000]
