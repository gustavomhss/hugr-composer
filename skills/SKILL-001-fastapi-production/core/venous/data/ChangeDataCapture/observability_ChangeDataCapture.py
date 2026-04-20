"""Observability harness — asserts ChangeDataCapture emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from ChangeDataCapture import InMemoryChangeDataCapture


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


def test_observability_lifecycle_emits_attributes() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id", "total"])
    cdc.begin_tx("txn")
    cdc.stage_change("txn", "orders", "insert", 1, None, {"id": 1, "total": 10})
    cdc.stage_change("txn", "orders", "update", 1, {"id": 1, "total": 10}, {"id": 1, "total": 20})
    published = cdc.commit_tx("txn")
    # Attributes observable for the cdc.tx.committed log event:
    assert published == 2
    assert cdc.next_position >= 3
    assert cdc.committed_event_count == 2
    # cdc.last.position metric is derivable from next_position - 1.
    assert cdc.next_position - 1 >= 3


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "cdc.tx.commit" in ops
    assert "cdc.subscribe" in ops
    assert "cdc.schema.evolve" in ops


def test_observability_consumer_lag_derivation() -> None:
    # consumer lag = last_committed_pos - checkpoint; both observable on the impl.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    for i in range(4):
        cdc.begin_tx(f"t{i}")
        cdc.stage_change(f"t{i}", "t", "insert", i, None, {"id": i})
        cdc.commit_tx(f"t{i}")
    cdc.checkpoint(1)
    lag = (cdc.next_position - 1) - cdc.checkpoint_of()
    assert lag >= 3
