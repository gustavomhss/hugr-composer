"""Observability harness for KeyRotationSchedule."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from KeyRotationSchedule import InMemoryKeyRotator, KeyRotationSchedule


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


def test_observability_rotation_span() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "key.rotate" in ops


def test_observability_missed_metric() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "key.rotation.missed" in names


def test_observability_rotate_runs_cleanly() -> None:
    r = InMemoryKeyRotator()
    r.schedule(KeyRotationSchedule(
        key_alias="a", cadence=timedelta(days=30),
        overlap=timedelta(days=1),
        next_rotation_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    ))
    assert r.rotate_now("a") == "v2"
