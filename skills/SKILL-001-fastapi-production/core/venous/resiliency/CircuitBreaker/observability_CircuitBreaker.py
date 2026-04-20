"""Observability harness — asserts CircuitBreaker emits events matching schema."""

from __future__ import annotations

import json
import time
from pathlib import Path

from CircuitBreaker import InMemoryCircuitBreaker


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


def test_observability_lifecycle_emits_transition_event() -> None:
    breaker = InMemoryCircuitBreaker("svc", cooldown_ms=10)
    breaker.force_open("boot")
    time.sleep(0.03)
    breaker.allow_probe()
    # At least two transitions (closed->open, open->half_open) MUST have been emitted.
    transitions = [(e.from_state, e.to_state) for e in breaker.events]
    assert ("closed", "open") in transitions
    assert ("open", "half_open") in transitions


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "circuitbreaker.call" in ops
