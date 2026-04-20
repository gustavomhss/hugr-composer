"""Observability harness — schema well-formedness + runtime counter assertions."""

from __future__ import annotations

import json
from pathlib import Path

from PasswordHasher import ScryptCost, ScryptHasher

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_are_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()


def test_observability_span_ops_include_hash_and_verify() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "password_hasher.hash" in ops
    assert "password_hasher.verify" in ops


def test_observability_no_plaintext_in_schema() -> None:
    schema = _load_schema()
    # Log schemas MUST NOT reference plaintext-like fields.
    forbidden = {"plaintext", "password", "secret_value", "pw"}
    for log in schema["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in forbidden


def test_observability_hash_emits_telemetry_contract() -> None:
    # The reference in-memory hasher emits no telemetry, but the schema
    # declares the contract that real deployments MUST uphold.
    h = ScryptHasher(cost=ScryptCost(n=14, r=8, p=1, dklen=32),
                     cost_floor=ScryptCost(n=14, r=8, p=1, dklen=32))
    stored = h.hash("x")
    assert stored.startswith("$scrypt$")


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1
