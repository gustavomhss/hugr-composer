"""Observability harness — asserts SagaOrchestrator emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from SagaOrchestrator import (
    STATE_COMPLETED,
    InMemorySagaOrchestrator,
    SagaDefinition,
)


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
    assert "saga.start" in ops
    assert "saga.compensate" in ops


def test_observability_runtime_journal_tracks_every_lifecycle_event() -> None:
    sd = SagaDefinition("obs")
    sd.register("a", compensator=lambda p: None)(lambda p: p)
    sd.register("b", compensator=lambda p: None)(lambda p: p)
    emitted: list[tuple[str, str]] = []
    saga = InMemorySagaOrchestrator(
        sd,
        command_sink=lambda cid, cmd, _p: emitted.append((cid, cmd)),
    )
    saga.start("o", {})
    saga.step("o", "a", 1)
    saga.step("o", "b", 2)
    assert saga.status("o")[0] == STATE_COMPLETED
    # The journal is what an observability exporter samples; verify lengths.
    journal = saga.journal_for("o")
    # PENDING->RUNNING, RUNNING->RUNNING, RUNNING->COMPLETED = 3 records.
    assert len(journal) == 3
    # Emitted commands track the lifecycle one-to-one.
    assert [c[1] for c in emitted] == [
        "invoke_a",
        "invoke_b",
        "saga_completed",
    ]
