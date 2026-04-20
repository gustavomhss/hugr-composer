"""Behavioral end-to-end scenarios for LifetimeScope — proves invariants at runtime."""

from __future__ import annotations

import pytest

from LifetimeScope import (
    LifetimeScope,
    LifetimeScopeInvariantError,
    ScopeManager,
)


class RequestContext:
    """A request-scoped state bag that a handler would own."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.events.append("close")


class Session:
    def __init__(self) -> None:
        self.open = True
        self.closed = False

    def close(self) -> None:
        self.open = False
        self.closed = True


class Config:
    """A process-wide singleton."""


def test_scenario_request_scope_session_closed_on_exit() -> None:
    # A web-request lifecycle: open_scope, resolve scoped Session, exit auto-closes.
    m = ScopeManager()
    m.register("session", Session, scope=LifetimeScope.SCOPED)
    recorded: list[Session] = []
    with m.scope() as request:
        sess = request.resolve_typed("session", Session)
        recorded.append(sess)
        assert sess.open is True
    assert recorded[0].closed is True


def test_scenario_sibling_scopes_isolated() -> None:
    # Two independent "requests" get distinct scoped instances.
    m = ScopeManager()
    m.register("session", Session, scope=LifetimeScope.SCOPED)
    with m.scope() as s1:
        a = s1.resolve_typed("session", Session)
    with m.scope() as s2:
        b = s2.resolve_typed("session", Session)
    assert a is not b


def test_scenario_singleton_shared_across_requests() -> None:
    # A Config singleton is the SAME instance across nested scopes.
    m = ScopeManager()
    m.register("config", Config, scope=LifetimeScope.SINGLETON)
    with m.scope() as s1:
        cfg1 = s1.resolve("config")
    with m.scope() as s2:
        cfg2 = s2.resolve("config")
    assert cfg1 is cfg2


def test_scenario_transient_each_call_fresh() -> None:
    # A transient context is NEVER reused.
    m = ScopeManager()
    m.register("req", RequestContext, scope=LifetimeScope.TRANSIENT)
    a = m.resolve("req")
    b = m.resolve("req")
    assert a is not b


def test_scenario_lifo_disposal_order() -> None:
    # Instances disposed in reverse construction order (LIFO).
    m = ScopeManager()
    m.register("a", RequestContext, scope=LifetimeScope.SCOPED)
    m.register("b", RequestContext, scope=LifetimeScope.SCOPED)
    m.register("c", RequestContext, scope=LifetimeScope.SCOPED)

    dispose_order: list[str] = []

    class Tracked(RequestContext):
        def __init__(self, name: str, order: list[str]) -> None:
            super().__init__()
            self._name = name
            self._order = order

        def close(self) -> None:
            self._order.append(self._name)
            super().close()

    m2 = ScopeManager()
    m2.register("a", lambda: Tracked("a", dispose_order), scope=LifetimeScope.SCOPED)
    m2.register("b", lambda: Tracked("b", dispose_order), scope=LifetimeScope.SCOPED)
    m2.register("c", lambda: Tracked("c", dispose_order), scope=LifetimeScope.SCOPED)
    with m2.scope() as child:
        child.resolve("a")
        child.resolve("b")
        child.resolve("c")
    # LIFO: c first, then b, then a.
    assert dispose_order == ["c", "b", "a"]


def test_scenario_nested_scopes_inherit_parent() -> None:
    # A grandchild scope inherits registrations from root via the chain.
    m = ScopeManager()
    m.register("session", Session, scope=LifetimeScope.SCOPED)
    with m.scope() as child:
        with child.scope() as grandchild:
            sess = grandchild.resolve_typed("session", Session)
            assert sess.open


def test_scenario_unknown_lifetime_rejected_at_boundary() -> None:
    # A framework adapter receiving 'request' (Spring/Nest.js style) MUST
    # translate explicitly — the raw string is rejected by the enum.
    m = ScopeManager()
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-05"):
        m.register("svc", Session, scope="request")
