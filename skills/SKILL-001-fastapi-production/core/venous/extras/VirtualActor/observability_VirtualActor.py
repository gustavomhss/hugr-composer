"""Observability harness — asserts VirtualActor emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_required_events_present() -> None:
    names = {log["event_name"] for log in _load_schema()["logs"]}
    assert "actor.invoke.enqueued" in names
    assert "actor.invoke.completed" in names


def test_observability_metric_types_are_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_span_names_dotted_lowercase() -> None:
    for s in _load_schema()["spans"]:
        n = str(s["operation_name"])
        assert n == n.lower()
        assert "." in n


def test_observability_cardinality_bounds_declared() -> None:
    for m in _load_schema()["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1
