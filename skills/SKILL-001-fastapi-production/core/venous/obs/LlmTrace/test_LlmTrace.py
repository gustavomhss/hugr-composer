"""Unit tests for LlmTrace — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import pytest

from LlmTrace import (
    GEN_AI_PROMPT_FINGERPRINT,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    InMemoryLlmTrace,
    LlmTraceInvariantError,
    assert_required_semconv_present,
    validate_finish_reason,
    validate_operation,
    validate_prompt_fingerprint,
    validate_semconv_key,
    validate_token_count,
)


# ---------------------------------------------------------------------------
# LLMTRACE_INV_01 — one span per model call
# ---------------------------------------------------------------------------
def test_inv_one_span_per_call_confirms() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "planner-v2", "fp-abc") as span:
        span.set_usage(10, 5)
        span.set_finish_reason("stop")
    assert len(tracer.spans) == 1
    assert tracer.active_depth == 0


def test_inv_one_span_per_call_prevents() -> None:
    tracer = InMemoryLlmTrace()
    with pytest.raises(LlmTraceInvariantError):
        with tracer.start("", "m", "fp"):
            pass
    with pytest.raises(LlmTraceInvariantError):
        validate_operation("   ")


def test_inv_one_span_per_call_under_failure() -> None:
    tracer = InMemoryLlmTrace()
    try:
        with tracer.start("completion", "m", "fp"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    # Even under failure, exactly one span was emitted and closed.
    assert len(tracer.spans) == 1
    assert tracer.spans[0].end_ns is not None
    assert tracer.active_depth == 0


# ---------------------------------------------------------------------------
# LLMTRACE_INV_02 — OTel GenAI SemConv attribute names
# ---------------------------------------------------------------------------
def test_inv_semconv_attrs_confirms() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "gpt-4o-mini", "fp-1") as span:
        span.set_usage(100, 42)
        span.set_finish_reason("stop")
    s = tracer.spans[0]
    assert s.attributes[GEN_AI_REQUEST_MODEL] == "gpt-4o-mini"
    assert s.attributes[GEN_AI_USAGE_INPUT_TOKENS] == 100
    assert s.attributes[GEN_AI_USAGE_OUTPUT_TOKENS] == 42
    assert_required_semconv_present(s.attributes)


def test_inv_semconv_attrs_prevents() -> None:
    with pytest.raises(LlmTraceInvariantError):
        validate_semconv_key("model")  # missing gen_ai. prefix
    with pytest.raises(LlmTraceInvariantError):
        validate_finish_reason("not-a-real-reason")
    with pytest.raises(LlmTraceInvariantError):
        validate_token_count("input_tokens", -1)
    with pytest.raises(LlmTraceInvariantError):
        validate_token_count("input_tokens", True)  # bool is not int


def test_inv_semconv_attrs_under_failure() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        # record_error installs gen_ai.error.* attrs (still namespaced).
        span.record_error("RateLimit", "429")
    keys = list(tracer.spans[0].attributes)
    for key in keys:
        assert key.startswith("gen_ai.")


# ---------------------------------------------------------------------------
# LLMTRACE_INV_03 — prompt_fingerprint required
# ---------------------------------------------------------------------------
def test_inv_prompt_fingerprint_confirms() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp-xyz"):
        pass
    assert tracer.spans[0].attributes[GEN_AI_PROMPT_FINGERPRINT] == "fp-xyz"
    assert tracer.spans[0].prompt_fingerprint == "fp-xyz"


def test_inv_prompt_fingerprint_prevents() -> None:
    tracer = InMemoryLlmTrace()
    with pytest.raises(LlmTraceInvariantError):
        with tracer.start("completion", "m", ""):
            pass
    with pytest.raises(LlmTraceInvariantError):
        validate_prompt_fingerprint("   ")


def test_inv_prompt_fingerprint_under_failure() -> None:
    tracer = InMemoryLlmTrace()
    try:
        with tracer.start("completion", "m", "fp-under-failure"):
            raise RuntimeError("provider 500")
    except RuntimeError:
        pass
    # Even on provider error the fingerprint is preserved on the closed span.
    assert tracer.spans[0].prompt_fingerprint == "fp-under-failure"


# ---------------------------------------------------------------------------
# LLMTRACE_INV_04 — record_error before exit
# ---------------------------------------------------------------------------
def test_inv_record_error_confirms() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        span.record_error("RateLimit", "429 from provider")
    s = tracer.spans[0]
    assert s.error_code == "RateLimit"
    assert s.status_code == "ERROR"


def test_inv_record_error_prevents() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        with pytest.raises(LlmTraceInvariantError):
            span.record_error("", "empty code forbidden")


def test_inv_record_error_under_failure() -> None:
    tracer = InMemoryLlmTrace()
    # Provider raises without caller calling record_error manually: the
    # reference tracer MUST auto-record the exception as an error to satisfy
    # LLMTRACE-INV-04 (no silent swallow).
    try:
        with tracer.start("completion", "m", "fp"):
            raise ConnectionError("transient")
    except ConnectionError:
        pass
    s = tracer.spans[0]
    assert s.error_code == "ConnectionError"
    assert s.status_code == "ERROR"


# ---------------------------------------------------------------------------
# LLMTRACE_INV_05 — child spans nest under parent
# ---------------------------------------------------------------------------
def test_inv_nested_children_confirms() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "planner", "fp-parent"):
        with tracer.start("tool_call", "search", "fp-child"):
            pass
    assert len(tracer.spans) == 2
    parent, child = tracer.spans
    assert child.parent_span_id == parent.span_id
    assert child.trace_id == parent.trace_id


def test_inv_nested_children_prevents() -> None:
    tracer = InMemoryLlmTrace()
    # Root span has no parent (parent_span_id is None).
    with tracer.start("completion", "m", "fp"):
        pass
    assert tracer.spans[0].parent_span_id is None


def test_inv_nested_children_under_failure() -> None:
    tracer = InMemoryLlmTrace()
    try:
        with tracer.start("completion", "m", "fp-outer"):
            with tracer.start("tool_call", "search", "fp-inner"):
                raise RuntimeError("tool failed")
    except RuntimeError:
        pass
    # Stack MUST fully unwind under exception.
    assert tracer.active_depth == 0
    parent, child = tracer.spans
    assert child.parent_span_id == parent.span_id
    assert child.status_code == "ERROR"
    # Exception propagates: outer also marked ERROR by auto-record.
    assert parent.status_code == "ERROR"
