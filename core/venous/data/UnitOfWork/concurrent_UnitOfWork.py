"""Concurrency / linearizability harness for UnitOfWork.

Confirms that concurrent registrations from multiple threads never corrupt
bucket sets and the disjointness invariant holds under race.
"""

from __future__ import annotations

import threading

from UnitOfWork import InMemoryUnitOfWork, UnitOfWorkInvariantError


def test_concurrent_registrations_preserve_bucket_disjointness() -> None:
    uow = InMemoryUnitOfWork()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(bucket: str, n: int) -> None:
        try:
            for _ in range(n):
                obj = object()
                if bucket == "new":
                    uow.register_new(obj)
                elif bucket == "dirty":
                    uow.register_dirty(obj)
                else:
                    uow.register_removed(obj)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    with uow:
        ts = [
            threading.Thread(target=worker, args=("new", 100)),
            threading.Thread(target=worker, args=("dirty", 100)),
            threading.Thread(target=worker, args=("removed", 100)),
            threading.Thread(target=worker, args=("new", 100)),
        ]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert not errors
        new_ids = {id(o) for o in uow.new_snapshot}
        dirty_ids = {id(o) for o in uow.dirty_snapshot}
        removed_ids = {id(o) for o in uow.removed_snapshot}
        assert len(new_ids) == 200
        assert len(dirty_ids) == 100
        assert len(removed_ids) == 100
        assert new_ids.isdisjoint(dirty_ids)
        assert new_ids.isdisjoint(removed_ids)
        assert dirty_ids.isdisjoint(removed_ids)


def test_concurrent_commit_then_registration_is_rejected() -> None:
    uow = InMemoryUnitOfWork()
    with uow:
        uow.commit()

    errors: list[BaseException] = []
    accepted: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            uow.register_new(object())
            with lock:
                accepted.append(1)
        except UnitOfWorkInvariantError:
            pass
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert accepted == []  # every registration after commit MUST be rejected


def test_concurrent_rollback_and_read_snapshot() -> None:
    uow = InMemoryUnitOfWork()
    with uow as u:
        for _ in range(50):
            u.register_new(object())

    # After context-manager auto-rollback, snapshots MUST be empty regardless of
    # concurrent readers.
    results: list[int] = []
    lock = threading.Lock()

    def reader() -> None:
        with lock:
            results.append(len(uow.new_snapshot))

    ts = [threading.Thread(target=reader) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(r == 0 for r in results)
