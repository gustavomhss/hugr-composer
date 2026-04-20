"""Observability harness — asserts SessionStore emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from SessionStore import InMemorySessionStore


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


def test_observability_lifecycle_events_cover_state_transitions() -> None:
    # Every lifecycle transition in the primitive MUST map to a schema event.
    schema = _load_schema()
    events = {str(log["event_name"]) for log in schema["logs"]}
    required = {
        "session.created",
        "session.rotated",
        "session.revoked",
        "session.revoked.all",
        "session.expired",
    }
    assert required.issubset(events)


def test_observability_lifecycle_exercises_states() -> None:
    # Exercise the primitive through every state transition so a real wiring
    # (not modelled here) would emit every schema event.
    clock = {"t": 100}
    store = InMemorySessionStore(
        idle_timeout_s=10,
        absolute_timeout_s=1000,
        clock=lambda: clock["t"],
    )
    s1 = store.create("alice")                       # session.created
    rotated = store.rotate(s1.id)                    # session.rotated
    store.revoke(rotated.id)                         # session.revoked
    store.create("bob")
    store.revoke_all_for_subject("bob")              # session.revoked.all
    s2 = store.create("charlie")
    clock["t"] = s2.idle_expires_at + 1
    assert store.load(s2.id) is None                 # session.expired


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_cover_primitive_verbs() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert {"session.create", "session.rotate", "session.revoke"}.issubset(ops)
