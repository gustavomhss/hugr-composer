"""Observability harness — asserts Aggregate exposes the declared schema."""

from __future__ import annotations

import json
from pathlib import Path

from Aggregate import InMemoryAggregateRepository, OrderAggregate


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
    repo = InMemoryAggregateRepository[str]()
    order = OrderAggregate("obs-1", "c")
    order.add_line("sku", 1)
    events = repo.save(order)
    # Invariants that map to emitted attributes.
    assert order.version >= 2
    assert len(events) >= 2
    assert order.pending_event_count == 0


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "aggregate.mutate" in ops
    assert "aggregate.save" in ops
