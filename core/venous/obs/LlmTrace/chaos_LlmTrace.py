"""Chaos / fault-injection for LlmTrace.

Game-day scenarios: provider errors, malformed usage, threaded contention,
mis-ordered child spans. The tracer MUST remain correct under each.
"""

from __future__ import annotations

import threading

import pytest

from LlmTrace import InMemoryLlmTrace, LlmTraceInvariantError


def test_chaos_provider_timeout_auto_records_error() -> None:
    tracer = InMemoryLlmTrace()
    try:
        with tracer.start("completion", "m", "fp"):
            raise TimeoutError("upstream 30s timeout")
    except TimeoutError:
        pass
    s = tracer.spans[0]
    assert s.status_code == "ERROR"
    assert s.error_code == "TimeoutError"


def test_chaos_negative_token_count_rejected() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        with pytest.raises(LlmTraceInvariantError):
            span.set_usage(-1, 0)


def test_chaos_boolean_token_count_rejected() -> None:
    # bool is a subtype of int in Python — explicitly reject to avoid
    # silent attribute poisoning (INV-02).
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        with pytest.raises(LlmTraceInvariantError):
            span.set_usage(True, 0)  # type: ignore[arg-type] — INV-02 guard


def test_chaos_concurrent_spans_safe() -> None:
    tracer = InMemoryLlmTrace()
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            for i in range(50):
                with tracer.start("completion", "m", f"fp-{idx}-{i}") as span:
                    span.set_usage(1, 1)
                    span.set_finish_reason("stop")
        except BaseException as exc:  # pragma: no cover — defensive catch
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(tracer.spans) == 400


def test_chaos_empty_error_code_rejected() -> None:
    tracer = InMemoryLlmTrace()
    with tracer.start("completion", "m", "fp") as span:
        with pytest.raises(LlmTraceInvariantError):
            span.record_error("", "msg")


def test_chaos_nested_failure_unwinds_cleanly() -> None:
    tracer = InMemoryLlmTrace()
    try:
        with tracer.start("completion", "m", "fp-outer"):
            with tracer.start("tool_call", "m", "fp-inner"):
                raise RuntimeError("deep failure")
    except RuntimeError:
        pass
    assert tracer.active_depth == 0
    for s in tracer.spans:
        assert s.status_code == "ERROR"
        assert s.end_ns is not None


def test_chaos_deeply_nested_spans_remain_a_tree() -> None:
    tracer = InMemoryLlmTrace()

    def recurse(depth: int) -> None:
        if depth == 0:
            return
        with tracer.start("tool_call", "m", f"fp-d{depth}"):
            recurse(depth - 1)

    recurse(16)
    # All 16 spans must chain parent -> child exactly once.
    for child, parent in zip(tracer.spans[1:], tracer.spans[:-1], strict=True):
        assert child.parent_span_id == parent.span_id


def test_chaos_non_semconv_key_rejected_by_validator() -> None:
    from LlmTrace import validate_semconv_key

    with pytest.raises(LlmTraceInvariantError):
        validate_semconv_key("custom.key")
    with pytest.raises(LlmTraceInvariantError):
        validate_semconv_key("")
