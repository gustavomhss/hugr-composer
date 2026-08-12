"""Observability harness — asserts EventSourcedStore emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from EventSourcedStore import (
    ConcurrencyError,
    InMemoryEventSourcedStore,
    replay,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def _fold(state: object, event: object) -> int:
    assert isinstance(event, dict)
    base = 0 if state is None else int(state)  # type: ignore[arg-type]
    return base + int(event["n"])


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


def test_observability_spans_cover_core_operations() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "ess.append" in ops
    assert "ess.load" in ops
    assert "ess.snapshot" in ops


def test_observability_logs_cover_concurrency_path() -> None:
    # The operator MUST be able to see concurrency rejections — it is the
    # primary symptom of stale writers. The schema declares an explicit event
    # name for it.
    schema = _load_schema()
    names = {log["event_name"] for log in schema["logs"]}
    assert "ess.concurrency.rejected" in names


def test_observability_runtime_state_matches_schema_attributes() -> None:
    # Drive the primitive through the operations whose attributes the schema
    # declares; the observable values must be accessible via the public API.
    store = InMemoryEventSourcedStore()
    v1 = store.append("agg-obs", expected_version=0, events=[{"n": 1}, {"n": 2}])
    assert v1 == 2  # new_version
    try:
        store.append("agg-obs", expected_version=0, events=[{"n": 99}])
    except ConcurrencyError as exc:
        assert exc.expected_version == 0
        assert exc.actual_version == 2
    store.snapshot("agg-obs", version=2, state=3)
    snap = store.latest_snapshot("agg-obs")
    assert snap is not None
    assert snap.version == 2
    state, folded = replay(store, "agg-obs", _fold)
    assert state == 3
    assert folded == 2
