"""Behavioral end-to-end scenarios for DiContainer — proves invariants at runtime."""

from __future__ import annotations

import pytest

from DiContainer import DiContainerInvariantError, InMemoryDiContainer


class IRepo:
    def save(self, x: int) -> None: ...


class SqlRepo(IRepo):
    def __init__(self) -> None:
        self.saved: list[int] = []

    def save(self, x: int) -> None:
        self.saved.append(x)


class IClock:
    pass


class SystemClock(IClock):
    pass


class Session:
    def __init__(self) -> None:
        self.open = True
        self.closed = False

    def close(self) -> None:
        self.open = False
        self.closed = True


def test_scenario_singleton_shared_across_scopes() -> None:
    c = InMemoryDiContainer()
    c.register(IRepo, SqlRepo, scope="singleton")
    with c.create_scope() as s1:
        r1 = s1.resolve(IRepo)
    with c.create_scope() as s2:
        r2 = s2.resolve(IRepo)
    assert r1 is r2


def test_scenario_scoped_unique_per_scope() -> None:
    c = InMemoryDiContainer()
    c.register(IClock, SystemClock, scope="scoped")
    with c.create_scope() as s1:
        c1 = s1.resolve(IClock)
        c1b = s1.resolve(IClock)
    with c.create_scope() as s2:
        c2 = s2.resolve(IClock)
    assert c1 is c1b
    assert c1 is not c2


def test_scenario_transient_fresh_every_resolve() -> None:
    c = InMemoryDiContainer()
    c.register(IClock, SystemClock, scope="transient")
    a = c.resolve(IClock)
    b = c.resolve(IClock)
    assert a is not b


def test_scenario_scope_ends_disposes_sessions() -> None:
    c = InMemoryDiContainer()
    c.register(Session, Session, scope="scoped")
    captured: list[Session] = []
    with c.create_scope() as scope:
        sess = scope.resolve(Session)
        captured.append(sess)
    assert captured[0].closed


def test_scenario_cycle_detected_during_resolve() -> None:
    c = InMemoryDiContainer()

    def bad() -> IRepo:
        return c.resolve(IRepo)

    c.register(IRepo, bad, scope="singleton")
    with pytest.raises(DiContainerInvariantError, match="DI-INV-01"):
        c.resolve(IRepo)


def test_scenario_keyed_registrations_resolve_distinctly() -> None:
    c = InMemoryDiContainer()
    c.register(IRepo, SqlRepo, scope="singleton", name="primary")
    c.register(IRepo, SqlRepo, scope="singleton", name="replica")
    p = c.resolve(IRepo, name="primary")
    r = c.resolve(IRepo, name="replica")
    assert p is not r
