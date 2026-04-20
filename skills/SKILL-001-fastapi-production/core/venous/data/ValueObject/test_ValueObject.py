"""Unit tests for ValueObject — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import dataclasses

import pytest

from ValueObject import (
    DateRange,
    Email,
    FrozenValueObject,
    Money,
    ValueObjectInvariantError,
    validate_attributes,
)


# ---------------------------------------------------------------------------
# VO_INV_01 — immutable after construction
# ---------------------------------------------------------------------------
def test_inv_immutable_after_construction_confirms() -> None:
    m = Money(amount_cents=1000, currency="USD")
    # Reading fields is fine; mutation is not.
    assert m.amount_cents == 1000
    assert m.currency == "USD"
    # __slots__ means no stray __dict__ either.
    assert not hasattr(m, "__dict__")


def test_inv_immutable_after_construction_prevents() -> None:
    m = Money(amount_cents=500, currency="EUR")
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.amount_cents = 999  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.currency = "XXX"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del m.currency  # type: ignore[misc]


def test_inv_immutable_after_construction_under_failure() -> None:
    m = Money(amount_cents=100, currency="USD")
    # Even if a constructor call mid-way raises, existing instances MUST remain intact.
    try:
        Money(amount_cents=-1, currency="USD")
    except ValueObjectInvariantError:
        pass
    assert m.amount_cents == 100
    # with_changes MUST produce a fresh instance — the receiver is untouched.
    m2 = m.with_changes(amount_cents=200)
    assert m.amount_cents == 100
    assert m2.amount_cents == 200
    assert m is not m2


# ---------------------------------------------------------------------------
# VO_INV_02 — equality by value + hash consistency
# ---------------------------------------------------------------------------
def test_inv_equality_by_value_confirms() -> None:
    a = Money(amount_cents=100, currency="USD")
    b = Money(amount_cents=100, currency="USD")
    assert a == b
    assert hash(a) == hash(b)
    assert a is not b
    # Usable as dict keys / set members.
    bag = {a: 1}
    assert bag[b] == 1
    assert {a, b} == {a}


def test_inv_equality_by_value_prevents() -> None:
    a = Money(amount_cents=100, currency="USD")
    b = Money(amount_cents=101, currency="USD")
    c = Money(amount_cents=100, currency="EUR")
    assert a != b
    assert a != c
    assert hash(a) != hash(b) or hash(a) != hash(c)  # at least one differs
    # Different VO class, even with overlapping fields, MUST NOT compare equal.
    assert a != Email(address="a@b.com")


def test_inv_equality_by_value_under_failure() -> None:
    # Equality MUST remain stable even if the environment is chaotic.
    a = Money(amount_cents=100, currency="USD")
    snapshots = [hash(a) for _ in range(100)]
    assert len(set(snapshots)) == 1  # hash is stable over the object's life
    assert a == Money(amount_cents=100, currency="USD")


# ---------------------------------------------------------------------------
# VO_INV_03 — no unstable-identity references
# ---------------------------------------------------------------------------
def test_inv_no_unstable_identity_refs_confirms() -> None:
    # Nested ValueObjects are fine — stable identity by value.
    @dataclasses.dataclass(frozen=True, slots=True)
    class Line(FrozenValueObject):
        price: Money
        qty: int

    line = Line(price=Money(amount_cents=100, currency="USD"), qty=3)
    assert line.price.amount_cents == 100
    assert line == Line(price=Money(amount_cents=100, currency="USD"), qty=3)


def test_inv_no_unstable_identity_refs_prevents() -> None:
    class FakeAggregate:
        _aggregate_id: str = "agg-1"

    # A VO cannot be built around a live Aggregate root.
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"agg": FakeAggregate()})

    # Mutable containers are likewise rejected.
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"items": [1, 2, 3]})
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"bag": {"k": "v"}})
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"s": {1, 2}})


def test_inv_no_unstable_identity_refs_under_failure() -> None:
    # Tuples carrying rejected values MUST also be rejected recursively.
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"nested": ([1, 2], 3)})
    # Frozensets of primitives are fine.
    validate_attributes("X", {"tags": frozenset({"a", "b"})})


# ---------------------------------------------------------------------------
# VO_INV_04 — eager construction-time validation
# ---------------------------------------------------------------------------
def test_inv_eager_validation_confirms() -> None:
    # Valid construction returns a fully-validated instance.
    m = Money(amount_cents=0, currency="USD")
    assert m.amount_cents == 0
    e = Email(address="alice@example.com")
    assert e.address == "alice@example.com"
    d = DateRange(start_epoch_s=0, end_epoch_s=86_400)
    assert d.end_epoch_s > d.start_epoch_s


def test_inv_eager_validation_prevents() -> None:
    # Every invariant violation raises AT CONSTRUCTION — no half-built object.
    with pytest.raises(ValueObjectInvariantError):
        Money(amount_cents=-5, currency="USD")
    with pytest.raises(ValueObjectInvariantError):
        Money(amount_cents=10, currency="usd")  # lowercase
    with pytest.raises(ValueObjectInvariantError):
        Money(amount_cents=10, currency="DOLLAR")  # wrong length
    with pytest.raises(ValueObjectInvariantError):
        Email(address="no-at-sign")
    with pytest.raises(ValueObjectInvariantError):
        Email(address="a@@b.com")
    with pytest.raises(ValueObjectInvariantError):
        DateRange(start_epoch_s=100, end_epoch_s=100)  # not strictly greater
    with pytest.raises(ValueObjectInvariantError):
        DateRange(start_epoch_s=200, end_epoch_s=100)


def test_inv_eager_validation_under_failure() -> None:
    # with_changes also goes through __post_init__ — violations raise there too.
    m = Money(amount_cents=100, currency="USD")
    with pytest.raises(ValueObjectInvariantError):
        m.with_changes(amount_cents=-1)
    with pytest.raises(ValueObjectInvariantError):
        m.with_changes(currency="us")
    # Unknown field names are also rejected eagerly.
    with pytest.raises(ValueObjectInvariantError):
        m.with_changes(unknown_field=1)
