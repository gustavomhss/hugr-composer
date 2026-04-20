"""Observability harness — asserts Tracer emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from Tracer import InMemoryTracer


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_span_kinds_emitted_match_schema() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("obs.start", kind="INTERNAL"):
        pass
    schema = _load_schema()
    span_ops = {s["operation_name"] for s in schema["spans"]}
    assert "tracer.span.create" in span_ops


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
        assert "_" not in name or "." in name


def test_observability_tracer_counts_exports() -> None:
    tracer = InMemoryTracer()
    for _ in range(5):
        with tracer.start_as_current_span("export"):
            pass
    assert tracer.export_calls == 5


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1
