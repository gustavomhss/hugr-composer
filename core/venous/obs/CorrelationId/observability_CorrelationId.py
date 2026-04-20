"""Observability harness for CorrelationId."""

from __future__ import annotations

import json
from pathlib import Path

from CorrelationId import extract, generate, inject

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shapes_ok() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_extract_span_named() -> None:
    ops = {x["operation_name"] for x in _schema()["spans"]}
    assert "correlation_id.extract" in ops
    assert "correlation_id.inject" in ops


def test_observability_metrics_bounded_cardinality() -> None:
    for m in _schema()["metrics"]:
        bound = m["cardinality_bound"]
        assert isinstance(bound, int)
        assert bound <= 10_000


def test_observability_log_events_are_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_runtime_id_present_on_every_outbound() -> None:
    cid = generate()
    out = inject(cid)
    assert out["x-request-id"] == cid


def test_observability_extract_then_inject_preserves_id() -> None:
    headers = {"x-request-id": "0123456789abcdef0123456789abcdef"}
    cid = extract(headers)
    out = inject(cid)
    assert out["x-request-id"] == headers["x-request-id"]


def test_observability_metric_types_valid() -> None:
    for m in _schema()["metrics"]:
        assert m["metric_type"] in {"counter", "gauge", "histogram", "updown_counter"}
