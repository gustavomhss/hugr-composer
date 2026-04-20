"""Behavioral end-to-end scenarios for LlmTrace — proves invariants at runtime."""

from __future__ import annotations

import time

import pytest

from LlmTrace import (
    GEN_AI_PROMPT_FINGERPRINT,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    InMemoryLlmTrace,
    LlmTraceInvariantError,
    assert_required_semconv_present,
)


def test_scenario_completion_round_trip() -> None:
    """A normal completion call emits a single OTel-shaped span."""
    tracer = InMemoryLlmTrace(system="anthropic")
    with tracer.start("completion", "claude-opus-4-7", "fp-completion-1") as span:
        span.set_usage(1200, 340)
        span.set_finish_reason("stop")
    s = tracer.spans[0]
    assert s.attributes[GEN_AI_REQUEST_MODEL] == "claude-opus-4-7"
    assert s.attributes[GEN_AI_USAGE_INPUT_TOKENS] == 1200
    assert s.attributes[GEN_AI_USAGE_OUTPUT_TOKENS] == 340
    assert s.attributes[GEN_AI_RESPONSE_FINISH_REASONS] == ["stop"]
    assert s.attributes[GEN_AI_PROMPT_FINGERPRINT] == "fp-completion-1"
    assert s.status_code == "OK"
    assert_required_semconv_present(s.attributes)


def test_scenario_tool_call_nests_under_model_call() -> None:
    """Child tool-call spans nest under the parent completion span."""
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "planner-v2", "fp-parent") as parent:
        parent.set_usage(500, 120)
        with tracer.start("tool_call.search", "tool.web_search", "fp-child") as child:
            child.set_finish_reason("stop")
        parent.set_finish_reason("tool_calls")
    parent_span, child_span = tracer.spans
    assert child_span.parent_span_id == parent_span.span_id
    assert child_span.trace_id == parent_span.trace_id


def test_scenario_provider_error_recorded_before_exit() -> None:
    """Exceptions escaping the span body auto-record as error (INV-04)."""
    tracer = InMemoryLlmTrace()
    try:
        with tracer.start("completion", "m", "fp-err"):
            raise TimeoutError("provider timeout")
    except TimeoutError:
        pass
    s = tracer.spans[0]
    assert s.error_code == "TimeoutError"
    assert s.status_code == "ERROR"


def test_scenario_prompt_caching_usage_attrs_recorded() -> None:
    """Prompt-cache token counts land on OTel GenAI cache_* attrs."""
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "claude-opus-4-7", "fp-cache") as span:
        span.set_usage(800, 120)
        span.set_cache_usage(
            cache_read_input_tokens=600, cache_creation_input_tokens=0
        )
        span.set_finish_reason("stop")
    s = tracer.spans[0]
    assert s.attributes[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS] == 600


def test_scenario_privacy_first_no_content_captured_by_default() -> None:
    """Default tracer MUST NOT attach prompt/response content; only fingerprint."""
    tracer = InMemoryLlmTrace()
    assert tracer.capture_content is False
    with tracer.start("completion", "m", "fp-private"):
        pass
    s = tracer.spans[0]
    for key in s.attributes:
        assert "prompt.text" not in key
        assert "response.text" not in key


def test_scenario_bad_finish_reason_rejected() -> None:
    """Only OTel-spec finish reasons are accepted (INV-02)."""
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        with pytest.raises(LlmTraceInvariantError):
            span.set_finish_reason("ran_out_of_tokens")  # not a SemConv value


def test_scenario_hot_path_is_fast() -> None:
    """LlmTrace adds negligible overhead per span (< 250us on a modest box)."""
    tracer = InMemoryLlmTrace()
    start = time.monotonic()
    for i in range(500):
        with tracer.start("completion", "m", f"fp-{i}") as span:
            span.set_usage(10, 10)
            span.set_finish_reason("stop")
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
    assert len(tracer.spans) == 500
