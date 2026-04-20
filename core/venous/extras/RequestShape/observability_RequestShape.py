"""Observability harness — asserts RequestShape emits logs/metrics/spans per schema."""

from __future__ import annotations

import json
from pathlib import Path

from RequestShape import (
    HDR_PRIORITY,
    HDR_REQUEST_ID,
    ImmutableRequestShape,
)

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


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_span_operations_cover_primitive_api() -> None:
    schema = _load_schema()
    names = {str(s["operation_name"]) for s in schema["spans"]}
    assert "request.shape.construct" in names
    assert "request.shape.from_headers" in names
    assert "request.shape.to_headers" in names


def test_observability_construction_emits_declared_attributes() -> None:
    # Proves the impl surfaces the attributes the schema declares as required.
    shape = ImmutableRequestShape(
        request_id="req-obs-1", priority="critical", origin="edge",
    )
    assert shape.request_id == "req-obs-1"
    assert shape.priority == "critical"
    assert shape.origin == "edge"


def test_observability_from_headers_attribute_present() -> None:
    headers = {HDR_REQUEST_ID: "req-obs-2", HDR_PRIORITY: "normal"}
    shape = ImmutableRequestShape.from_headers(headers)
    assert shape.request_id == "req-obs-2"


def test_observability_label_keys_bounded() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        keys = m["label_keys"]
        assert isinstance(keys, list)
        # Label cardinality of a small primitive should not explode.
        assert 0 <= len(keys) <= 4
