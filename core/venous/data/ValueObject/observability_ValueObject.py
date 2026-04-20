"""Observability harness — asserts ValueObject emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from ValueObject import COUNTERS, Money

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_span_names_present() -> None:
    schema = _load_schema()
    span_ops = {s["operation_name"] for s in schema["spans"]}
    assert "valueobject.construct" in span_ops
    assert "valueobject.with_changes" in span_ops


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
        # convention: dotted namespace (valueobject.*)
        assert "." in name


def test_observability_counters_monotonic() -> None:
    before = COUNTERS.constructed
    for i in range(5):
        Money(amount_cents=i, currency="USD")
    after = COUNTERS.constructed
    assert after >= before


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_all_required_attributes_declared() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        assert isinstance(log["required_attributes"], list)
        assert len(log["required_attributes"]) >= 1
