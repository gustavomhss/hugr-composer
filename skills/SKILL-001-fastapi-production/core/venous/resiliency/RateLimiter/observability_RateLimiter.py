"""Observability harness — asserts RateLimiter emits events matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from RateLimiter import InMemoryRateLimiter


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


def test_observability_admission_events_emitted() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
    limiter.try_acquire("k")
    limiter.try_acquire("k")  # rejected
    events = limiter.events
    assert len(events) == 2
    assert events[0].admitted is True
    assert events[1].admitted is False
    assert events[1].retry_after_ms > 0


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "ratelimiter.acquire" in ops
    assert "ratelimiter.try.acquire" in ops
