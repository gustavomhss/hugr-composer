"""Metamorphic + differential tests for InputValidator.

Algebraic properties:
- parse_then_dict_roundtrip: parse(raw) then to_dict() returns the same values.
- extra_field_monotone: adding any unknown field to a valid payload MUST
  toggle parse() from accept to reject.
- bound_shrink_monotone: tightening a max_length can only turn accepts into
  rejects, never the reverse.
- order_independence: field order in the input mapping MUST NOT affect parse
  outcome.
- determinism: repeated parse() of the same raw payload yields equal results.
- coerce_differential: a digit-only string coerces to int iff allow_coerce.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from InputValidator import (
    SchemaField,
    SchemaModel,
    SchemaValidator,
    ValidationError,
)


class User(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "name": SchemaField(type_=str, min_length=1, max_length=32),
        "age": SchemaField(type_=int, min_value=0, max_value=150),
    }


def _v() -> SchemaValidator:
    return SchemaValidator()


def test_metamorphic_parse_then_dict_roundtrip() -> None:
    raw = {"name": "alice", "age": 30}
    u = _v().parse(raw, User)
    assert u.to_dict() == raw


def test_metamorphic_extra_field_monotone() -> None:
    ok = {"name": "a", "age": 1}
    _v().parse(ok, User)  # accepts
    with pytest.raises(ValidationError):
        _v().parse({**ok, "extra": 1}, User)  # rejects


def test_metamorphic_bound_shrink_monotone() -> None:
    class Loose(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"name": SchemaField(type_=str, max_length=8)}

    class Tight(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"name": SchemaField(type_=str, max_length=3)}

    payload = {"name": "abcd"}
    _v().parse(payload, Loose)  # accepts under loose bound
    with pytest.raises(ValidationError):
        _v().parse(payload, Tight)  # rejects under tight bound


def test_metamorphic_order_independence() -> None:
    v = _v()
    a = v.parse({"name": "x", "age": 1}, User)
    b = v.parse({"age": 1, "name": "x"}, User)
    assert a.to_dict() == b.to_dict()


def test_metamorphic_determinism() -> None:
    v = _v()
    raw = {"name": "x", "age": 1}
    results = [v.parse(raw, User).to_dict() for _ in range(32)]
    assert all(r == results[0] for r in results)


def test_differential_coerce_toggle() -> None:
    class Strict(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"n": SchemaField(type_=int)}

    class Loose(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"n": SchemaField(type_=int, allow_coerce=True)}

    raw = {"n": "42"}
    with pytest.raises(ValidationError):
        _v().parse(raw, Strict)
    u = _v().parse(raw, Loose)
    assert u.n == 42


def test_metamorphic_idempotent_on_parsed_dict() -> None:
    # Re-parsing the dict form of a parsed result yields the same structure.
    raw = {"name": "x", "age": 1}
    v = _v()
    first = v.parse(raw, User)
    second = v.parse(first.to_dict(), User)
    assert first.to_dict() == second.to_dict()
