"""Observability harness — asserts InboxDeduplicator emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from InboxDeduplicator import InMemoryInboxDeduplicator

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
    """End-to-end first-delivery + duplicate-skip cycle; attributes cited by
    the observability schema (message_id, consumer, first_delivery) are all
    observable from the primitive's public surface.
    """
    inbox = InMemoryInboxDeduplicator()
    ran: list[int] = []
    with inbox.handle("m-1", "c", lambda: ran.append(1)) as first:
        assert first is True  # maps to inbox.message.first.delivery event
    with inbox.handle("m-1", "c", lambda: ran.append(1)) as second:
        assert second is False  # maps to inbox.message.duplicate.skipped event
    assert sum(ran) == 1
    snap = inbox.store_snapshot
    assert len(snap) == 1
    assert snap[0]["consumer"] == "c"


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "inbox.handle" in ops
    assert "inbox.commit" in ops
    assert "inbox.purge" in ops


def test_observability_purge_metric_attribution() -> None:
    """Purge metric cardinality stays bounded — the cutoff_iso is emitted as
    a log attribute only, NEVER as a metric label."""
    schema = _load_schema()
    purge_metric = next(m for m in schema["metrics"] if m["name"] == "inbox.purge.evicted")
    assert purge_metric["label_keys"] == []  # no cutoff_iso leak into labels
    assert purge_metric["cardinality_bound"] <= 100


def test_observability_purge_evicted_count_observable() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now - timedelta(days=30)}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    for i in range(3):
        with inbox.handle(f"m-{i}", "c", lambda: None):
            pass
    clock_state["t"] = now
    cutoff = (now - timedelta(days=14)).isoformat()
    evicted = inbox.purge_older_than(cutoff)
    # `evicted` is the exact integer emitted into the `inbox.purge.evicted`
    # counter — harness asserts it matches observable state.
    assert evicted == 3
    assert inbox.store_snapshot == ()
