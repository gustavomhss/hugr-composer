"""Metamorphic + differential tests for ValueObject.

Algebraic laws:
- Reflexivity, symmetry, transitivity of equality
- hash-equals-implies-equals consistency (VO-INV-02)
- with_changes(x=x.x) == x (identity)
- with_changes is composable: with_changes(a=1).with_changes(b=2)
  == with_changes(a=1, b=2)
- Money.add associativity + commutativity
- Serialization roundtrip is the identity (differential parity)
"""

from __future__ import annotations

import dataclasses

from ValueObject import (
    CoercionRegistry,
    DateRange,
    Email,
    FrozenValueObject,
    Money,
)


def test_metamorphic_equality_reflexive() -> None:
    m = Money(amount_cents=7, currency="USD")
    assert m == m
    assert hash(m) == hash(m)


def test_metamorphic_equality_symmetric() -> None:
    a = Money(amount_cents=7, currency="USD")
    b = Money(amount_cents=7, currency="USD")
    assert (a == b) and (b == a)


def test_metamorphic_equality_transitive() -> None:
    a = Money(amount_cents=3, currency="BRL")
    b = Money(amount_cents=3, currency="BRL")
    c = Money(amount_cents=3, currency="BRL")
    assert a == b and b == c and a == c


def test_metamorphic_hash_equals_implies_equals() -> None:
    # If two VOs are equal, their hashes MUST be equal (VO-INV-02).
    # We sample to gain confidence; the frozen-dataclass contract guarantees it.
    for i in range(200):
        a = Money(amount_cents=i, currency="USD")
        b = Money(amount_cents=i, currency="USD")
        if a == b:
            assert hash(a) == hash(b)


def test_metamorphic_with_changes_identity() -> None:
    # Replacing a field with its current value yields an equal object.
    e = Email(address="x@y.com")
    assert e.with_changes(address=e.address) == e


def test_metamorphic_with_changes_composition() -> None:
    d1 = DateRange(start_epoch_s=0, end_epoch_s=10)
    a = d1.with_changes(end_epoch_s=20).with_changes(start_epoch_s=5)
    b = d1.with_changes(start_epoch_s=5, end_epoch_s=20)
    assert a == b


def test_metamorphic_money_addition_associative() -> None:
    a = Money(amount_cents=1, currency="USD")
    b = Money(amount_cents=2, currency="USD")
    c = Money(amount_cents=3, currency="USD")
    assert a.add(b).add(c) == a.add(b.add(c))


def test_metamorphic_money_addition_commutative() -> None:
    a = Money(amount_cents=5, currency="USD")
    b = Money(amount_cents=8, currency="USD")
    assert a.add(b) == b.add(a)


def test_differential_coercion_roundtrip_is_identity() -> None:
    reg = CoercionRegistry()
    cases: list[FrozenValueObject] = [
        Money(amount_cents=0, currency="USD"),
        Money(amount_cents=9_999, currency="EUR"),
        Email(address="alice@example.org"),
        DateRange(start_epoch_s=1, end_epoch_s=2),
    ]
    for obj in cases:
        mapping = reg.to_mapping(obj)
        restored = reg.from_mapping(type(obj), mapping)
        assert restored == obj


def test_differential_custom_adapter_matches_default() -> None:
    reg = CoercionRegistry()
    reg.register(
        Money,
        to_mapping=lambda m: {"amount_cents": m.amount_cents, "currency": m.currency},
        from_mapping=lambda d: Money(**d),
    )
    m = Money(amount_cents=42, currency="USD")
    assert reg.to_mapping(m) == m.to_dict()
    assert reg.from_mapping(Money, reg.to_mapping(m)) == m


def test_metamorphic_nested_composition_preserves_equality() -> None:
    @dataclasses.dataclass(frozen=True, slots=True)
    class Wrap(FrozenValueObject):
        inner: Money

    w1 = Wrap(inner=Money(amount_cents=11, currency="USD"))
    w2 = Wrap(inner=Money(amount_cents=11, currency="USD"))
    assert w1 == w2
    w3 = w1.with_changes(inner=Money(amount_cents=12, currency="USD"))
    assert w1 != w3
