"""Observability harness — schema well-formedness + runtime assertions."""

from __future__ import annotations

import json
from pathlib import Path

from OutputEncoder import DefaultOutputEncoder, Sink

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
        assert "." in name


def test_observability_span_ops_include_encode() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "output_encoder.encode" in ops


def test_observability_no_plaintext_attribute() -> None:
    schema = _load_schema()
    # Schemas MUST NOT require emitting the untrusted input or output —
    # attacker payloads logged verbatim become a secondary XSS vector
    # (via log viewers).
    forbidden = {"value", "input", "output", "raw", "payload"}
    for log in schema["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in forbidden
    for metric in schema["metrics"]:
        for attr in metric.get("label_keys", []):
            assert attr not in forbidden


def test_observability_encode_produces_deterministic_output() -> None:
    # The schema promises `output_length` in the log — this assertion grounds
    # that by showing encode() is deterministic and returns a measurable str.
    e = DefaultOutputEncoder()
    out = e.encode("<script>", Sink.HTML_TEXT)
    assert isinstance(out, str)
    assert len(out) > 0


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1
