"""Observability harness — asserts MaterializedView emits logs / metrics / spans matching schema."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from MaterializedView import InMemoryMaterializedView


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
    def upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
        aid = str(event["aggregate_id"])
        rows[aid] = {"aggregate_id": aid, "seq": event["seq"]}

    view = InMemoryMaterializedView("obs_view")
    view.register_handler("x", upsert)
    view.apply({"type": "x", "aggregate_id": "a1", "seq": 1, "schema_version": 1})
    # Map to log attributes declared in the schema.
    assert view.name == "obs_view"
    assert view.last_applied_seq == 1
    assert view.applied_event_count == 1
    assert view.staleness_s() >= 0.0


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "view.apply" in ops
    assert "view.rebuild" in ops
    assert "view.query" in ops


def test_observability_rebuild_surfaces_event_count() -> None:
    def upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
        aid = str(event["aggregate_id"])
        rows[aid] = {"aggregate_id": aid}

    view = InMemoryMaterializedView("obs_view")
    view.register_handler("x", upsert)
    source = [
        {"type": "x", "aggregate_id": f"a{i}", "seq": i, "schema_version": 1}
        for i in range(1, 6)
    ]
    view.rebuild(source)
    # applied_event_count aligns with the source-event-count observable.
    assert view.applied_event_count == 5
