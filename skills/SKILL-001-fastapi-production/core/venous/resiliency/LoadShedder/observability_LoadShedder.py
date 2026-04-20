"""Observability harness — asserts LoadShedder emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from LoadShedder import InMemoryLoadShedder


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


def test_observability_cutoff_is_published_as_metric() -> None:
    schema = _load_schema()
    names = {str(m["name"]) for m in schema["metrics"]}
    # LSH-INV-05: current_cutoff MUST be exported as a metric.
    assert "load_shedder.current_cutoff" in names


def test_observability_metric_sink_fires_on_cutoff_change() -> None:
    emitted: list[tuple[str, float, dict[str, str]]] = []

    def sink(name: str, value: float, labels: dict[str, str]) -> None:
        emitted.append((name, value, labels))

    class _C:
        def __init__(self) -> None:
            self.now = 1.0

        def __call__(self) -> float:
            return self.now

        def advance(self, s: float) -> None:
            self.now += s

    clock = _C()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10, metric_sink=sink)
    assert emitted  # initial publication on construction
    clock.advance(0.1)
    s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    # Cutoff change emits a new metric.
    assert any(e[0] == "load_shedder.current_cutoff" and e[2]["cutoff"] == "critical" for e in emitted)


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_admit_span_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "load_shedder.admit" in ops
