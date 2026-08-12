"""Unit tests for InputValidator — three per invariant."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from InputValidator import (
    MAX_STRING_LEN,
    SchemaField,
    SchemaModel,
    SchemaValidator,
    ValidationError,
    list_of,
)


class UserCreate(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "name": SchemaField(type_=str, min_length=1, max_length=64),
        "age": SchemaField(type_=int, min_value=0, max_value=150),
    }


class UserCreateExtrasAllowed(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "name": SchemaField(type_=str, min_length=1, max_length=64),
    }
    __extra__ = "allow"


class Nested(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "tags": SchemaField(type_=list_of(str), max_length=4),
        "owner": SchemaField(type_=UserCreate),
    }


def _v() -> SchemaValidator:
    return SchemaValidator()


# ---------------------------------------------------------------------------
# IV_INV_01 — unknown fields rejected unless opted-in
# ---------------------------------------------------------------------------
def test_inv_unknown_fields_confirms() -> None:
    u = _v().parse({"name": "alice", "age": 30}, UserCreate)
    assert u.name == "alice" and u.age == 30


def test_inv_unknown_fields_prevents() -> None:
    with pytest.raises(ValidationError) as err:
        _v().parse({"name": "alice", "age": 30, "role": "admin"}, UserCreate)
    assert err.value.field_path == "role"
    assert err.value.reason == "unknown_field"


def test_inv_unknown_fields_under_failure() -> None:
    # Schema opts in via __extra__ = "allow"; extras are tolerated but known
    # declared fields still parse strictly.
    u = _v().parse({"name": "bob", "uninvited": 1}, UserCreateExtrasAllowed)
    assert u.name == "bob"


# ---------------------------------------------------------------------------
# IV_INV_02 — length/range/pattern bounds enforced pre-business
# ---------------------------------------------------------------------------
def test_inv_bounds_enforced_confirms() -> None:
    u = _v().parse({"name": "a", "age": 0}, UserCreate)
    assert u.age == 0


def test_inv_bounds_enforced_prevents() -> None:
    for bad in (
        ({"name": "", "age": 1}, "string_min_length_violated"),
        ({"name": "x" * 65, "age": 1}, "string_max_length_exceeded"),
        ({"name": "ok", "age": -1}, "min_value_violated"),
        ({"name": "ok", "age": 999}, "max_value_exceeded"),
    ):
        raw, reason = bad
        with pytest.raises(ValidationError) as err:
            _v().parse(raw, UserCreate)
        assert err.value.reason == reason


def test_inv_bounds_enforced_under_failure() -> None:
    # Unbounded string at schema level is still capped by the global MAX_STRING_LEN.
    class Free(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"blob": SchemaField(type_=str)}

    oversize = "x" * (MAX_STRING_LEN + 1)
    with pytest.raises(ValidationError) as err:
        _v().parse({"blob": oversize}, Free)
    assert err.value.reason == "string_max_length_exceeded"


# ---------------------------------------------------------------------------
# IV_INV_03 — narrowing coercion only; widening requires opt-in
# ---------------------------------------------------------------------------
class CoerceSchema(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "n": SchemaField(type_=int, allow_coerce=True, min_value=0, max_value=10_000),
    }


class WidenSchema(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "sid": SchemaField(type_=str, allow_widen=True, max_length=32),
    }


def test_inv_narrowing_coercion_confirms() -> None:
    u = _v().parse({"n": "42"}, CoerceSchema)
    assert u.n == 42


def test_inv_narrowing_coercion_prevents() -> None:
    # Non-digits-only strings MUST NOT coerce.
    for bad_val in ("12a", "1.5", "0x10", " 12", "12 ", "", "--1"):
        with pytest.raises(ValidationError):
            _v().parse({"n": bad_val}, CoerceSchema)

    # Without allow_coerce, even digit strings MUST NOT coerce.
    class Strict(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"n": SchemaField(type_=int)}

    with pytest.raises(ValidationError) as err:
        _v().parse({"n": "42"}, Strict)
    assert err.value.reason == "expected_int"


def test_inv_narrowing_coercion_under_failure() -> None:
    # Widening (int -> str) MUST require explicit opt-in.
    class NoWiden(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"sid": SchemaField(type_=str)}

    with pytest.raises(ValidationError) as err:
        _v().parse({"sid": 12345}, NoWiden)
    assert err.value.reason == "widening_coercion_not_allowed"

    # With opt-in, it works.
    u = _v().parse({"sid": 12345}, WidenSchema)
    assert u.sid == "12345"


# ---------------------------------------------------------------------------
# IV_INV_04 — typed error with field path; no attacker content leaked
# ---------------------------------------------------------------------------
def test_inv_field_path_error_confirms() -> None:
    with pytest.raises(ValidationError) as err:
        _v().parse({"name": "ok", "age": "not-a-number"}, UserCreate)
    assert err.value.field_path == "age"
    assert isinstance(err.value, ValueError)


def test_inv_field_path_error_prevents() -> None:
    # The offending value itself MUST NOT be embedded in the error. Force a
    # validation failure by exceeding max_length (=64 on `name`) so we can
    # inspect the error message. Using a repeated payload keeps the attack
    # pattern visible in `attacker` without a length escape.
    payload = "DROP TABLE users;--<script>alert(1)</script>"
    attacker = payload * 3  # 132 chars, exceeds max_length=64 → ValidationError
    with pytest.raises(ValidationError) as err:
        _v().parse({"name": attacker, "age": 1}, UserCreate)
    msg = str(err.value)
    assert payload not in msg
    assert "DROP TABLE" not in msg
    assert "<script>" not in msg


def test_inv_field_path_error_under_failure() -> None:
    # Nested path reported with dotted location.
    with pytest.raises(ValidationError) as err:
        _v().parse(
            {"tags": ["ok"], "owner": {"name": "a", "age": "bad"}},
            Nested,
        )
    assert err.value.field_path == "owner.age"


# ---------------------------------------------------------------------------
# IV_INV_05 — depth and collection size bounded
# ---------------------------------------------------------------------------
class DeepHolder(SchemaModel):
    pass


# Build nested schema manually below using SchemaField with __fields__.


def _build_deep_schema(levels: int) -> type[SchemaModel]:
    """Construct N nested SchemaModel classes — inner first."""
    last: type[SchemaModel] | None = None
    for i in range(levels):
        fields: Mapping[str, SchemaField] = (
            {"leaf": SchemaField(type_=int)}
            if last is None
            else {"child": SchemaField(type_=last)}
        )
        new = type(f"Level{i}", (SchemaModel,), {"__fields__": fields})
        last = new
    assert last is not None
    return last


def test_inv_bounded_depth_size_confirms() -> None:
    Schema = _build_deep_schema(3)
    # Build {"child": {"child": {"leaf": 1}}}
    payload: dict[str, object] = {"leaf": 1}
    for _ in range(2):
        payload = {"child": payload}
    u = _v().parse(payload, Schema)
    assert u is not None


def test_inv_bounded_depth_size_prevents() -> None:
    # Oversize collection at the list level.
    class WithList(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {
            "xs": SchemaField(type_=list_of(int), max_length=3),
        }

    with pytest.raises(ValidationError) as err:
        _v().parse({"xs": [1, 2, 3, 4]}, WithList)
    assert err.value.reason == "list_max_length_exceeded"


def test_inv_bounded_depth_size_under_failure() -> None:
    # Depth far beyond MAX_DEPTH MUST be rejected, never recursed to completion.
    levels = 32  # > MAX_DEPTH == 16
    Schema = _build_deep_schema(levels)
    payload: dict[str, object] = {"leaf": 1}
    for _ in range(levels - 1):
        payload = {"child": payload}
    with pytest.raises(ValidationError) as err:
        _v().parse(payload, Schema)
    assert err.value.reason in ("max_depth_exceeded", "payload_node_budget_exceeded")


# ---------------------------------------------------------------------------
# Construction and registration invariants
# ---------------------------------------------------------------------------
def test_schema_must_be_subclass() -> None:
    with pytest.raises(ValidationError):
        _v().parse({}, int)  # type: ignore[arg-type]  # intentional bad schema — proves IV_INV_01 guardrail


def test_root_must_be_mapping() -> None:
    with pytest.raises(ValidationError) as err:
        _v().parse([1, 2, 3], UserCreate)
    assert err.value.reason == "expected_mapping"


def test_non_string_field_name_rejected() -> None:
    with pytest.raises(ValidationError):
        _v().parse({1: "x"}, UserCreate)  # type: ignore[dict-item]  # int key — must reject per IV_INV_01
