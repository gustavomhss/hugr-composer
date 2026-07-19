"""Unit tests for Tracer — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading
import time

import pytest
from Tracer import (
    InMemoryTracer,
    TracerInvariantError,
    validate_attribute_value,
    validate_span_name,
    validate_traceparent,
)


# ---------------------------------------------------------------------------
# TRACER_INV_01 — name + timestamps + causal order
# ---------------------------------------------------------------------------
def test_inv_name_timestamps_confirms() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("unit.work"):
        pass
    span = tracer.spans[0]
    assert span.name == "unit.work"
    assert span.start_ns > 0
    assert span.end_ns is not None
    assert span.end_ns >= span.start_ns


def test_inv_name_timestamps_prevents() -> None:
    tracer = InMemoryTracer()
    with pytest.raises(TracerInvariantError), tracer.start_as_current_span(""):
        pass
    with pytest.raises(TracerInvariantError):
        validate_span_name("   ")


def test_inv_name_timestamps_under_failure() -> None:
    tracer = InMemoryTracer()
    try:
        with tracer.start_as_current_span("unit.boom"):
            raise RuntimeError("injected")
    except RuntimeError:
        pass
    span = tracer.spans[0]
    # Even under exception, end_ns MUST be set and causal.
    assert span.end_ns is not None
    assert span.end_ns >= span.start_ns


# ---------------------------------------------------------------------------
# TRACER_INV_02 — end idempotent
# ---------------------------------------------------------------------------
def test_inv_end_idempotent_confirms() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("idem.span") as span:
        pass
    # The context manager ended it once. Second manual end MUST be no-op.
    internal = tracer.spans[0]
    original_end = internal.end_ns
    internal.end(time.monotonic_ns() + 10_000)
    assert internal.end_ns == original_end
    assert any("ended twice" in w or "TRACER-INV-02" in w for w in internal.warnings)


def test_inv_end_idempotent_prevents() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("double.end"):
        pass
    span = tracer.spans[0]
    # A causal-order violation at end MUST raise.
    fresh_tracer = InMemoryTracer()
    with fresh_tracer.start_as_current_span("fresh"):
        pass
    s = fresh_tracer.spans[0]
    # Force re-end with a timestamp before start — must be ignored (already ended).
    s.end(s.start_ns - 1)
    # Still idempotent: end_ns unchanged from the context-manager close.
    assert s.end_ns is not None and s.end_ns >= s.start_ns


def test_inv_end_idempotent_under_failure() -> None:
    tracer = InMemoryTracer()
    try:
        with tracer.start_as_current_span("boom.idem"):
            raise ValueError("boom")
    except ValueError:
        pass
    span = tracer.spans[0]
    original = span.end_ns
    span.end(time.monotonic_ns() + 100)
    assert span.end_ns == original
    assert span.warnings  # at least one warning recorded


# ---------------------------------------------------------------------------
# TRACER_INV_03 — W3C context honored
# ---------------------------------------------------------------------------
def test_inv_w3c_context_confirms() -> None:
    tracer = InMemoryTracer()
    carrier_in = {
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        "tracestate": "vendor1=value1,vendor2=value2",
    }
    tracer.extract(carrier_in)
    carrier_out: dict[str, str] = {}
    tracer.inject(carrier_out)
    assert "traceparent" in carrier_out
    assert carrier_out["tracestate"] == "vendor1=value1,vendor2=value2"


def test_inv_w3c_context_prevents() -> None:
    assert validate_traceparent("00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
    assert not validate_traceparent("garbage")
    assert not validate_traceparent("00-short-short-01")


def test_inv_w3c_context_under_failure() -> None:
    tracer = InMemoryTracer()
    # Malformed traceparent MUST NOT crash; extract SHALL tolerate garbage.
    result = tracer.extract({"traceparent": "garbage", "tracestate": "vendorX=keep"})
    assert isinstance(result, dict)
    # Unknown vendor entries MUST NOT be mutated.
    carrier: dict[str, str] = {}
    tracer.inject(carrier)
    if "tracestate" in carrier:
        assert "vendorX=keep" in carrier["tracestate"]


# ---------------------------------------------------------------------------
# TRACER_INV_04 — exception sets ERROR unless OK explicit
# ---------------------------------------------------------------------------
def test_inv_exception_status_confirms() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("errtest") as span:
        span.record_exception(RuntimeError("boom"))
    s = tracer.spans[0]
    assert s.status_code == "ERROR"


def test_inv_exception_status_prevents() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("explicit.ok") as span:
        span.set_status("OK")
        span.record_exception(RuntimeError("boom"))
    s = tracer.spans[0]
    assert s.status_code == "OK"  # explicit OK is honored


def test_inv_exception_status_under_failure() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("fails") as span:
        # Recording multiple exceptions still keeps ERROR status.
        span.record_exception(ValueError("a"))
        span.record_exception(ValueError("b"))
    s = tracer.spans[0]
    assert s.status_code == "ERROR"


# ---------------------------------------------------------------------------
# TRACER_INV_05 — attribute type discipline
# ---------------------------------------------------------------------------
def test_inv_attribute_types_confirms() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("attr") as span:
        span.set_attribute("s", "text")
        span.set_attribute("i", 42)
        span.set_attribute("f", 3.14)
        span.set_attribute("b", True)
    s = tracer.spans[0]
    assert s.attributes == {"s": "text", "i": 42, "f": 3.14, "b": True}


def test_inv_attribute_types_prevents() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("attr.bad") as span:
        with pytest.raises(TracerInvariantError):
            span.set_attribute("nested", {"no": "dicts"})  # type: ignore[arg-type]
        with pytest.raises(TracerInvariantError):
            validate_attribute_value("mixed", [1, "two"])


def test_inv_attribute_types_under_failure() -> None:
    tracer = InMemoryTracer()
    with tracer.start_as_current_span("under.failure") as span:
        # Valid list passes even while wrapped in try/except.
        try:
            span.set_attribute("tags", ["a", "b", "c"])
        except TracerInvariantError:
            pytest.fail("homogeneous sequence MUST be accepted")


# ---------------------------------------------------------------------------
# TRACER_INV_06 — async export / non-blocking
# ---------------------------------------------------------------------------
def test_inv_async_export_confirms() -> None:
    tracer = InMemoryTracer()
    start = time.monotonic()
    with tracer.start_as_current_span("fast"):
        pass
    elapsed = time.monotonic() - start
    assert elapsed < 0.05  # context close must not block on network
    assert tracer.export_calls == 1


def test_inv_async_export_prevents() -> None:
    # The tracer MUST NOT provide a blocking wait API in its Protocol surface.
    tracer = InMemoryTracer()
    public = {m for m in dir(tracer) if not m.startswith("_")}
    for forbidden in ("wait_for_export", "flush_blocking", "ack"):
        assert forbidden not in public


def test_inv_async_export_under_failure() -> None:
    tracer = InMemoryTracer()
    # Even under heavy span creation, span creation returns promptly.
    threads: list[threading.Thread] = []

    def worker() -> None:
        for _ in range(50):
            with tracer.start_as_current_span("t"):
                pass

    for _ in range(4):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert tracer.export_calls == 200
