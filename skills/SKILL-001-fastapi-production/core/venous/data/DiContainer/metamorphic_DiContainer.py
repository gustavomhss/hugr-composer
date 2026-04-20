"""Metamorphic + differential tests for DiContainer.

Algebraic properties:
- Singleton.resolve() returns the same instance across any number of calls.
- Transient.resolve() returns a fresh instance on every call.
- dispose() is idempotent.
- Scope siblings are independent (resolutions in one scope don't leak into another).
"""

from __future__ import annotations

from DiContainer import InMemoryDiContainer


class IService:
    pass


class SvcImpl(IService):
    pass


def test_metamorphic_singleton_identity_is_stable() -> None:
    c = InMemoryDiContainer()
    c.register(IService, SvcImpl, scope="singleton")
    first = c.resolve(IService)
    for _ in range(50):
        assert c.resolve(IService) is first


def test_metamorphic_transient_never_repeats() -> None:
    c = InMemoryDiContainer()
    c.register(IService, SvcImpl, scope="transient")
    instances: list[IService] = [c.resolve(IService) for _ in range(20)]
    ids = {id(x) for x in instances}
    assert len(ids) == 20


def test_metamorphic_dispose_idempotent() -> None:
    c = InMemoryDiContainer()
    c.register(IService, SvcImpl, scope="scoped")
    scope = c.create_scope()
    scope.resolve(IService)
    for _ in range(10):
        scope.dispose()
    assert scope.disposed


def test_metamorphic_sibling_scopes_isolated() -> None:
    c = InMemoryDiContainer()
    c.register(IService, SvcImpl, scope="scoped")
    with c.create_scope() as s1, c.create_scope() as s2:
        a = s1.resolve(IService)
        b = s2.resolve(IService)
    assert a is not b


def test_differential_explicit_override_equals_fresh_container() -> None:
    # Registering IService then overriding it must yield the same behaviour as
    # a fresh container registered with the final impl.
    c1 = InMemoryDiContainer()
    c1.register(IService, SvcImpl, scope="singleton")
    c1.register(IService, SvcImpl, scope="singleton", allow_override=True)

    c2 = InMemoryDiContainer()
    c2.register(IService, SvcImpl, scope="singleton")

    assert type(c1.resolve(IService)) is type(c2.resolve(IService))
