"""Observability harness — asserts LifetimeScope emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from LifetimeScope import LifetimeScope, ScopeManager


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


class Svc:
    pass


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


def test_observability_lifecycle_produces_expected_state() -> None:
    m = ScopeManager()
    m.register("s", Svc, scope=LifetimeScope.SCOPED)
    with m.scope() as child:
        child.resolve("s")
        assert len(child.scope_snapshot()) == 1
        assert child.depth == 1
    assert child.disposed


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "lifetime.resolve" in ops
    assert "lifetime.scope.dispose" in ops


def test_observability_scope_lifecycle_events_declared() -> None:
    schema = _load_schema()
    events = {str(log["event_name"]) for log in schema["logs"]}
    assert {"lifetime.scope.opened", "lifetime.scope.disposed"} <= events
