"""Observability harness for TelemetryExporter."""

from __future__ import annotations

import json
from pathlib import Path

from TelemetryExporter import InMemoryTelemetryExporter


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shape() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_export_counter_exists() -> None:
    names = {m["name"] for m in _schema()["metrics"]}
    assert "exporter.export.count" in names


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_span_ops_present() -> None:
    ops = {s["operation_name"] for s in _schema()["spans"]}
    assert "exporter.export" in ops


def test_observability_counters_tracked_on_export() -> None:
    ex = InMemoryTelemetryExporter()
    ex.export([{"x": 1}], timeout_s=1.0)
    assert sum(ex.counter.values()) > 0


def test_observability_log_events_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()
