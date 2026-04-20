"""Observability harness for HistogramBuckets."""

from __future__ import annotations

import json
from pathlib import Path

from HistogramBuckets import HistogramBuckets


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shape() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_preset_version_span() -> None:
    ops = {s["operation_name"] for s in _schema()["spans"]}
    assert "histogrambuckets.build" in ops


def test_observability_preset_changes_counter() -> None:
    names = {m["name"] for m in _schema()["metrics"]}
    assert "histogrambuckets.rejections" in names


def test_observability_logs_have_attrs() -> None:
    for log in _schema()["logs"]:
        assert log["required_attributes"]


def test_observability_presets_count_buckets() -> None:
    assert len(HistogramBuckets.latency_ms_default().boundaries) <= 20


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid
