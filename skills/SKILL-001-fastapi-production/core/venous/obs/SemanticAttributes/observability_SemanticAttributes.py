"""Observability harness for SemanticAttributes."""

from __future__ import annotations

import json
from pathlib import Path


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_shape() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_deprecated_key_warning_metric_present() -> None:
    names = {m["name"] for m in _schema()["metrics"]}
    assert "semattr.deprecated.warnings" in names


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_logs_have_required_attrs() -> None:
    for log in _schema()["logs"]:
        assert isinstance(log["required_attributes"], list)
        assert log["required_attributes"]


def test_observability_span_ops_match() -> None:
    ops = {s["operation_name"] for s in _schema()["spans"]}
    assert "semattr.validate" in ops


def test_observability_bounded_cardinality() -> None:
    for m in _schema()["metrics"]:
        assert m["cardinality_bound"] <= 1_000_000
