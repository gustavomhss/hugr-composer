"""Metamorphic + differential tests for LifetimeScope.

Algebraic properties:
- Singleton.resolve() is idempotent (same identity forever).
- Transient.resolve() is injective across calls (every call a distinct object).
- dispose() is idempotent.
- scope_snapshot() is LIFO (reverse of creation order).
- coerce() is a left-inverse of `.value`.
- Sibling scopes produce disjoint instance sets.
"""

from __future__ import annotations

from LifetimeScope import LifetimeScope, ScopeManager, coerce


class Svc:
    pass


def test_metamorphic_singleton_identity_stable() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SINGLETON)
    first = m.resolve("s")
    for _ in range(100):
        assert m.resolve("s") is first


def test_metamorphic_transient_never_repeats() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.TRANSIENT)
    seen = [m.resolve("s") for _ in range(30)]
    assert len({id(x) for x in seen}) == 30


def test_metamorphic_dispose_idempotent() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SCOPED)
    child = m.open_scope()
    child.resolve("s")
    for _ in range(10):
        child.dispose()
    assert child.disposed


def test_metamorphic_snapshot_is_lifo() -> None:
    m = ScopeManager()
    m.register("a", Svc, scope=LifetimeScope.SCOPED)
    m.register("b", Svc, scope=LifetimeScope.SCOPED)
    m.register("c", Svc, scope=LifetimeScope.SCOPED)
    with m.scope() as child:
        a = child.resolve("a")
        b = child.resolve("b")
        c = child.resolve("c")
        snap = child.scope_snapshot()
    # Creation order: a, b, c → LIFO snapshot: c, b, a
    assert snap == (c, b, a)


def test_metamorphic_coerce_left_inverse_of_value() -> None:
    for member in LifetimeScope:
        assert coerce(member.value) is member
        assert coerce(member) is member


def test_metamorphic_sibling_scopes_disjoint() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SCOPED)
    with m.scope() as s1, m.scope() as s2:
        a = s1.resolve("s")
        b = s2.resolve("s")
    assert a is not b


def test_differential_coerce_equivalent_to_enum_constructor() -> None:
    # coerce('singleton') ≡ LifetimeScope('singleton') for any valid value.
    for v in ("singleton", "scoped", "transient"):
        assert coerce(v) is LifetimeScope(v)


def test_metamorphic_depth_increases_monotonic() -> None:
    # Every open_scope adds exactly 1 to depth.
    m = ScopeManager()
    assert m.depth == 0
    with m.scope() as a:
        assert a.depth == 1
        with a.scope() as b:
            assert b.depth == 2
            with b.scope() as c:
                assert c.depth == 3
