"""Behavioral scenarios for SemanticAttributes."""

from __future__ import annotations

import pytest

from SemanticAttributes import (
    SemanticAttributes,
    SemanticAttributesInvariantError,
    canonicalize_key,
    missing_required_keys,
    redact_db_statement,
    required_keys_satisfied,
    validate_enum_value,
)


def test_scenario_annotate_http_span() -> None:
    attrs = {
        SemanticAttributes.HTTP_REQUEST_METHOD: "GET",
        SemanticAttributes.HTTP_ROUTE: "/checkout",
        SemanticAttributes.HTTP_RESPONSE_STATUS_CODE: 200,
    }
    assert required_keys_satisfied("http_server", attrs)


def test_scenario_missing_db_system_rejected() -> None:
    assert not required_keys_satisfied("db_client", {"db.statement": "SELECT"})


def test_scenario_enum_value_enforced_for_db() -> None:
    validate_enum_value(SemanticAttributes.DB_SYSTEM, "postgresql")
    with pytest.raises(SemanticAttributesInvariantError):
        validate_enum_value(SemanticAttributes.DB_SYSTEM, "my-special-db")


def test_scenario_deprecated_alias_emits_warning() -> None:
    warnings: list[str] = []
    current = canonicalize_key("http.method", warn=warnings)
    assert current == "http.request.method"
    assert warnings


def test_scenario_production_sql_redaction() -> None:
    sql = "SELECT * FROM orders WHERE id=42 AND email='a@b'"
    redacted = redact_db_statement(sql, environment="production")
    assert "42" not in redacted
    assert "a@b" not in redacted


def test_scenario_dev_environment_preserves_sql() -> None:
    sql = "SELECT id=42 FROM users"
    assert redact_db_statement(sql, environment="development") == sql
