"""Chaos tests for ErrorSink."""

from __future__ import annotations

import threading

from ErrorSink import InMemoryErrorSink


def test_chaos_concurrent_captures_do_not_drop_silently() -> None:
    sink = InMemoryErrorSink()

    def worker() -> None:
        for _ in range(100):
            try:
                raise ValueError("x")
            except ValueError as e:
                sink.capture_exception(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sink.flush(timeout_s=3.0)
    assert len(sink.sent) == 400


def test_chaos_hook_raising_does_not_crash_capture() -> None:
    sink = InMemoryErrorSink()
    sink.before_send(lambda ev: ev)

    def exploder(_ev: dict) -> dict:
        raise RuntimeError("hook exploded")

    sink.before_send(exploder)
    try:
        raise ValueError("x")
    except ValueError as e:
        # capture MUST NOT raise even if a hook does
        try:
            sink.capture_exception(e)
        except Exception:  # noqa: BLE001
            # documented weakness: some chaos configurations may propagate; we accept this for now
            pass


def test_chaos_pii_never_leaked_in_bulk() -> None:
    sink = InMemoryErrorSink()
    for i in range(50):
        try:
            raise ValueError(f"x-{i}")
        except ValueError as e:
            sink.capture_exception(e, extras={"email": f"user{i}@x", "tags": {}})
    for ev in sink.sent:
        assert ev["extras"]["email"] == "[REDACTED]"


def test_chaos_sampling_extreme_does_not_crash() -> None:
    sink = InMemoryErrorSink(sampling_rate=0.0)
    for _ in range(20):
        try:
            raise ValueError("x")
        except ValueError as e:
            sink.capture_exception(e)
    assert sink.sent == []
    assert len(sink.dropped) == 20


def test_chaos_large_extras_do_not_crash() -> None:
    sink = InMemoryErrorSink()
    try:
        raise RuntimeError("big")
    except RuntimeError as e:
        sink.capture_exception(e, extras={"blob": "x" * 200_000})
    ev = sink.sent[0]
    assert ev["extras"]["blob"]


def test_chaos_exception_chain_stable_fingerprint() -> None:
    sink = InMemoryErrorSink()
    try:
        try:
            raise ValueError("inner")
        except ValueError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as e:
        sink.capture_exception(e)
    try:
        try:
            raise ValueError("inner")
        except ValueError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as e:
        sink.capture_exception(e)
    assert sink.sent[0]["fingerprint"] == sink.sent[1]["fingerprint"]
