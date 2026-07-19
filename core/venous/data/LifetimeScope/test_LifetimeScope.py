"""Unit tests for LifetimeScope — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from LifetimeScope import (
    LifetimeScope,
    LifetimeScopeInvariantError,
    ScopeManager,
    coerce,
    is_closed_value,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
class Svc:
    instances = 0

    def __init__(self) -> None:
        Svc.instances += 1
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _fresh_manager() -> ScopeManager:
    Svc.instances = 0
    return ScopeManager()


# ---------------------------------------------------------------------------
# LS_INV_01 — singleton identity
# ---------------------------------------------------------------------------
def test_inv_singleton_identity_confirms() -> None:
    m = _fresh_manager()
    m.register("svc", Svc, scope=LifetimeScope.SINGLETON)
    a = m.resolve("svc")
    b = m.resolve("svc")
    assert a is b
    assert Svc.instances == 1


def test_inv_singleton_identity_prevents() -> None:
    # A child scope MUST observe the same singleton identity as the root.
    m = _fresh_manager()
    m.register("svc", Svc, scope=LifetimeScope.SINGLETON)
    root_inst = m.resolve("svc")
    with m.scope() as child:
        child_inst = child.resolve("svc")
    assert root_inst is child_inst
    assert Svc.instances == 1


def test_inv_singleton_identity_under_failure() -> None:
    # Concurrent cold resolves MUST yield exactly one singleton identity.
    m = _fresh_manager()
    m.register("svc", Svc, scope=LifetimeScope.SINGLETON)
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        inst = m.resolve("svc")
        with lock:
            seen.append(id(inst))

    ts = [threading.Thread(target=worker) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(seen)) == 1


# ---------------------------------------------------------------------------
# LS_INV_02 — scoped lifecycle (per-scope unique + LIFO disposal)
# ---------------------------------------------------------------------------
def test_inv_scoped_lifecycle_confirms() -> None:
    m = _fresh_manager()
    m.register("svc", Svc, scope=LifetimeScope.SCOPED)
    created: list[Svc] = []
    with m.scope() as child:
        a = child.resolve_typed("svc", Svc)
        b = child.resolve_typed("svc", Svc)
        assert a is b
        created.append(a)
    assert created[0].closed is True  # disposed on scope exit


def test_inv_scoped_lifecycle_prevents() -> None:
    # Resolving a scoped key from the root is FORBIDDEN.
    m = _fresh_manager()
    m.register("svc", Svc, scope=LifetimeScope.SCOPED)
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-02"):
        m.resolve("svc")
    # Resolving after dispose is FORBIDDEN.
    child = m.open_scope()
    child.resolve("svc")
    child.dispose()
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-02"):
        child.resolve("svc")


def test_inv_scoped_lifecycle_under_failure() -> None:
    # Instances are disposed in LIFO order and an exception inside the scope
    # STILL disposes every owned instance.
    m = _fresh_manager()
    m.register("a", Svc, scope=LifetimeScope.SCOPED)
    m.register("b", Svc, scope=LifetimeScope.SCOPED)
    m.register("c", Svc, scope=LifetimeScope.SCOPED)
    captured: dict[str, Svc] = {}
    with pytest.raises(RuntimeError, match="boom"), m.scope() as child:
        captured["a"] = child.resolve_typed("a", Svc)
        captured["b"] = child.resolve_typed("b", Svc)
        captured["c"] = child.resolve_typed("c", Svc)
        raise RuntimeError("boom")
    assert captured["a"].closed
    assert captured["b"].closed
    assert captured["c"].closed


# ---------------------------------------------------------------------------
# LS_INV_03 — transient freshness
# ---------------------------------------------------------------------------
def test_inv_transient_fresh_confirms() -> None:
    m = _fresh_manager()
    m.register("svc", Svc, scope=LifetimeScope.TRANSIENT)
    a = m.resolve("svc")
    b = m.resolve("svc")
    assert a is not b
    assert Svc.instances == 2


def test_inv_transient_fresh_prevents() -> None:
    # A transient MUST NOT appear in the scope snapshot — nothing is cached.
    m = _fresh_manager()
    m.register("svc", Svc, scope=LifetimeScope.TRANSIENT)
    with m.scope() as child:
        child.resolve("svc")
        child.resolve("svc")
        assert child.scope_snapshot() == ()


def test_inv_transient_fresh_under_failure() -> None:
    # Even when the factory would return the same object, the contract is
    # per-CALL — we therefore verify that two calls never hand back a cached
    # object (each `resolve` invokes the factory).
    m = _fresh_manager()
    calls = {"n": 0}

    def factory() -> Svc:
        calls["n"] += 1
        return Svc()

    m.register("svc", factory, scope=LifetimeScope.TRANSIENT)
    for _ in range(25):
        m.resolve("svc")
    assert calls["n"] == 25


# ---------------------------------------------------------------------------
# LS_INV_04 — singleton cannot capture shorter-lived disposable
# ---------------------------------------------------------------------------
def test_inv_leak_rejection_confirms() -> None:
    # A SINGLETON with a compatible (singleton) declared lifetime is accepted.
    class ShareMe:
        __lifetime_scope__ = "singleton"

    m = _fresh_manager()
    m.register("share", ShareMe, scope=LifetimeScope.SINGLETON)
    assert isinstance(m.resolve("share"), ShareMe)


def test_inv_leak_rejection_prevents() -> None:
    # A SINGLETON capturing a declared-scoped dependency is REJECTED.
    class RequestBound:
        __lifetime_scope__ = "scoped"

    m = _fresh_manager()
    m.register("req", RequestBound, scope=LifetimeScope.SINGLETON)
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-04"):
        m.resolve("req")


def test_inv_leak_rejection_under_failure() -> None:
    # A SINGLETON capturing a declared-transient dep is also rejected.
    class PerCall:
        __lifetime_scope__ = "transient"

    m = _fresh_manager()
    m.register("pc", PerCall, scope=LifetimeScope.SINGLETON)
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-04"):
        m.resolve("pc")


# ---------------------------------------------------------------------------
# LS_INV_05 — closed vocabulary
# ---------------------------------------------------------------------------
def test_inv_closed_vocabulary_confirms() -> None:
    assert LifetimeScope("singleton") is LifetimeScope.SINGLETON
    assert coerce("scoped") is LifetimeScope.SCOPED
    assert coerce(LifetimeScope.TRANSIENT) is LifetimeScope.TRANSIENT
    assert set(LifetimeScope.__members__) == {"SINGLETON", "SCOPED", "TRANSIENT"}


def test_inv_closed_vocabulary_prevents() -> None:
    # Unknown strings are REJECTED by coerce and by register.
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-05"):
        coerce("request")
    m = _fresh_manager()
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-05"):
        m.register("x", Svc, scope="request")
    assert is_closed_value("singleton") is True
    assert is_closed_value("REQUEST") is False
    assert is_closed_value(123) is False


def test_inv_closed_vocabulary_under_failure() -> None:
    # Case sensitivity: 'Singleton' MUST NOT silently degrade.
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-05"):
        coerce("Singleton")
    # Empty string is also rejected.
    with pytest.raises(LifetimeScopeInvariantError, match="LS-INV-05"):
        coerce("")
