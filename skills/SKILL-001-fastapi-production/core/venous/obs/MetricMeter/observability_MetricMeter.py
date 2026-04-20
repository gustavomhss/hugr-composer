"""Observability harness for MetricMeter."""

from __future__ import annotations

import json
from pathlib import Path

from MetricMeter import InMemoryMetricMeter


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert schema["logs"] and schema["metrics"] and schema["spans"]


def test_observability_meter_counts_instruments() -> None:
    m = InMemoryMetricMeter()
    m.counter("a", unit="1", description="d")
    m.histogram("b", unit="ms", description="d")
    assert set(m.instruments.keys()) == {"a", "b"}


def test_observability_schema_has_cardinality_bounds() -> None:
    for metric in _load_schema()["metrics"]:
        assert isinstance(metric["cardinality_bound"], int)


def test_observability_span_ops_match_catalog() -> None:
    span_ops = {s["operation_name"] for s in _load_schema()["spans"]}
    assert "metric.instrument.create" in span_ops


def test_observability_log_events_have_required_attributes() -> None:
    for log in _load_schema()["logs"]:
        attrs = log["required_attributes"]
        assert isinstance(attrs, list) and attrs


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for metric in _load_schema()["metrics"]:
        assert metric["metric_type"] in valid
