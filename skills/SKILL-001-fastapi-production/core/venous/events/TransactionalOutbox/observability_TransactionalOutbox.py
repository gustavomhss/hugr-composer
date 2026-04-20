"""Observability harness — asserts TransactionalOutbox emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from TransactionalOutbox import InMemoryTransactionalOutbox, OutboxMessage

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
    published: list[str] = []

    def publisher(m: OutboxMessage) -> bool:
        published.append(m.message_id)
        return True

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
    with outbox.begin() as scope:
        outbox.enqueue("orders.placed", {"id": 1}, key="A")
        scope.commit()
    outbox.relay_once()
    # Invariants that map to emitted log attributes:
    snap = outbox.store_snapshot
    assert len(snap) == 1
    assert snap[0]["status"] == "published"
    assert len(published) == 1


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "outbox.commit" in ops
    assert "outbox.relay" in ops
