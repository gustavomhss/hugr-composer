"""Concurrency / linearizability harness for LifetimeScope.ScopeManager."""

from __future__ import annotations

import threading

from LifetimeScope import (
    LifetimeScope,
    LifetimeScopeInvariantError,
    ScopeManager,
)


class Widget:
    pass


def test_concurrent_singleton_resolution_is_linearizable() -> None:
    m = ScopeManager()
    m.register("w", Widget, scope=LifetimeScope.SINGLETON)
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(20):
            inst = m.resolve("w")
            with lock:
                seen.append(id(inst))

    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(seen)) == 1


def test_concurrent_scoped_resolution_inside_scope_is_stable() -> None:
    m = ScopeManager()
    m.register("w", Widget, scope=LifetimeScope.SCOPED)
    results: list[int] = []
    lock = threading.Lock()

    def worker(scope: ScopeManager) -> None:
        inst = scope.resolve("w")
        with lock:
            results.append(id(inst))

    with m.scope() as child:
        ts = [threading.Thread(target=worker, args=(child,)) for _ in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(set(results)) == 1


def test_concurrent_different_scopes_yield_distinct_instances() -> None:
    m = ScopeManager()
    m.register("w", Widget, scope=LifetimeScope.SCOPED)
    results: list[Widget] = []
    lock = threading.Lock()

    def worker() -> None:
        # Retain references so id() cannot be reused.
        scope = m.open_scope()
        inst = scope.resolve("w")
        assert isinstance(inst, Widget)
        with lock:
            results.append(inst)
        scope.dispose()

    ts = [threading.Thread(target=worker) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len({id(x) for x in results}) == 40


def test_concurrent_double_registration_exactly_one_wins() -> None:
    m = ScopeManager()
    ok = 0
    rejected = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal ok, rejected
        try:
            m.register("w", Widget, scope=LifetimeScope.SINGLETON)
            with lock:
                ok += 1
        except LifetimeScopeInvariantError:
            with lock:
                rejected += 1

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert ok == 1
    assert rejected == 31


def test_concurrent_transient_yields_distinct_objects() -> None:
    m = ScopeManager()
    m.register("w", Widget, scope=LifetimeScope.TRANSIENT)
    results: list[Widget] = []
    lock = threading.Lock()

    def worker() -> None:
        inst = m.resolve_typed("w", Widget)
        with lock:
            results.append(inst)

    ts = [threading.Thread(target=worker) for _ in range(60)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # All references retained → all ids distinct.
    assert len({id(x) for x in results}) == 60
