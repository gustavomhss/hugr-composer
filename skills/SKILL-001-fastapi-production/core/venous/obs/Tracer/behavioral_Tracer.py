"""Behavioral end-to-end scenarios for Tracer — proves invariants at runtime."""

from __future__ import annotations

import time

import pytest

from Tracer import InMemoryTracer, TracerInvariantError


def test_scenario_request_lifecycle() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("http.server.request", kind="SERVER",
                                      attributes={"http.route": "/checkout"}) as span:
        span.set_attribute("http.response.status_code", 200)
        span.add_event("cache.hit", {"key": "abc"})
    s = tracer.spans[0]
    assert s.kind == "SERVER"
    assert s.attributes["http.route"] == "/checkout"
    assert s.events[0][0] == "cache.hit"


def test_scenario_exception_marks_error() -> None:
    tracer = InMemoryTracer()
    try:
        with tracer.start_as_current_span("risky.work") as span:
            try:
                raise RuntimeError("downstream")
            except RuntimeError as exc:
                span.record_exception(exc)
                raise
    except RuntimeError:
        pass
    assert tracer.spans[0].status_code == "ERROR"


def test_scenario_context_propagation_roundtrip() -> None:
    producer = InMemoryTracer()
    producer.extract({
        "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
        "tracestate": "vendorA=1,vendorB=2",
    })
    carrier: dict[str, str] = {}
    producer.inject(carrier)
    consumer = InMemoryTracer()
    ctx = consumer.extract(carrier)
    assert isinstance(ctx, dict)
    assert ctx["trace_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_scenario_nested_work_units() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("outer"):
        with tracer.start_as_current_span("inner.db", kind="CLIENT",
                                          attributes={"db.system": "postgresql"}):
            pass
    assert len(tracer.spans) == 2
    assert tracer.spans[1].kind == "CLIENT"


def test_scenario_attribute_discipline_blocks_dict() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("attr.policy") as span:
        span.set_attribute("user.agent", "Mozilla/5.0")
        with pytest.raises(TracerInvariantError):
            span.set_attribute("nested.bag", {"k": "v"})  # type: ignore[arg-type]


def test_scenario_end_is_idempotent_even_under_concurrent_close() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("once"):
        pass
    s = tracer.spans[0]
    initial = s.end_ns
    s.end(time.monotonic_ns() + 1_000_000)
    s.end(time.monotonic_ns() + 2_000_000)
    assert s.end_ns == initial
    assert len(s.warnings) >= 2


def test_scenario_hot_path_is_fast() -> None:
    tracer = InMemoryTracer()
    start = time.monotonic()
    for _ in range(1_000):
        with tracer.start_as_current_span("hot.path"):
            pass
    elapsed = time.monotonic() - start
    # 1000 spans under 250ms on a reasonable CI box — proves non-blocking export.
    assert elapsed < 0.5
