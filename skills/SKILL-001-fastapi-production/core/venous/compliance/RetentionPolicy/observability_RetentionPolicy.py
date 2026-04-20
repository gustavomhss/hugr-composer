"""Observability harness for RetentionPolicy."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from RetentionPolicy import InMemoryRetentionEnforcer, RetentionPolicy


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_non_empty() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_sweep_span_declared() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "retention.sweep" in ops


def test_observability_purged_counter_declared() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "retention.records.purged" in names


def test_observability_sweep_runs_cleanly() -> None:
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(RetentionPolicy(
        data_class="x", max_age=timedelta(days=1),
        legal_basis="l", deletion_mode="hard",
    ))
    enf.enforce_on_write("x", "r1")
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert enf.sweep() == 1
