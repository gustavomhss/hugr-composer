"""Observability harness — asserts AuthorizationCodeFlow emits logs/metrics/spans per schema."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from AuthorizationCodeFlow import ProviderMetadata, create_flow

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"

_PROVIDER = ProviderMetadata(
    authorization_endpoint="https://op.example/authorize",
    token_endpoint="https://op.example/token",
    jwks_uri="https://op.example/jwks",
    code_challenge_methods_supported=("S256",),
)


def _ok_token(_req: Mapping[str, str]) -> Mapping[str, object]:
    return {
        "access_token": "A" * 32,
        "refresh_token": "R" * 32,
        "id_token": "I" * 32,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types_are_valid() -> None:
    s = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in s["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted_lowercase() -> None:
    s = _load_schema()
    for log in s["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_cardinality_bounds_declared() -> None:
    s = _load_schema()
    for m in s["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    s = _load_schema()
    ops = {str(sp["operation_name"]) for sp in s["spans"]}
    assert "acf.begin" in ops
    assert "acf.exchange" in ops


def test_observability_runtime_audit_emits_schema_events() -> None:
    # Exercise the flow and confirm the audit sink receives a begin event and
    # an exchange.success event with the exact attributes the schema declares.
    captured: list[Mapping[str, object]] = []

    def sink(e: Mapping[str, object]) -> None:
        captured.append(e)

    flow = create_flow(
        client_id="c",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
        audit_sink=sink,
    )
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="x", state=req.state, stored=req)

    event_names = [e["event_name"] for e in captured]
    assert "acf.begin" in event_names
    assert "acf.exchange.success" in event_names

    begin_event = next(e for e in captured if e["event_name"] == "acf.begin")
    for attr in ("state_hash", "nonce_hash", "scope_count"):
        assert attr in begin_event

    success_event = next(e for e in captured if e["event_name"] == "acf.exchange.success")
    for attr in ("state_hash", "code_hash", "token_response"):
        assert attr in success_event

    # ACF-INV-06: the audit token_response NEVER contains plaintext tokens.
    tr = success_event["token_response"]
    assert isinstance(tr, Mapping)
    assert tr["access_token"] == "[REDACTED_TOKEN]"
    assert tr["refresh_token"] == "[REDACTED_TOKEN]"
    assert tr["id_token"] == "[REDACTED_TOKEN]"
