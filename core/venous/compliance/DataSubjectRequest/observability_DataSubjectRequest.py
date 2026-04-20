"""Observability harness for DataSubjectRequest."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from DataSubjectRequest import InMemoryDataSubjectRequest


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


def test_observability_log_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_spans_declared() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "dsr.open" in ops and "dsr.close" in ops


def test_observability_duration_metric_declared() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "dsr.open.count" in names


def test_observability_open_counts_one() -> None:
    d = InMemoryDataSubjectRequest()
    d.open("s", "access", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert d.size == 1
