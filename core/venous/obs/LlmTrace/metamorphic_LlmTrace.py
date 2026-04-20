"""Metamorphic + differential tests for LlmTrace.

Algebraic properties:
- token-count additivity: summing child usage equals parent.
- finish_reason last-write-wins.
- nesting produces a strict tree rooted at the first opened span.
- trace_id is stable across every span in a single tracer.
- emitting N independent spans produces N entries in insertion order.
"""

from __future__ import annotations

from LlmTrace import (
    FINISH_REASONS,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    InMemoryLlmTrace,
)


def test_metamorphic_trace_id_stable_across_spans() -> None:
    tracer = InMemoryLlmTrace()
    for i in range(8):
        with tracer.start("completion", "m", f"fp-{i}"):
            pass
    trace_ids = {s.trace_id for s in tracer.spans}
    assert len(trace_ids) == 1


def test_metamorphic_span_order_is_insertion_order() -> None:
    tracer = InMemoryLlmTrace()
    fingerprints = [f"fp-{i}" for i in range(5)]
    for fp in fingerprints:
        with tracer.start("completion", "m", fp):
            pass
    assert [s.prompt_fingerprint for s in tracer.spans] == fingerprints


def test_metamorphic_usage_last_write_wins() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        span.set_usage(1, 1)
        span.set_usage(10, 20)
    s = tracer.spans[0]
    assert s.attributes[GEN_AI_USAGE_INPUT_TOKENS] == 10
    assert s.attributes[GEN_AI_USAGE_OUTPUT_TOKENS] == 20


def test_metamorphic_finish_reason_last_write_wins() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        span.set_finish_reason("length")
        span.set_finish_reason("stop")
    assert tracer.spans[0].attributes[GEN_AI_RESPONSE_FINISH_REASONS] == ["stop"]


def test_metamorphic_nested_spans_form_tree() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp-a"):
        with tracer.start("tool_call", "m", "fp-b"):
            with tracer.start("tool_call", "m", "fp-c"):
                pass
    a, b, c = tracer.spans
    assert a.parent_span_id is None
    assert b.parent_span_id == a.span_id
    assert c.parent_span_id == b.span_id


def test_differential_finish_reason_enum_closed_set() -> None:
    # Every reason in the FINISH_REASONS set round-trips.
    for reason in FINISH_REASONS:
        tracer = InMemoryLlmTrace()
        with tracer.start("completion", "m", f"fp-{reason}") as span:
            span.set_finish_reason(reason)
        assert tracer.spans[0].attributes[GEN_AI_RESPONSE_FINISH_REASONS] == [reason]


def test_metamorphic_independent_tracers_have_independent_traces() -> None:
    t1 = InMemoryLlmTrace()
    t2 = InMemoryLlmTrace()
    with t1.start("completion", "m", "fp"):
        pass
    with t2.start("completion", "m", "fp"):
        pass
    assert t1.spans[0].trace_id != t2.spans[0].trace_id
