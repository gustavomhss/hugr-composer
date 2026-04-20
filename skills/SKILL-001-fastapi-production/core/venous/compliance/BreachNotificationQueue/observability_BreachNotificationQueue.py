"""Observability harness for BreachNotificationQueue."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from BreachNotificationQueue import InMemoryBreachNotificationQueue


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_non_empty() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_logs_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_open_span() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "breach.open" in ops and "breach.notify" in ops


def test_observability_sla_metric() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "breach.sla.breached" in names


def test_observability_open_runs_cleanly() -> None:
    q = InMemoryBreachNotificationQueue()
    q.open_incident(datetime(2026, 4, 1, tzinfo=timezone.utc), "low", "x")
    assert q.size == 1
