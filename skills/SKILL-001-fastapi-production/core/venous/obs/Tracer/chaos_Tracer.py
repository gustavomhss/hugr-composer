"""Chaos / fault-injection for Tracer.

Game-day scenarios: exporter simulated slow, malformed carriers, clock skew,
threaded contention. Tracer MUST remain correct under each.
"""

from __future__ import annotations

import threading
import time

import pytest

from Tracer import InMemoryTracer, TracerInvariantError


def test_chaos_malformed_traceparent_does_not_crash() -> None:
    tracer = InMemoryTracer()
    for bad in ("", "x", "00-" + "z" * 32 + "-abcd-01", None):
        try:
            tracer.extract({"traceparent": bad if isinstance(bad, str) else ""})
        except Exception as exc:  # noqa: BLE001 — intentional catch-all
            pytest.fail(f"extract raised on malformed input: {exc!r}")


def test_chaos_clock_skew_backward_rejected() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("skew"):
        pass
    s = tracer.spans[0]
    # Calling end() with a pre-start timestamp is a no-op (already ended)
    # but on a never-ended span it MUST raise.
    s2 = type(s)(name="raw", kind="INTERNAL", start_ns=10_000)
    with pytest.raises(TracerInvariantError):
        s2.end(end_ns=5_000)


def test_chaos_concurrent_span_creation_is_safe() -> None:
    tracer = InMemoryTracer()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(200):
                with tracer.start_as_current_span("race"):
                    pass
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(tracer.spans) == 1600


def test_chaos_attribute_injection_rejected() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("injection") as span:
        with pytest.raises(TracerInvariantError):
            span.set_attribute("payload", object())  # type: ignore[arg-type]


def test_chaos_oversized_tracestate_truncated() -> None:
    tracer = InMemoryTracer()
    many = ",".join(f"v{i}=x" for i in range(200))
    tracer.extract({
        "traceparent": "00-33333333333333333333333333333333-4444444444444444-01",
        "tracestate": many,
    })
    carrier: dict[str, str] = {}
    tracer.inject(carrier)
    # Tracestate entries MUST NOT exceed the per-W3C guidance (≤ 32 entries).
    assert carrier["tracestate"].count("=") <= 32


def test_chaos_record_exception_with_custom_exception_type() -> None:
    class DomainError(RuntimeError):
        pass

    tracer = InMemoryTracer()
    with tracer.start_as_current_span("domain") as span:
        span.record_exception(DomainError("trouble"))
    assert tracer.spans[0].status_code == "ERROR"


def test_chaos_attribute_sequence_type_mismatch_under_load() -> None:
    tracer = InMemoryTracer()
    failures = 0
    with tracer.start_as_current_span("loop") as span:
        for i in range(100):
            try:
                span.set_attribute("mixed", [1, "two", 3.0])  # type: ignore[arg-type]
            except TracerInvariantError:
                failures += 1
    assert failures == 100
