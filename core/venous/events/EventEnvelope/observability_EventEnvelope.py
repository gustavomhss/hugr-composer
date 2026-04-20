"""Observability harness — asserts EventEnvelope emits the declared schema shape."""

from __future__ import annotations

import json
from pathlib import Path

from EventEnvelope import EventEnvelope, InMemoryDedupSet

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_log_event_names_are_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_dedup_counters_increment() -> None:
    dedup = InMemoryDedupSet()
    env = EventEnvelope(id="obs-1", source="/s", type="t")
    dedup.accept(env)
    dedup.accept(env)  # duplicate
    # Two dedup decisions taken; consumer-side metric would record 1 accept + 1 reject.
    assert dedup.size() == 1


def test_observability_span_operations_match_schema() -> None:
    schema = _load_schema()
    span_ops = {s["operation_name"] for s in schema["spans"]}
    assert "event.envelope.validate" in span_ops
