"""Behavioral end-to-end scenarios for InputValidator.

Each scenario simulates a real ingress handler exercising the primitive. The
assertions verify the runtime invariants hold under production-like payloads.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from InputValidator import (
    SchemaField,
    SchemaModel,
    SchemaValidator,
    ValidationError,
    list_of,
)


class OrderCreate(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "sku": SchemaField(type_=str, min_length=1, max_length=32, pattern=r"[A-Z0-9\-]+"),
        "quantity": SchemaField(type_=int, min_value=1, max_value=1000),
        "note": SchemaField(type_=str, required=False, max_length=256),
    }


def _v() -> SchemaValidator:
    return SchemaValidator()


def test_scenario_happy_path_ecommerce_order() -> None:
    raw = {"sku": "ABC-123", "quantity": 5, "note": "gift wrap"}
    o = _v().parse(raw, OrderCreate)
    assert o.sku == "ABC-123"
    assert o.quantity == 5


def test_scenario_attacker_injects_extra_field() -> None:
    # Attacker tries to mass-assign `is_admin` via unknown field.
    raw = {"sku": "ABC-123", "quantity": 1, "is_admin": True}
    with pytest.raises(ValidationError) as err:
        _v().parse(raw, OrderCreate)
    assert err.value.field_path == "is_admin"
    assert err.value.reason == "unknown_field"


def test_scenario_sql_injection_blocked_by_pattern() -> None:
    # SKU pattern forbids quote/semicolon/space → SQLi payload fails.
    raw = {"sku": "'; DROP TABLE orders;--", "quantity": 1}
    with pytest.raises(ValidationError) as err:
        _v().parse(raw, OrderCreate)
    # No attacker content leaked in the error.
    assert "DROP" not in str(err.value)
    assert err.value.field_path == "sku"


def test_scenario_oversize_payload_rejected_at_edge() -> None:
    big_note = "x" * 10_000
    raw = {"sku": "ABC", "quantity": 1, "note": big_note}
    with pytest.raises(ValidationError):
        _v().parse(raw, OrderCreate)


def test_scenario_nested_payload_happy_and_attack() -> None:
    class Address(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {
            "city": SchemaField(type_=str, max_length=64),
            "zip": SchemaField(type_=str, pattern=r"[0-9\-]{3,10}"),
        }

    class UserProfile(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {
            "email": SchemaField(type_=str, max_length=254, pattern=r"[^@\s]+@[^@\s]+"),
            "addresses": SchemaField(type_=list_of(Address), max_length=3),
        }

    raw_ok = {
        "email": "a@example.com",
        "addresses": [{"city": "NY", "zip": "10001"}],
    }
    _v().parse(raw_ok, UserProfile)

    raw_attack = {
        "email": "a@example.com",
        "addresses": [{"city": "NY", "zip": "10001", "country": "US"}],  # extra
    }
    with pytest.raises(ValidationError) as err:
        _v().parse(raw_attack, UserProfile)
    assert err.value.field_path == "addresses[0].country"


def test_scenario_type_confusion_attack_blocked() -> None:
    # Attacker sends a list where a dict is expected.
    with pytest.raises(ValidationError):
        _v().parse([{"sku": "A", "quantity": 1}], OrderCreate)


def test_scenario_unicode_bidi_override_blocked() -> None:
    # RTL override character U+202E mid-string — MUST be rejected.
    raw = {"sku": "A\u202eBC", "quantity": 1}
    with pytest.raises(ValidationError) as err:
        _v().parse(raw, OrderCreate)
    assert err.value.field_path == "sku"


def test_scenario_null_byte_injection_blocked() -> None:
    raw = {"sku": "ABC\x00stuff", "quantity": 1}
    with pytest.raises(ValidationError):
        _v().parse(raw, OrderCreate)
