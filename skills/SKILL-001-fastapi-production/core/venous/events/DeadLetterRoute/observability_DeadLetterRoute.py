"""Observability harness — asserts DeadLetterRoute emits logs / metrics / spans."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from DeadLetterRoute import (
    DeadLetterRoute,
    DlqObservabilitySink,
    InMemoryDeadLetterSink,
)
from EventEnvelope import EventEnvelope


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types_valid() -> None:
    s = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in s["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted_lowercase() -> None:
    s = _load_schema()
    for log in s["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_cardinality_bounds_declared() -> None:
    s = _load_schema()
    for m in s["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_cover_state_transitions() -> None:
    s = _load_schema()
    ops = {sp["operation_name"] for sp in s["spans"]}
    assert "dlq.send" in ops
    assert "dlq.requeue" in ops
    assert "dlq.purge" in ops


def test_observability_sink_records_lifecycle() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        obs = DlqObservabilitySink()
        env = EventEnvelope(id="e", source="urn:o", type="o.e")
        await sink.send(route, env, "boom", attempt=2)
        obs.on_send(route, env, "boom", 2)
        # Purge and log.
        evicted = sink.purge("d", envelope_source="urn:o", envelope_id="e")
        obs.on_purge(evicted, "fixed")
        names = {log["event_name"] for log in obs.logs}
        assert "dlq.sent" in names
        assert "dlq.purged" in names

    asyncio.run(run())
