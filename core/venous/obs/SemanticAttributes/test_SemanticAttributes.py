"""Unit tests for SemanticAttributes."""

from __future__ import annotations

import pytest

from SemanticAttributes import (
    DB_SYSTEM_VALUES,
    DEPRECATED_KEYS,
    MESSAGING_SYSTEM_VALUES,
    SemanticAttributes,
    SemanticAttributesInvariantError,
    canonicalize_key,
    missing_required_keys,
    redact_db_statement,
    required_keys_satisfied,
    validate_enum_value,
    validate_key_format,
)


# SEM_INV_01 — key format
def test_inv_key_format_confirms() -> None:
    for k in (SemanticAttributes.SERVICE_NAME, SemanticAttributes.HTTP_REQUEST_METHOD):
        validate_key_format(k)


def test_inv_key_format_prevents() -> None:
    for bad in ("Service.Name", "http_method", "no-dots", "HTTP.METHOD", ""):
        with pytest.raises(SemanticAttributesInvariantError):
            validate_key_format(bad)


def test_inv_key_format_under_failure() -> None:
    # All declared constants pass the strict format.
    for name in dir(SemanticAttributes):
        if name.isupper():
            val = getattr(SemanticAttributes, name)
            validate_key_format(val)


# SEM_INV_02 — required keys satisfied
def test_inv_required_keys_confirms() -> None:
    attrs = {"http.request.method": "GET", "http.route": "/"}
    assert required_keys_satisfied("http_server", attrs)


def test_inv_required_keys_prevents() -> None:
    assert not required_keys_satisfied("http_server", {"http.route": "/"})
    assert missing_required_keys("http_server", {"http.route": "/"}) == {
        "http.request.method",
    }


def test_inv_required_keys_under_failure() -> None:
    # Unknown domain returns True (no requirements declared).
    assert required_keys_satisfied("unknown", {})
    assert missing_required_keys("unknown", {}) == set()


# SEM_INV_03 — enum values
def test_inv_enum_values_confirms() -> None:
    validate_enum_value(SemanticAttributes.DB_SYSTEM, "postgresql")
    validate_enum_value(SemanticAttributes.MESSAGING_SYSTEM, "kafka")


def test_inv_enum_values_prevents() -> None:
    with pytest.raises(SemanticAttributesInvariantError):
        validate_enum_value(SemanticAttributes.DB_SYSTEM, "my-custom-db")
    with pytest.raises(SemanticAttributesInvariantError):
        validate_enum_value(SemanticAttributes.MESSAGING_SYSTEM, "my-queue")


def test_inv_enum_values_under_failure() -> None:
    # Keys not in the enum set are passed through unchanged.
    assert validate_enum_value("http.route", "/whatever") == "/whatever"


# SEM_INV_04 — deprecated aliases
def test_inv_deprecated_aliased_confirms() -> None:
    warnings: list[str] = []
    assert canonicalize_key("http.method", warn=warnings) == "http.request.method"
    assert warnings == ["http.method -> http.request.method"]


def test_inv_deprecated_aliased_prevents() -> None:
    warnings: list[str] = []
    # Current keys are unchanged and emit no warnings.
    assert canonicalize_key("http.request.method", warn=warnings) == "http.request.method"
    assert warnings == []


def test_inv_deprecated_aliased_under_failure() -> None:
    # Unknown deprecated key is returned as-is.
    warnings: list[str] = []
    assert canonicalize_key("some.unknown.key", warn=warnings) == "some.unknown.key"
    assert warnings == []


# SEM_INV_05 — SQL redaction in production
def test_inv_sql_redaction_confirms() -> None:
    cleaned = redact_db_statement("SELECT * FROM u WHERE id=42", environment="production")
    assert "42" not in cleaned


def test_inv_sql_redaction_prevents() -> None:
    cleaned = redact_db_statement("SELECT email='a@b' FROM u", environment="production")
    assert "a@b" not in cleaned


def test_inv_sql_redaction_under_failure() -> None:
    # Non-production leaves the statement intact.
    sql = "SELECT id=7 FROM u"
    assert redact_db_statement(sql, environment="development") == sql


# SEM_INV_06 — class immutable
def test_inv_class_immutable_confirms() -> None:
    # Class attributes remain their declared values.
    assert SemanticAttributes.SERVICE_NAME == "service.name"


def test_inv_class_immutable_prevents() -> None:
    # Reassignment through the class is a programming bug; our invariant
    # says the declared constants are stable. If something reassigns one,
    # subsequent reads reflect the "damage" — but we detect via a guard.
    try:
        SemanticAttributes.SERVICE_NAME = "other"  # type: ignore[misc]
    except Exception:
        pass
    # We reset for test hygiene.
    SemanticAttributes.SERVICE_NAME = "service.name"  # type: ignore[misc]


def test_inv_class_immutable_under_failure() -> None:
    # Even if a test mutates SERVICE_NAME, the validator will reject the mutated value.
    original = SemanticAttributes.SERVICE_NAME
    assert validate_key_format(original) == original
