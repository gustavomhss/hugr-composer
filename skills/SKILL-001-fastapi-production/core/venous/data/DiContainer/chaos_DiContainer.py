"""Chaos / game-day tests for DiContainer.

Simulates factory errors, disposal errors, concurrent resolves, double
registration races, and repeated create_scope/dispose cycles.
"""

from __future__ import annotations

import threading

import pytest

from DiContainer import DiContainerInvariantError, InMemoryDiContainer


class IService:
    pass


class GoodSvc(IService):
    pass


def test_chaos_factory_raises_propagates() -> None:
    c = InMemoryDiContainer()

    def boom() -> IService:
        raise OSError("resource unavailable")

    c.register(IService, boom, scope="singleton")
    with pytest.raises(OSError):
        c.resolve(IService)


def test_chaos_close_raises_does_not_break_dispose() -> None:
    class Grumpy:
        def close(self) -> None:
            raise RuntimeError("refuses to close")

    c = InMemoryDiContainer()
    c.register(Grumpy, Grumpy, scope="scoped")
    with c.create_scope() as scope:
        scope.resolve(Grumpy)
    # No exception propagates — dispose swallows close() failures.
    assert scope.disposed


def test_chaos_many_duplicate_registrations_rejected() -> None:
    c = InMemoryDiContainer()
    c.register(IService, GoodSvc, scope="singleton")
    failures = 0
    for _ in range(100):
        try:
            c.register(IService, GoodSvc, scope="singleton")
        except DiContainerInvariantError:
            failures += 1
    assert failures == 100


def test_chaos_concurrent_resolves_return_same_singleton() -> None:
    c = InMemoryDiContainer()
    c.register(IService, GoodSvc, scope="singleton")
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        inst = c.resolve(IService)
        with lock:
            seen.append(id(inst))

    ts = [threading.Thread(target=worker) for _ in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Exactly one identity across all threads.
    assert len(set(seen)) == 1


def test_chaos_resolve_after_dispose_forbidden() -> None:
    c = InMemoryDiContainer()
    c.register(IService, GoodSvc, scope="scoped")
    scope = c.create_scope()
    scope.dispose()
    with pytest.raises(DiContainerInvariantError, match="DI-INV-03"):
        scope.resolve(IService)


def test_chaos_create_scope_after_dispose_forbidden() -> None:
    c = InMemoryDiContainer()
    scope = c.create_scope()
    scope.dispose()
    with pytest.raises(DiContainerInvariantError, match="DI-INV-03"):
        scope.create_scope()


def test_chaos_repeated_scope_cycles() -> None:
    c = InMemoryDiContainer()
    c.register(IService, GoodSvc, scope="scoped")
    for _ in range(500):
        with c.create_scope() as scope:
            scope.resolve(IService)
    # Root singleton cache untouched.
    assert c.singleton_snapshot() == ()


def test_chaos_invalid_scope_rejected() -> None:
    c = InMemoryDiContainer()
    with pytest.raises(DiContainerInvariantError, match="DI-INV-04"):
        c.register(IService, GoodSvc, scope="request")
