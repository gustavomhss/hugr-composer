"""Observability harness for DataResidencyPolicy."""

from __future__ import annotations

import json
from pathlib import Path

from DataResidencyPolicy import DataResidencyPolicy, InMemoryResidencyEnforcer


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


def test_observability_check_write_span() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "residency.check_write" in ops


def test_observability_denied_counter() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "residency.denied" in names


def test_observability_bind_runs() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(DataResidencyPolicy(
        data_class="x", allowed_regions=("DE",),
        transfer_mechanism="SCC_2021/914",
    ))
    assert e.size == 1
