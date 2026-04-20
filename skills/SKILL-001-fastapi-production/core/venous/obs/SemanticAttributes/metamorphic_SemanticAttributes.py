"""Metamorphic + differential for SemanticAttributes."""

from __future__ import annotations

from SemanticAttributes import (
    DEPRECATED_KEYS,
    SemanticAttributes,
    canonicalize_key,
    missing_required_keys,
    redact_db_statement,
    validate_key_format,
)


def test_metamorphic_canonicalize_idempotent() -> None:
    for deprecated, current in DEPRECATED_KEYS.items():
        warn: list[str] = []
        step1 = canonicalize_key(deprecated, warn=warn)
        step2 = canonicalize_key(step1, warn=warn)
        assert step1 == step2 == current


def test_metamorphic_validate_key_stable() -> None:
    for name in dir(SemanticAttributes):
        if not name.isupper():
            continue
        val = getattr(SemanticAttributes, name)
        for _ in range(5):
            assert validate_key_format(val) == val


def test_metamorphic_redact_sql_stable_non_prod() -> None:
    sql = "SELECT 1"
    for _ in range(5):
        assert redact_db_statement(sql, environment="staging") == sql


def test_metamorphic_missing_keys_equals_requirement_minus_given() -> None:
    m = missing_required_keys("http_server", {"http.request.method": "GET"})
    assert m == {"http.route"}


def test_differential_sql_redaction_hides_numbers_and_strings() -> None:
    sql = "UPDATE u SET name='alice' WHERE id=7"
    redacted = redact_db_statement(sql, environment="production")
    assert "7" not in redacted
    assert "alice" not in redacted


def test_metamorphic_keys_are_lowercase_dotted() -> None:
    # Every declared Final[str] satisfies the regex.
    for name in dir(SemanticAttributes):
        if not name.isupper():
            continue
        val = getattr(SemanticAttributes, name)
        assert validate_key_format(val)
