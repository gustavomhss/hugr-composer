"""Metamorphic + differential for ErrorSink."""

from __future__ import annotations

from ErrorSink import InMemoryErrorSink, default_fingerprint


def test_metamorphic_fingerprint_stable_across_instances() -> None:
    def go() -> None:
        raise ValueError("same")

    fps = []
    for _ in range(3):
        try:
            go()
        except ValueError as e:
            fps.append("|".join(default_fingerprint(e)))
    assert len(set(fps)) == 1


def test_metamorphic_capture_returns_distinct_event_ids() -> None:
    sink = InMemoryErrorSink()
    ids: set[str] = set()
    for _ in range(20):
        try:
            raise RuntimeError("x")
        except RuntimeError as e:
            ids.add(sink.capture_exception(e))
    assert len(ids) == 20


def test_metamorphic_hook_order_preserves_semantics() -> None:
    sink = InMemoryErrorSink()
    sink.before_send(lambda ev: {**ev, "a": "1"})
    sink.before_send(lambda ev: {**ev, "b": "2"})
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    ev = sink.sent[0]
    assert ev["a"] == "1" and ev["b"] == "2"


def test_metamorphic_context_override_survives_copy() -> None:
    sink = InMemoryErrorSink()
    sink.set_context(trace_id="t1")
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    sink.set_context(trace_id="t2")
    try:
        raise ValueError("y")
    except ValueError as e:
        sink.capture_exception(e)
    traces = [ev["trace_id"] for ev in sink.sent]
    assert traces == ["t1", "t2"]


def test_differential_message_vs_exception_both_fingerprinted() -> None:
    sink = InMemoryErrorSink()
    sink.capture_message("some.failure")
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    for ev in sink.sent:
        assert "fingerprint" in ev


def test_metamorphic_before_send_chain_short_circuits_on_none() -> None:
    sink = InMemoryErrorSink()
    hit = {"b": False}
    sink.before_send(lambda ev: None)
    sink.before_send(lambda ev: (_ := hit.__setitem__("b", True)) or ev)
    try:
        raise ValueError("x")
    except ValueError as e:
        sink.capture_exception(e)
    assert sink.sent == []
    assert hit["b"] is False
