"""Observability harness for CorsPolicy — schema assertions + smoke run."""

from __future__ import annotations

import json
from pathlib import Path

from CorsPolicy import build_policy


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


def test_observability_log_event_names_lowercase() -> None:
    for log in _schema()["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()


def test_observability_evaluate_span_declared() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "cors.evaluate" in ops


def test_observability_denied_counter_declared() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "cors.denied" in names


def test_observability_evaluate_runs_cleanly() -> None:
    policy = build_policy(
        exact_origins=["https://a.example.com"],
        allow_credentials=False,
        max_age_seconds=60,
    )
    d = policy.evaluate("https://a.example.com", "GET", ())
    assert d.allow_origin == "https://a.example.com"
