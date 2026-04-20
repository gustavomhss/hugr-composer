"""Observability harness for PiiClassification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PiiClassification import InMemoryPiiClassification, PiiClass


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


def test_observability_mask_span_declared() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "pii.mask" in ops


def test_observability_leak_counter_declared() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "pii.leaks" in names


def test_observability_mask_runs_cleanly() -> None:
    @dataclass
    class U:
        f: str

    c = InMemoryPiiClassification()
    c.register(U, "f", PiiClass.PUBLIC)
    out = c.mask(U(f="x"), audience="public")
    assert out == {"f": "x"}
