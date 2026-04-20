"""Observability harness for LegalHold."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from LegalHold import InMemoryLegalHoldRegistry, LegalHold


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
    assert "legal_hold.open" in ops and "legal_hold.release" in ops


def test_observability_active_metric() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "legal_hold.active" in names


def test_observability_open_runs_cleanly() -> None:
    r = InMemoryLegalHoldRegistry()
    r.open(LegalHold(hold_id="h", scope_query="record_id = 'x'",
                     opened_at=datetime.now(timezone.utc), opened_by="c"))
    assert r.size == 1
