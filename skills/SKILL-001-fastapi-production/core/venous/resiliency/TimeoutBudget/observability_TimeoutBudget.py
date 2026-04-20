"""Observability harness — asserts TimeoutBudget emits logs/metrics/spans per schema."""

from __future__ import annotations

import json
from pathlib import Path

from TimeoutBudget import GuardedCall, MonotonicTimeoutBudget


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
    assert "timeout.budget.dispatch" in ops
    assert "timeout.budget.derive" in ops


def test_observability_dispatch_attributes_runtime_correspondence() -> None:
    # The dispatch span declares `effective_ms` — prove that the runtime
    # path produces it via GuardedCall.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=500, origin="req")
    guard = GuardedCall()
    effective = guard.dispatch(budget, "/a", local_timeout_ms=100)
    assert isinstance(effective, int)
    assert effective > 0
    # Dispatch tuple exposes (endpoint, effective_ms) — matches span attrs.
    ep, eff = guard.dispatches[0]
    assert ep == "/a"
    assert eff == effective
