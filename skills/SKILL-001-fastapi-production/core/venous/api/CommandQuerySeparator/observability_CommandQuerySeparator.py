"""Observability harness — asserts the declared schema is well-formed and the
primitive surfaces the documented event/metric/span operations.
"""

from __future__ import annotations

import json
from pathlib import Path

from CommandQuerySeparator import CommandAck, InMemoryCQS


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_operations_cover_command_and_query_paths() -> None:
    schema = _load_schema()
    ops = {str(s["operation_name"]) for s in schema["spans"]}
    assert "cqs.command.dispatch" in ops
    assert "cqs.query.answer" in ops


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_are_dotted_lowercase() -> None:
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


def test_observability_primitive_surfaces_event_stream_counts() -> None:
    cqs = InMemoryCQS()

    class _Cmd:
        pass

    def h(_cmd: object) -> CommandAck:
        evt = cqs.emit_event("Cmd", {})
        return CommandAck(ack=True, status="accepted", event_offset=evt.offset)

    cqs.register_command_handler(_Cmd, h)
    for _ in range(3):
        cqs.dispatch_command(_Cmd())
    assert len(cqs.event_stream.events) == 3
