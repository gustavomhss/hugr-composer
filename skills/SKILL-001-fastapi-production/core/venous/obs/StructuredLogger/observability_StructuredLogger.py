"""Observability harness for StructuredLogger."""

from __future__ import annotations

import json
from pathlib import Path

from StructuredLogger import InMemoryStructuredLogger


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert schema["logs"] and schema["metrics"] and schema["spans"]


def test_observability_emit_produces_record() -> None:
    log = InMemoryStructuredLogger()
    log.info("x")
    assert len(log.records) == 1


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_are_dotted() -> None:
    for log in _load_schema()["logs"]:
        assert "." in str(log["event_name"])


def test_observability_span_ops_include_emit() -> None:
    ops = {s["operation_name"] for s in _load_schema()["spans"]}
    assert "logger.emit" in ops


def test_observability_cardinality_bounds_present() -> None:
    for m in _load_schema()["metrics"]:
        assert isinstance(m["cardinality_bound"], int) and m["cardinality_bound"] >= 1
