"""Unit tests for DiContainer — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest

from DiContainer import DiContainerInvariantError, InMemoryDiContainer


# ---------------------------------------------------------------------------
# Test helper classes
# ---------------------------------------------------------------------------
class IFoo:
    pass


class Foo(IFoo):
    pass


class IBar:
    pass


class Bar(IBar):
    pass


# ---------------------------------------------------------------------------
# DI_INV_01 — cycle detection
# ---------------------------------------------------------------------------
def test_inv_cycle_detect_confirms() -> None:
    # Non-cyclic resolve succeeds.
    c = InMemoryDiContainer()
    c.register(IFoo, Foo, scope="singleton")
    assert isinstance(c.resolve(IFoo), Foo)


def test_inv_cycle_detect_prevents() -> None:
    c = InMemoryDiContainer()

    def make_a() -> IFoo:
        return c.resolve(IFoo)  # re-entry

    c.register(IFoo, make_a, scope="singleton")
    with pytest.raises(DiContainerInvariantError, match="DI-INV-01"):
        c.resolve(IFoo)


def test_inv_cycle_detect_under_failure() -> None:
    c = InMemoryDiContainer()

    def make_bar() -> IBar:
        # mutual recursion
        c.resolve(IFoo)
        return Bar()

    def make_foo() -> IFoo:
        c.resolve(IBar)
        return Foo()

    c.register(IFoo, make_foo, scope="transient")
    c.register(IBar, make_bar, scope="transient")
    with pytest.raises(DiContainerInvariantError, match="DI-INV-01"):
        c.resolve(IFoo)


# ---------------------------------------------------------------------------
# DI_INV_02 — scope leak prevention
# ---------------------------------------------------------------------------
def test_inv_scope_leak_confirms() -> None:
    # A scoped registration resolves cleanly inside a child scope.
    c = InMemoryDiContainer()
    c.register(IBar, Bar, scope="scoped")
    with c.create_scope() as scope:
        b = scope.resolve(IBar)
        assert isinstance(b, Bar)


def test_inv_scope_leak_prevents() -> None:
    # Resolving a scoped registration from the root is FORBIDDEN.
    c = InMemoryDiContainer()
    c.register(IBar, Bar, scope="scoped")
    with pytest.raises(DiContainerInvariantError, match="DI-INV-02"):
        c.resolve(IBar)


def test_inv_scope_leak_under_failure() -> None:
    # A singleton owner holding a transient-declared dep is rejected.
    class ShortLived:
        __scope_declaration__ = "transient"

    c = InMemoryDiContainer()
    c.register(ShortLived, ShortLived, scope="singleton")
    with pytest.raises(DiContainerInvariantError, match="DI-INV-02"):
        c.resolve(ShortLived)


# ---------------------------------------------------------------------------
# DI_INV_03 — disposal of owned instances
# ---------------------------------------------------------------------------
class Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_inv_dispose_owned_confirms() -> None:
    c = InMemoryDiContainer()
    c.register(Closable, Closable, scope="scoped")
    with c.create_scope() as scope:
        instance = scope.resolve(Closable)
        assert instance.closed is False
    assert instance.closed is True


def test_inv_dispose_owned_prevents() -> None:
    # An externally registered instance is NEVER disposed.
    c = InMemoryDiContainer()
    external = Closable()
    c.register_instance(Closable, external)
    with c.create_scope() as scope:
        resolved = scope.resolve(Closable)
        assert resolved is external
    assert external.closed is False


def test_inv_dispose_owned_under_failure() -> None:
    # Exception inside the scope STILL disposes owned instances.
    c = InMemoryDiContainer()
    c.register(Closable, Closable, scope="scoped")
    captured: list[Closable] = []
    with pytest.raises(RuntimeError, match="boom"):
        with c.create_scope() as scope:
            captured.append(scope.resolve(Closable))
            raise RuntimeError("boom")
    assert captured[0].closed is True


# ---------------------------------------------------------------------------
# DI_INV_04 — no silent re-registration
# ---------------------------------------------------------------------------
def test_inv_no_silent_replace_confirms() -> None:
    c = InMemoryDiContainer()
    c.register(IFoo, Foo, scope="singleton")
    # Explicit override is allowed.
    c.register(IFoo, Foo, scope="singleton", allow_override=True)
    assert c.is_registered(IFoo)


def test_inv_no_silent_replace_prevents() -> None:
    c = InMemoryDiContainer()
    c.register(IFoo, Foo, scope="singleton")
    with pytest.raises(DiContainerInvariantError, match="DI-INV-04"):
        c.register(IFoo, Foo, scope="singleton")


def test_inv_no_silent_replace_under_failure() -> None:
    # Concurrent double-registration: at most one wins, the rest are rejected.
    c = InMemoryDiContainer()
    ok = 0
    rejected = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal ok, rejected
        try:
            c.register(IFoo, Foo, scope="singleton")
            with lock:
                ok += 1
        except DiContainerInvariantError:
            with lock:
                rejected += 1

    ts = [threading.Thread(target=worker) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert ok == 1
    assert rejected == 19


# ---------------------------------------------------------------------------
# DI_INV_05 — interface type as key; keyed registrations need discriminator
# ---------------------------------------------------------------------------
def test_inv_iface_key_confirms() -> None:
    c = InMemoryDiContainer()
    c.register(IFoo, Foo, scope="singleton", name="primary")
    c.register(IFoo, Foo, scope="singleton", name="secondary")
    primary = c.resolve(IFoo, name="primary")
    secondary = c.resolve(IFoo, name="secondary")
    assert primary is not secondary


def test_inv_iface_key_prevents() -> None:
    c = InMemoryDiContainer()
    with pytest.raises(DiContainerInvariantError, match="DI-INV-05"):
        c.register(IFoo, Foo, scope="singleton", name="")


def test_inv_iface_key_under_failure() -> None:
    # Resolving an unregistered iface cleanly raises; no silent None.
    c = InMemoryDiContainer()
    with pytest.raises(DiContainerInvariantError, match="DI-INV-05"):
        c.resolve(IFoo)
