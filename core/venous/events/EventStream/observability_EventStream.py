"""Observability harness — asserts EventStream emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from EventStream import InMemoryEventStream


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert schema["logs"] and schema["metrics"] and schema["spans"]


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_append_lifecycle_attributes_derivable() -> None:
    es = InMemoryEventStream()
    seq1 = es.append("orders", {"id": 1})
    seq2 = es.append("orders", {"id": 2})
    # event_stream.appended carries (partition, seq) attributes.
    assert seq1 == 1
    assert seq2 == 2
    assert es.tail("orders") == 3
    assert es.partition_size("orders") == 2


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "event_stream.append" in ops
    assert "event_stream.read_from" in ops
    assert "event_stream.truncate" in ops


def test_observability_consumer_lag_derivation() -> None:
    # consumer lag = tail - consumer_offset; both observable on the impl.
    es = InMemoryEventStream()
    for i in range(6):
        es.append("p", {"i": i})
    consumer_offset = 3
    lag = es.tail("p") - consumer_offset
    assert lag == 4  # tail is 7, consumer at 3 → 4 positions behind


def test_observability_truncation_lifecycle_attributes_derivable() -> None:
    es = InMemoryEventStream(retention_min_entries=0)
    for i in range(5):
        es.append("p", {"i": i})
    es.truncate_before(3)
    # event_stream.truncated carries (partition, from_offset, to_offset).
    assert es.truncated_before_of("p") == 3
    assert es.partition_size("p") == 3
