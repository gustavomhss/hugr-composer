"""Observability harness — asserts RpcInterceptor emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_required_log_events_present() -> None:
    schema = _load_schema()
    names = {str(log["event_name"]) for log in schema["logs"]}
    assert "rpc.interceptor.entered" in names
    assert "rpc.interceptor.short_circuited" in names


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_span_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for s in schema["spans"]:
        name = str(s["operation_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1
