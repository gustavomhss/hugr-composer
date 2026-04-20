"""Observability harness for AuditEvent."""

from __future__ import annotations

import json
from pathlib import Path

from AuditEvent import InMemoryAuditSink, build_event


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shape() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_chain_span_declared() -> None:
    ops = {s["operation_name"] for s in _schema()["spans"]}
    assert "audit.emit" in ops


def test_observability_metrics_valid_types() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_events_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_sink_emits_chain_stat() -> None:
    sink = InMemoryAuditSink()
    e = build_event(event_id="e1", actor_id="u", actor_type="h", action="READ",
                    resource_type="r", resource_id="1", outcome="success",
                    attributes={}, prev_hash="")
    sink.emit(e)
    assert len(sink.events) == 1


def test_observability_verify_failure_counter() -> None:
    names = {m["name"] for m in _schema()["metrics"]}
    assert "audit.chain.verify.failures" in names
