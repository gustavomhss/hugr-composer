"""Observability harness for StreamSubject."""

from __future__ import annotations

import json
from pathlib import Path

from StreamSubject import StreamSubject, SubjectRegistry

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_log_names_lowercase() -> None:
    for log in _load_schema()["logs"]:
        assert str(log["event_name"]) == str(log["event_name"]).lower()


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_cardinality_bounds() -> None:
    for m in _load_schema()["metrics"]:
        assert isinstance(m["cardinality_bound"], int)


def test_observability_publication_sequence_is_observable() -> None:
    reg = SubjectRegistry()
    reg.subscribe("a.>", "c1")
    reg.publish(StreamSubject("a.b"))
    reg.publish(StreamSubject("a.c"))
    seqs = [d[2] for d in reg.deliveries()]
    assert seqs == [1, 2]


def test_observability_span_ops_present() -> None:
    ops = {s["operation_name"] for s in _load_schema()["spans"]}
    assert "subject.match" in ops
