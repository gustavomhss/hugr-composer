"""Observability harness for ProcessingRecord."""

from __future__ import annotations

import json
from pathlib import Path

from ProcessingRecord import InMemoryProcessingRegistry, ProcessingRecord


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


def test_observability_register_span() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "ropa.register" in ops


def test_observability_activities_counter() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "ropa.activities" in names


def test_observability_register_runs() -> None:
    r = InMemoryProcessingRegistry()
    r.register(ProcessingRecord(
        activity="a", controller="c", purposes=("p",),
        data_classes=("pii",), recipients=("i",),
        retention_ref="r", legal_basis="GDPR Art 6(1)(a) consent",
    ))
    assert r.size == 1
