"""Concurrency / linearizability harness for DiContainer.

Confirms that concurrent resolves, registrations, and scope creations never
corrupt state and that singletons linearize to a single identity.
"""

from __future__ import annotations

import threading

from DiContainer import DiContainerInvariantError, InMemoryDiContainer


class IWidget:
    pass


class Widget(IWidget):
    pass


def test_concurrent_singleton_resolution_is_linearizable() -> None:
    c = InMemoryDiContainer()
    c.register(IWidget, Widget, scope="singleton")
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(20):
            inst = c.resolve(IWidget)
            with lock:
                seen.append(id(inst))

    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Exactly one singleton identity across 200 resolves.
    assert len(set(seen)) == 1


def test_concurrent_scoped_resolution_inside_scope_is_stable() -> None:
    c = InMemoryDiContainer()
    c.register(IWidget, Widget, scope="scoped")
    results: list[int] = []
    lock = threading.Lock()

    def worker(scope: InMemoryDiContainer) -> None:
        inst = scope.resolve(IWidget)
        with lock:
            results.append(id(inst))

    with c.create_scope() as scope:
        ts = [threading.Thread(target=worker, args=(scope,)) for _ in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(set(results)) == 1  # all resolves return the same instance


def test_concurrent_different_scopes_yield_distinct_instances() -> None:
    c = InMemoryDiContainer()
    c.register(IWidget, Widget, scope="scoped")
    results: list[IWidget] = []
    lock = threading.Lock()

    def worker() -> None:
        # Keep the scope alive (and thus its instance) by holding the reference
        # until every thread has finished — id() may be reused otherwise.
        scope = c.create_scope()
        inst = scope.resolve(IWidget)
        with lock:
            results.append(inst)
        scope.dispose()

    ts = [threading.Thread(target=worker) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Each scope yields a unique instance identity (references retained).
    assert len({id(x) for x in results}) == 40


def test_concurrent_double_registration_exactly_one_wins() -> None:
    c = InMemoryDiContainer()
    ok = 0
    rejected = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal ok, rejected
        try:
            c.register(IWidget, Widget, scope="singleton")
            with lock:
                ok += 1
        except DiContainerInvariantError:
            with lock:
                rejected += 1

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert ok == 1
    assert rejected == 31
