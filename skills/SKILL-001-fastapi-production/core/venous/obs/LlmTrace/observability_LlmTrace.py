"""Observability harness — asserts LlmTrace emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from LlmTrace import (
    GEN_AI_PROMPT_FINGERPRINT,
    GEN_AI_REQUEST_MODEL,
    InMemoryLlmTrace,
)


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_span_operations_match_schema() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        span.set_usage(10, 5)
        span.set_finish_reason("stop")
    schema = _load_schema()
    span_ops = {s["operation_name"] for s in schema["spans"]}
    assert "llmtrace.span.create" in span_ops


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


def test_observability_required_semconv_attrs_present_on_every_span() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "gpt", "fp-1"):
        pass
    with tracer.start("tool_call", "tool", "fp-2"):
        pass
    for s in tracer.spans:
        assert GEN_AI_REQUEST_MODEL in s.attributes
        assert GEN_AI_PROMPT_FINGERPRINT in s.attributes
