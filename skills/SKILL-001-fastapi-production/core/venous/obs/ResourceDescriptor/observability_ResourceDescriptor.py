"""Observability harness for ResourceDescriptor."""

from __future__ import annotations

import json
from pathlib import Path


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shape() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_initialization_span_declared() -> None:
    ops = {s["operation_name"] for s in _schema()["spans"]}
    assert "resource.initialize" in ops


def test_observability_log_events_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_cardinality_bounded() -> None:
    for m in _schema()["metrics"]:
        assert m["cardinality_bound"] <= 1_000_000


def test_observability_rejection_counter_declared() -> None:
    names = {m["name"] for m in _schema()["metrics"]}
    assert "resource.rejections" in names
