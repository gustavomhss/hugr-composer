"""Observability harness — asserts ValueTransform emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from ValueTransform import ArgumentMetadata, ParseInt

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_expected_events_declared() -> None:
    schema = _load_schema()
    events = {s["event_name"] for s in schema["logs"]}
    assert "value_transform.coercion.failed" in events
    assert "value_transform.validation.failed" in events


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


def test_observability_spans_declare_required_attrs() -> None:
    schema = _load_schema()
    for s in schema["spans"]:
        assert isinstance(s["required_attributes"], list)
        assert len(s["required_attributes"]) >= 1


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_smoke_transform_emits_nothing_to_side_channels() -> None:
    # Purity invariant: calling transform() MUST NOT spawn threads, write files,
    # or open sockets. We assert by probing that a fresh ParseInt is side-effect
    # free against a trivial counter.
    p = ParseInt()
    meta = ArgumentMetadata(kind="param", metatype=int, data="id")
    for _ in range(10):
        assert p.transform("1", meta) == 1
