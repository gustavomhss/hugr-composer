"""Observability harness for CorrelationContext."""

from __future__ import annotations

import json
from pathlib import Path

from CorrelationContext import InMemoryCorrelationContext


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shapes_ok() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_context_activation_span_named() -> None:
    ops = {x["operation_name"] for x in _schema()["spans"]}
    assert "correlation.activate" in ops


def test_observability_metrics_bounded_cardinality() -> None:
    for m in _schema()["metrics"]:
        assert m["cardinality_bound"] <= 10_000


def test_observability_log_events_are_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_runtime_context_emits_consistent_request_id() -> None:
    ctx = InMemoryCorrelationContext()
    with ctx.activate():
        first = InMemoryCorrelationContext.current().request_id
    # stable across reads
    assert first == ctx.request_id


def test_observability_metric_names_valid() -> None:
    for m in _schema()["metrics"]:
        assert m["metric_type"] in {"counter", "gauge", "histogram", "updown_counter"}
