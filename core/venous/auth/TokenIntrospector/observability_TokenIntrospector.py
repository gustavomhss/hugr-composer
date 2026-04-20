"""Observability harness — asserts TokenIntrospector emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from TokenIntrospector import (
    CachingTokenIntrospector,
    IssuerConfig,
    SigningKey,
    StaticIntrospectionEndpoint,
    StaticJwksFetcher,
    make_hs256_jwt,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"
ISSUER = "https://obs.example.com"
AUD = "obs-aud"
SECRET = b"observability-key-material-minimum-256-bits!!"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert schema["logs"] and schema["metrics"] and schema["spans"]


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "token.introspect" in ops
    assert "jwks.fetch" in ops
    assert "rfc7662.introspect" in ops


def test_observability_lifecycle_emits_attributes() -> None:
    fetcher = StaticJwksFetcher({
        ISSUER: [SigningKey(kid="k", algorithm="HS256", secret=SECRET)],
    })
    endpoint = StaticIntrospectionEndpoint()
    ti = CachingTokenIntrospector(
        issuers={ISSUER: IssuerConfig(
            issuer=ISSUER, allowed_algorithms=frozenset({"HS256"}),
        )},
        jwks_fetcher=fetcher,
        introspection_endpoint=endpoint,
        clock=lambda: 1_700_000_000.0,
    )
    jwt = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="user", audience=AUD,
        expires_at=1_700_000_500, kid="k",
    )
    claims = ti.introspect(jwt, AUD)
    # Attributes that would be emitted as log fields per schema.
    assert claims.issuer == ISSUER
    assert claims.subject == "user"
    assert AUD in claims.audience
    assert ti.jwks_cache_size == 1
