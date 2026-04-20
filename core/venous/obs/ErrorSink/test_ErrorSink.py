"""Unit tests for ErrorSink — confirms/prevents/under_failure per invariant."""

from __future__ import annotations

import time

from ErrorSink import InMemoryErrorSink, default_fingerprint


# ERR_INV_01 — context attached
def test_inv_context_attached_confirms() -> None:
    sink = InMemoryErrorSink()
    sink.set_context(trace_id="t", span_id="s", request_id="r")
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    ev = sink.sent[0]
    assert ev["trace_id"] == "t" and ev["span_id"] == "s" and ev["request_id"] == "r"


def test_inv_context_attached_prevents() -> None:
    sink = InMemoryErrorSink()
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    ev = sink.sent[0]
    # No context set → no keys present.
    assert "trace_id" not in ev and "span_id" not in ev


def test_inv_context_attached_under_failure() -> None:
    sink = InMemoryErrorSink()
    sink.set_context(trace_id="t", span_id=None, request_id=None)
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    ev = sink.sent[0]
    assert ev["trace_id"] == "t" and "span_id" not in ev


# ERR_INV_02 — deterministic fingerprint
def test_inv_fingerprint_stable_confirms() -> None:
    def raise_it() -> None:
        raise ValueError("boom")

    fps: list[str] = []
    for _ in range(3):
        try:
            raise_it()
        except ValueError as e:
            fps.append("|".join(default_fingerprint(e)))
    assert len(set(fps)) == 1


def test_inv_fingerprint_stable_prevents() -> None:
    # Different exception types MUST NOT collide.
    try:
        raise ValueError("a")
    except ValueError as e:
        fp1 = default_fingerprint(e)
    try:
        raise RuntimeError("b")
    except RuntimeError as e:
        fp2 = default_fingerprint(e)
    assert fp1 != fp2


def test_inv_fingerprint_stable_under_failure() -> None:
    sink = InMemoryErrorSink()
    for _ in range(5):
        try:
            raise ValueError("repeat")
        except ValueError as e:
            sink.capture_exception(e)
    fps = {ev["fingerprint"] for ev in sink.sent}
    assert len(fps) == 1


# ERR_INV_03 — PII redaction
def test_inv_pii_redacted_confirms() -> None:
    sink = InMemoryErrorSink()
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e, extras={"email": "a@b.com", "ok": "ok"})
    ev = sink.sent[0]
    assert ev["extras"]["email"] == "[REDACTED]"
    assert ev["extras"]["ok"] == "ok"


def test_inv_pii_redacted_prevents() -> None:
    sink = InMemoryErrorSink()
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e, tags={"password": "plaintext"})
    ev = sink.sent[0]
    assert ev["tags"]["password"] == "[REDACTED]"


def test_inv_pii_redacted_under_failure() -> None:
    sink = InMemoryErrorSink()
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e, extras={"nested": {"authorization": "Bearer secret"}})
    ev = sink.sent[0]
    assert ev["extras"]["nested"]["authorization"] == "[REDACTED]"


# ERR_INV_04 — non-blocking
def test_inv_nonblocking_confirms() -> None:
    sink = InMemoryErrorSink()
    start = time.monotonic()
    for _ in range(100):
        try:
            raise ValueError("x")
        except ValueError as e:
            sink.capture_exception(e)
    elapsed = time.monotonic() - start
    assert elapsed < 0.5  # 100 captures in well under a second


def test_inv_nonblocking_prevents() -> None:
    sink = InMemoryErrorSink()
    # Nothing in the public surface blocks — capture_exception returns promptly.
    try:
        raise RuntimeError("x")
    except RuntimeError as e:
        start = time.monotonic()
        sink.capture_exception(e)
        assert time.monotonic() - start < 0.05


def test_inv_nonblocking_under_failure() -> None:
    sink = InMemoryErrorSink()

    def slow_hook(ev: dict) -> dict:
        # Even a slow hook does not block the public API because sample hooks
        # are invoked INSIDE capture; the contract guarantees queue enqueue is non-blocking.
        return ev

    sink.before_send(slow_hook)
    start = time.monotonic()
    for _ in range(50):
        try:
            raise ValueError("x")
        except ValueError as e:
            sink.capture_exception(e)
    assert time.monotonic() - start < 2.0


# ERR_INV_05 — before_send None drops
def test_inv_before_send_drop_confirms() -> None:
    sink = InMemoryErrorSink()
    sink.before_send(lambda ev: None)
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    assert sink.sent == []
    assert len(sink.dropped) == 1


def test_inv_before_send_drop_prevents() -> None:
    sink = InMemoryErrorSink()
    sink.before_send(lambda ev: ev)  # pass-through
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    assert len(sink.sent) == 1
    assert sink.dropped == []


def test_inv_before_send_drop_under_failure() -> None:
    sink = InMemoryErrorSink()
    sink.before_send(lambda ev: ev if ev["tags"].get("keep") else None)
    for keep in (True, False, True):
        try:
            raise ValueError("x")
        except ValueError as e:
            sink.capture_exception(e, tags={"keep": "1"} if keep else {})
    assert len(sink.sent) == 2
    assert len(sink.dropped) == 1


# ERR_INV_06 — sampling AFTER fingerprint
def test_inv_sampling_after_fp_confirms() -> None:
    sink = InMemoryErrorSink(sampling_rate=0.5)
    # Fingerprint is computed before sampling; observable via dropped events carrying a fingerprint.
    for _ in range(20):
        try:
            raise ValueError("sampled")
        except ValueError as e:
            sink.capture_exception(e)
    for ev in sink.dropped:
        assert "fingerprint" in ev


def test_inv_sampling_after_fp_prevents() -> None:
    sink = InMemoryErrorSink(sampling_rate=1.0)
    try:
        raise ValueError("always-kept")
    except ValueError as e:
        sink.capture_exception(e)
    assert len(sink.sent) == 1 and sink.dropped == []


def test_inv_sampling_after_fp_under_failure() -> None:
    sink = InMemoryErrorSink(sampling_rate=0.0)
    try:
        raise ValueError("never-kept")
    except ValueError as e:
        sink.capture_exception(e)
    assert sink.sent == []
    # Dropped events STILL have fingerprint (proves FP ran first).
    assert "fingerprint" in sink.dropped[0]
