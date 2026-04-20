"""Metamorphic + differential tests for Tracer.

Algebraic properties:
- idempotency of end()
- associativity of nested spans (order preservation)
- traceparent roundtrip preserves trace_id
- tracestate preservation across inject/extract
"""

from __future__ import annotations

from Tracer import InMemoryTracer


def test_metamorphic_end_idempotent_call_count() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("stable"):
        pass
    s = tracer.spans[0]
    first = s.end_ns
    for _ in range(10):
        s.end(10**18)
    assert s.end_ns == first


def test_metamorphic_trace_id_roundtrip() -> None:
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    span_id = "b7ad6b7169203331"
    t1 = InMemoryTracer()
    t1.extract({"traceparent": f"00-{trace_id}-{span_id}-01"})
    carrier: dict[str, str] = {}
    t1.inject(carrier)
    t2 = InMemoryTracer()
    t2.extract(carrier)
    carrier2: dict[str, str] = {}
    t2.inject(carrier2)
    assert carrier2.get("traceparent") == f"00-{trace_id}-{span_id}-01"


def test_metamorphic_tracestate_vendors_preserved() -> None:
    tracer = InMemoryTracer()
    tracer.extract({
        "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
        "tracestate": "vA=1,vB=2,vC=3",
    })
    carrier: dict[str, str] = {}
    tracer.inject(carrier)
    assert carrier["tracestate"] == "vA=1,vB=2,vC=3"


def test_metamorphic_span_order_is_insertion_order() -> None:
    tracer = InMemoryTracer()
    names = ["a", "b", "c", "d", "e"]
    for n in names:
        with tracer.start_as_current_span(n):
            pass
    assert [s.name for s in tracer.spans] == names


def test_differential_kind_is_preserved() -> None:
    tracer = InMemoryTracer()
    for k in ("INTERNAL", "SERVER", "CLIENT", "PRODUCER", "CONSUMER"):
        with tracer.start_as_current_span("k", kind=k):
            pass
    kinds = [s.kind for s in tracer.spans]
    assert kinds == ["INTERNAL", "SERVER", "CLIENT", "PRODUCER", "CONSUMER"]


def test_metamorphic_attribute_overwrite_last_wins() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("attr") as span:
        span.set_attribute("k", "v1")
        span.set_attribute("k", "v2")
    assert tracer.spans[0].attributes["k"] == "v2"
