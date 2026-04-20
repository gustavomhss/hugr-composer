"""Chaos / fault-injection for ValueObject.

Game-day scenarios: adversarial inputs, mutable-container smuggling attempts,
bypass via setattr, deep-nesting stress, Aggregate-identity smuggling. The
primitive MUST remain correct and invariant-respecting under each.
"""

from __future__ import annotations

import dataclasses
import threading

import pytest

from ValueObject import (
    DateRange,
    Email,
    FrozenValueObject,
    Money,
    ValueObjectInvariantError,
    validate_attributes,
)


def test_chaos_setattr_bypass_attempts() -> None:
    m = Money(amount_cents=1, currency="USD")
    # object.__setattr__ bypass is the standard attack vector on frozen
    # dataclasses.  With slots=True, there is no __dict__, so the write
    # either hits a slot descriptor (raising) or the frozen __setattr__
    # (also raising).  Either way the invariant holds.
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        m.__setattr__("amount_cents", 9999)


def test_chaos_mutable_container_smuggling_rejected() -> None:
    # Callers sometimes try to sneak lists/dicts into VO attributes.
    # validate_attributes rejects them up-front.
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"lst": [1, 2, 3]})
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"bag": {"k": "v"}})
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"set": {1, 2}})
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("X", {"ba": bytearray(b"x")})


def test_chaos_aggregate_identity_smuggling_rejected() -> None:
    class EntityProxy:
        _entity_id: str = "ent-42"

    class AggregateProxy:
        __aggregate_root__: bool = True

    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("VO", {"ent": EntityProxy()})
    with pytest.raises(ValueObjectInvariantError):
        validate_attributes("VO", {"agg": AggregateProxy()})


def test_chaos_deeply_nested_valueobjects_hold() -> None:
    @dataclasses.dataclass(frozen=True, slots=True)
    class Box(FrozenValueObject):
        inner: FrozenValueObject
        label: str

    cur: FrozenValueObject = Money(amount_cents=0, currency="USD")
    # Nest 40 deep; equality / hash must still work without recursion blow-up.
    for i in range(40):
        cur = Box(inner=cur, label=f"L{i}")
    clone: FrozenValueObject = Money(amount_cents=0, currency="USD")
    for i in range(40):
        clone = Box(inner=clone, label=f"L{i}")
    assert cur == clone
    assert hash(cur) == hash(clone)


def test_chaos_concurrent_construction_is_safe() -> None:
    # Frozen dataclasses have no shared state across instances; concurrent
    # construction must not produce cross-thread contamination.
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(500):
                m = Money(amount_cents=7, currency="USD")
                assert m == Money(amount_cents=7, currency="USD")
        except BaseException as exc:  # pragma: no cover — chaos capture
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_chaos_weird_currency_codes_rejected() -> None:
    for bad in ("", "US", "USDD", "us_", "1SD", " USD"):
        with pytest.raises(ValueObjectInvariantError):
            Money(amount_cents=1, currency=bad)


def test_chaos_weird_email_strings_rejected() -> None:
    for bad in ("", "@", "a@", "@b", "a@b", "a@@b.com", "no-at"):
        with pytest.raises(ValueObjectInvariantError):
            Email(address=bad)


def test_chaos_daterange_bounds_strict() -> None:
    for s, e in ((0, 0), (5, 5), (100, 50), (-10, -20)):
        with pytest.raises(ValueObjectInvariantError):
            DateRange(start_epoch_s=s, end_epoch_s=e)


def test_chaos_bool_is_not_int_for_money() -> None:
    # `True` / `False` are ints in Python; attribute-type discipline MUST
    # reject them as amount_cents to prevent a common type-confusion bug.
    with pytest.raises(ValueObjectInvariantError):
        Money(amount_cents=True, currency="USD")  # type: ignore[arg-type]


def test_chaos_unknown_field_via_with_changes_rejected() -> None:
    m = Money(amount_cents=1, currency="USD")
    with pytest.raises(ValueObjectInvariantError):
        m.with_changes(nope=1)
