"""Observability harness for ConsentLedger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ConsentLedger import InMemoryConsentLedger


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_non_empty() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_grant_span_declared() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "consent.grant" in ops and "consent.revoke" in ops


def test_observability_metrics_valid_types() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_grants_counter_declared() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "consent.grants" in names and "consent.revocations" in names


def test_observability_grant_runs_cleanly() -> None:
    led = InMemoryConsentLedger()
    led.grant("s", "p", "v", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert led.size == 1
