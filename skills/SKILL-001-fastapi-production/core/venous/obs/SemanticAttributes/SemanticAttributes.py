"""SemanticAttributes primitive — typed constants for OTel SemConv 1.27 keys.

Invariant IDs:

- SEM-INV-01: attribute keys MUST use lowercase dotted notation and SHALL NEVER be
  aliased to custom names.
- SEM-INV-02: required keys for a domain MUST be populated before a span ends.
- SEM-INV-03: enum values (db.system, messaging.system) MUST come from the
  SemConv registry, CANNOT be free-form.
- SEM-INV-04: deprecated keys SHALL be aliased to the current key with a one-time
  warning, NEVER silently dropped.
- SEM-INV-05: db.statement MUST be redacted in production; literal parameter values
  are FORBIDDEN.
- SEM-INV-06: SemanticAttributes class keys are immutable at runtime.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


class SemanticAttributesInvariantError(ValueError):
    """Runtime invariant violation."""


class SemanticAttributes:
    """Typed constants for OpenTelemetry Semantic Conventions 1.27."""

    SERVICE_NAME: Final[str] = "service.name"
    SERVICE_VERSION: Final[str] = "service.version"
    DEPLOYMENT_ENVIRONMENT: Final[str] = "deployment.environment.name"
    HTTP_REQUEST_METHOD: Final[str] = "http.request.method"
    HTTP_ROUTE: Final[str] = "http.route"
    HTTP_RESPONSE_STATUS_CODE: Final[str] = "http.response.status_code"
    DB_SYSTEM: Final[str] = "db.system"
    DB_STATEMENT: Final[str] = "db.statement"
    MESSAGING_SYSTEM: Final[str] = "messaging.system"
    MESSAGING_DESTINATION_NAME: Final[str] = "messaging.destination.name"
    GEN_AI_SYSTEM: Final[str] = "gen_ai.system"
    GEN_AI_REQUEST_MODEL: Final[str] = "gen_ai.request.model"
    GEN_AI_USAGE_INPUT_TOKENS: Final[str] = "gen_ai.usage.input_tokens"
    GEN_AI_USAGE_OUTPUT_TOKENS: Final[str] = "gen_ai.usage.output_tokens"


# SEM-INV-03: SemConv enum values for key-typed attributes.
DB_SYSTEM_VALUES: Final[frozenset[str]] = frozenset({
    "postgresql", "mysql", "mariadb", "sqlite", "mssql", "oracle",
    "redis", "mongodb", "cassandra", "dynamodb", "clickhouse",
})
MESSAGING_SYSTEM_VALUES: Final[frozenset[str]] = frozenset({
    "kafka", "rabbitmq", "aws_sqs", "aws_sns", "gcp_pubsub", "azure_servicebus",
    "redis", "nats",
})

# SEM-INV-04: deprecated → current alias table.
DEPRECATED_KEYS: Final[dict[str, str]] = {
    "http.method": "http.request.method",
    "http.status_code": "http.response.status_code",
    "db.sql": "db.statement",
}

# SEM-INV-02: required keys per domain.
REQUIRED_KEYS_BY_DOMAIN: Final[dict[str, frozenset[str]]] = {
    "http_server": frozenset({"http.request.method", "http.route"}),
    "db_client": frozenset({"db.system"}),
    "messaging_producer": frozenset({"messaging.system", "messaging.destination.name"}),
}


def validate_key_format(key: str) -> str:
    """SEM-INV-01: keys must use lowercase.dotted notation."""
    if not isinstance(key, str) or not KEY_PATTERN.match(key):
        raise SemanticAttributesInvariantError(
            f"SEM-INV-01: key {key!r} MUST match lowercase dotted notation."
        )
    return key


def validate_enum_value(key: str, value: str) -> str:
    """SEM-INV-03: enum values come from the SemConv registry."""
    if key == SemanticAttributes.DB_SYSTEM:
        if value not in DB_SYSTEM_VALUES:
            raise SemanticAttributesInvariantError(
                f"SEM-INV-03: db.system value {value!r} CANNOT be free-form; "
                f"choose from {sorted(DB_SYSTEM_VALUES)}."
            )
    elif key == SemanticAttributes.MESSAGING_SYSTEM:
        if value not in MESSAGING_SYSTEM_VALUES:
            raise SemanticAttributesInvariantError(
                f"SEM-INV-03: messaging.system value {value!r} CANNOT be free-form."
            )
    return value


def canonicalize_key(key: str, *, warn: list[str] | None = None) -> str:
    """SEM-INV-04: deprecated keys → current keys, with warning recorded."""
    if key in DEPRECATED_KEYS:
        current = DEPRECATED_KEYS[key]
        if warn is not None:
            warn.append(f"{key} -> {current}")
        return current
    return key


def required_keys_satisfied(domain: str, attributes: Mapping[str, object]) -> bool:
    """SEM-INV-02: all required keys for the domain are present."""
    req = REQUIRED_KEYS_BY_DOMAIN.get(domain)
    if not req:
        return True
    return req.issubset(attributes.keys())


def missing_required_keys(domain: str, attributes: Mapping[str, object]) -> set[str]:
    req = REQUIRED_KEYS_BY_DOMAIN.get(domain, frozenset())
    return set(req) - set(attributes.keys())


def redact_db_statement(statement: str, *, environment: str) -> str:
    """SEM-INV-05: in production, strip literal parameter values from SQL."""
    if environment.lower() != "production":
        return statement
    # Replace literal values after VALUES(...) and quoted strings; coarse redaction.
    cleaned = re.sub(r"'[^']*'", "?", statement)
    cleaned = re.sub(r"\b\d+\b", "?", cleaned)
    return cleaned


__all__ = [
    "DB_SYSTEM_VALUES",
    "DEPRECATED_KEYS",
    "KEY_PATTERN",
    "MESSAGING_SYSTEM_VALUES",
    "REQUIRED_KEYS_BY_DOMAIN",
    "SemanticAttributes",
    "SemanticAttributesInvariantError",
    "canonicalize_key",
    "missing_required_keys",
    "redact_db_statement",
    "required_keys_satisfied",
    "validate_enum_value",
    "validate_key_format",
]
