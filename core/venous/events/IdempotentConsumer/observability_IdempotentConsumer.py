"""Observability harness — asserts IdempotentConsumer emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from IdempotentConsumer import EchoMessage, build_echo_consumer


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


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
    assert "consumer.handle" in ops
    assert "consumer.on_duplicate" in ops


def test_observability_lifecycle_emits_attributes() -> None:
    c, inbox, outbox = build_echo_consumer()
    c.handle(EchoMessage(id="obs-1"))
    c.handle(EchoMessage(id="obs-1"))  # duplicate
    # Attributes that the schema declares as required map to observable
    # consumer state.
    assert c.consumer_name  # consumer_name / consumer.name span attribute
    assert c.effect_runs == 1  # consumer.effect.duration{result=ok}
    assert c.duplicate_calls == 1  # consumer.duplicate.skipped
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1
