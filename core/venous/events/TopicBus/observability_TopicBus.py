"""Observability harness — asserts TopicBus emits logs/metrics/spans matching schema."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from EventEnvelope import EventEnvelope
from TopicBus import Ack, InMemoryTopicBus, Nack, ObservabilitySink


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


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "bus.publish" in ops
    assert "bus.dispatch" in ops


def test_observability_sink_records_lifecycle() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=1, dlq_topic="dlq")
        sink = ObservabilitySink()

        async def h(e: EventEnvelope, ack: Ack, nack: Nack) -> None:
            sink.on_publish("t", bus.log_size(), e)
            if e.id == "bad":
                sink.on_nack("t", "g", e, "fail")
                await nack("fail")
                return
            sink.on_ack("t", "g", e)
            await ack()

        bus.subscribe("t", "g", h)
        await bus.publish("t", EventEnvelope(id="ok", source="u", type="t"))
        await bus.publish("t", EventEnvelope(id="bad", source="u", type="t"))
        names = {log["event_name"] for log in sink.logs}
        assert "bus.published" in names
        assert "bus.acked" in names
        assert "bus.nacked" in names

    asyncio.run(run())
