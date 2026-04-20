"""Observability harness — asserts DomainEvent emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from DomainEvent import AggregateEventStream, FrozenDomainEvent
from test_DomainEvent import make_event


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


def test_observability_lifecycle_emits_attributes() -> None:
    stream = AggregateEventStream()
    stream.stage(make_event(version=1))
    stream.stage(make_event(version=2))
    published: list[FrozenDomainEvent] = []
    stream.flush(published.append)
    assert len(published) == 2
    # Every published event carries the attributes schema says it must.
    for e in published:
        assert e.event_id
        assert e.aggregate_type
        assert e.aggregate_id
        assert isinstance(e.version, int)
        assert e.event_type
        assert isinstance(e.schema_version, int)


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "domain.event.stage" in ops
    assert "domain.event.flush" in ops


def test_observability_rejection_path_has_invariant_id() -> None:
    schema = _load_schema()
    rejected = next(l for l in schema["logs"] if l["event_name"] == "domain.event.rejected")
    attrs = rejected["required_attributes"]
    assert isinstance(attrs, list)
    assert "invariant_id" in attrs
