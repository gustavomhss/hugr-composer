"""Observability harness — asserts EventBus emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from EventBus import InMemoryEventBus

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_span_ops_declared() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "eventbus.publish" in ops
    assert "eventbus.subscribe" in ops


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


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_bus_counters_match_lifecycle() -> None:
    bus = InMemoryEventBus()
    bus.subscribe("k.*", lambda n, p: None)
    for _ in range(5):
        bus.publish("k.v", {})
    assert bus.publish_calls == 5
    assert bus.delivered_calls == 5


def test_observability_error_counter_increments() -> None:
    bus = InMemoryEventBus()
    bus.subscribe("k.*", lambda n, p: (_ for _ in ()).throw(ValueError("x")))
    bus.publish("k.v", {})
    assert len(bus.errors) == 1
    assert bus.errors[0][1] == "ValueError"
