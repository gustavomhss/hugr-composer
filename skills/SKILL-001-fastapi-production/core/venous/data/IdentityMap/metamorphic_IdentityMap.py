"""Metamorphic + differential tests for IdentityMap.

Algebraic properties:
- `get` is pure — repeated calls return the same reference without side effects.
- `add` is idempotent on the same reference; non-idempotent on distinct instances.
- `remove` followed by `add` is legal; `add` followed by `contains` is True.
- Keys are disjoint per type: (Order, 1) and (Invoice, 1) never collide.
- `dispose` is idempotent; post-dispose every operation raises identically.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from IdentityMap import (
    IdentityMapInvariantError,
    InMemoryIdentityMap,
)


@dataclass
class A:
    id: int


@dataclass
class B:
    id: int


def test_metamorphic_get_is_pure() -> None:
    imap = InMemoryIdentityMap()
    a = A(id=1)
    imap.add(a)
    # Ten gets in a row must all be the same reference and must not change state.
    refs = [imap.get(A, 1) for _ in range(10)]
    assert all(r is a for r in refs)
    assert imap.size() == 1


def test_metamorphic_add_same_ref_idempotent() -> None:
    imap = InMemoryIdentityMap()
    a = A(id=1)
    for _ in range(10):
        imap.add(a)
    assert imap.size() == 1
    assert imap.get(A, 1) is a


def test_metamorphic_add_different_ref_non_idempotent() -> None:
    imap = InMemoryIdentityMap()
    imap.add(A(id=2))
    with pytest.raises(IdentityMapInvariantError):
        imap.add(A(id=2))


def test_metamorphic_remove_then_add_is_legal() -> None:
    imap = InMemoryIdentityMap()
    first = A(id=3)
    imap.add(first)
    imap.remove(A, 3)
    second = A(id=3)
    imap.add(second)
    assert imap.get(A, 3) is second
    assert imap.get(A, 3) is not first


def test_metamorphic_type_keyspace_disjoint() -> None:
    imap = InMemoryIdentityMap()
    a = A(id=1)
    b = B(id=1)
    imap.add(a)
    imap.add(b)
    assert imap.get(A, 1) is a
    assert imap.get(B, 1) is b
    assert imap.contains(A, 1)
    assert imap.contains(B, 1)


def test_metamorphic_dispose_idempotent() -> None:
    imap = InMemoryIdentityMap()
    imap.add(A(id=1))
    for _ in range(5):
        imap.dispose()
    assert imap.state == "disposed"


def test_differential_contains_mirrors_get() -> None:
    """`contains(t, i)` MUST agree with `get(t, i) is not None` for every observed key."""
    imap = InMemoryIdentityMap()
    imap.add(A(id=1))
    imap.add(A(id=2))
    imap.add(B(id=1))
    for t, i in [(A, 1), (A, 2), (A, 3), (B, 1), (B, 99)]:
        assert imap.contains(t, i) == (imap.get(t, i) is not None)


def test_metamorphic_add_remove_contains_cycle() -> None:
    imap = InMemoryIdentityMap()
    a = A(id=7)
    imap.add(a)
    assert imap.contains(A, 7)
    imap.remove(A, 7)
    assert not imap.contains(A, 7)
    assert imap.get(A, 7) is None
