"""Observability harness for CardinalityGuard."""

from __future__ import annotations

import json
from pathlib import Path

from CardinalityGuard import InMemoryCardinalityGuard


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shape() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_overflow_counter_declared() -> None:
    names = {m["name"] for m in _schema()["metrics"]}
    assert "cardinality.overflow.count" in names


def test_observability_span_ops_present() -> None:
    ops = {s["operation_name"] for s in _schema()["spans"]}
    assert "cardinality.admit" in ops


def test_observability_guard_emits_overflow_counter_value() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=1)
    g.admit("m", {"k": "v"})
    g.admit("m", {"k": "v2"})
    assert g.stats("m")["overflow_events"] == 1


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_events_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()
