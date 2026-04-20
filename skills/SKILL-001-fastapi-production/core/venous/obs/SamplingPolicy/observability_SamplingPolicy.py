"""Observability harness for SamplingPolicy."""

from __future__ import annotations

import json
from pathlib import Path

from SamplingPolicy import ParentBasedHeadSampler


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shape_ok() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_fallback_metric_declared() -> None:
    names = {m["name"] for m in _schema()["metrics"]}
    assert "sampler.fallback.count" in names


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_events_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_sampler_description_truncated() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)
    assert len(s.description()) < 256


def test_observability_span_ops_present() -> None:
    ops = {s["operation_name"] for s in _schema()["spans"]}
    assert "sampler.decide" in ops
