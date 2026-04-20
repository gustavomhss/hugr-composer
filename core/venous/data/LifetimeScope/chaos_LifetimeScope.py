"""Chaos / game-day tests for LifetimeScope.

Simulates factory errors, disposal errors, concurrent resolves, double
registration, resolve-after-dispose, repeated scope cycles.
"""

from __future__ import annotations

import threading

import pytest

from LifetimeScope import (
    LifetimeScope,
    LifetimeScopeInvariantError,
    ScopeManager,
)


class Svc:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_chaos_factory_raises_propagates() -> None:
    m = ScopeManager()

    def boom() -> Svc:
        raise OSError("resource unavailable")

    m.register("s", boom, scope=LifetimeScope.SINGLETON)
    with pytest.raises(OSError):
        m.resolve("s")


def test_chaos_close_raises_does_not_break_dispose() -> None:
    class Grumpy:
        def close(self) -> None:
            raise RuntimeError("refuses to close")

    m = ScopeManager()
    m.register("s", Grumpy, scope=LifetimeScope.SCOPED)
    with m.scope() as child:
        child.resolve("s")
    assert child.disposed


def test_chaos_duplicate_registrations_rejected() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SINGLETON)
    failures = 0
    for _ in range(50):
        try:
            m.register("s", Svc, scope=LifetimeScope.SINGLETON)
        except LifetimeScopeInvariantError:
            failures += 1
    assert failures == 50


def test_chaos_concurrent_resolves_return_same_singleton() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SINGLETON)
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        inst = m.resolve("s")
        with lock:
            seen.append(id(inst))

    ts = [threading.Thread(target=worker) for _ in range(60)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(seen)) == 1


def test_chaos_resolve_after_dispose_forbidden() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SCOPED)
    child = m.open_scope()
    child.dispose()
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-02"):
        child.resolve("s")


def test_chaos_open_scope_after_dispose_forbidden() -> None:
    m = ScopeManager()
    child = m.open_scope()
    child.dispose()
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-02"):
        child.open_scope()


def test_chaos_repeated_scope_cycles() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SCOPED)
    for _ in range(500):
        with m.scope() as child:
            child.resolve("s")
    # Root singleton cache untouched.
    assert m.singleton_snapshot() == ()


def test_chaos_invalid_scope_string_rejected() -> None:
    m = ScopeManager()
    for bad in ("Singleton", "REQUEST", "", "session", "per-request"):
        with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-05"):
            m.register(f"s_{bad}", Svc, scope=bad)


def test_chaos_partial_failure_still_disposes_others() -> None:
    # An earlier instance's close() raises; later instances still close.
    class Ok:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class Bad:
        def close(self) -> None:
            raise RuntimeError("bad close")

    ok_refs: list[Ok] = []
    m = ScopeManager()
    m.register("ok1", lambda: (o := Ok(), ok_refs.append(o), o)[-1], scope=LifetimeScope.SCOPED)
    m.register("bad", Bad, scope=LifetimeScope.SCOPED)
    m.register("ok2", lambda: (o := Ok(), ok_refs.append(o), o)[-1], scope=LifetimeScope.SCOPED)
    with m.scope() as child:
        child.resolve("ok1")
        child.resolve("bad")
        child.resolve("ok2")
    assert child.disposed
    # All Ok instances closed, Bad's failure swallowed.
    assert all(o.closed for o in ok_refs)
