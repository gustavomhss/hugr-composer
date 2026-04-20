"""Observability assertion harness for TamperEvidentAuditLog."""

from __future__ import annotations

import json
from pathlib import Path

from TamperEvidentAuditLog import HmacReferenceSigner, InMemoryTamperEvidentAuditLog


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_non_empty() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_append_span_declared() -> None:
    ops = {str(sp["operation_name"]) for sp in _schema()["spans"]}
    assert "teal.append" in ops and "teal.verify_chain" in ops


def test_observability_metrics_valid_types() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_events_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_append_increments_size() -> None:
    log = InMemoryTamperEvidentAuditLog(HmacReferenceSigner(b"o" * 32, "kid"))
    log.append("a", "READ", "r", "success", {})
    assert log.size == 1


def test_observability_verify_failure_counter_declared() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "teal.verify.failures" in names
