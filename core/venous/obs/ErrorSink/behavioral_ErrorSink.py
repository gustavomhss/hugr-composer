"""Behavioral scenarios for ErrorSink."""

from __future__ import annotations

from ErrorSink import InMemoryErrorSink


def test_scenario_payment_declined() -> None:
    sink = InMemoryErrorSink()
    sink.set_context(trace_id="trace-1", request_id="req-1")
    try:
        raise RuntimeError("card declined")
    except RuntimeError as e:
        eid = sink.capture_exception(e, level="warning",
                                     tags={"order.id": "o-1", "gateway": "stripe"})
    assert eid
    ev = sink.sent[0]
    assert ev["level"] == "warning"
    assert ev["trace_id"] == "trace-1"


def test_scenario_fingerprint_groups_same_error() -> None:
    sink = InMemoryErrorSink()
    for _ in range(3):
        try:
            raise ValueError("invariant")
        except ValueError as e:
            sink.capture_exception(e)
    fps = {ev["fingerprint"] for ev in sink.sent}
    assert len(fps) == 1


def test_scenario_custom_fingerprinter_groups_differently() -> None:
    sink = InMemoryErrorSink()
    sink.register_fingerprinter(lambda exc: [str(exc)])
    try:
        raise ValueError("A")
    except ValueError as e:
        sink.capture_exception(e)
    try:
        raise ValueError("B")
    except ValueError as e:
        sink.capture_exception(e)
    fps = {ev["fingerprint"] for ev in sink.sent}
    assert len(fps) == 2


def test_scenario_before_send_drops_noise() -> None:
    sink = InMemoryErrorSink()
    sink.before_send(lambda ev: None if ev.get("level") == "debug" else ev)
    try:
        raise RuntimeError("d")
    except RuntimeError as e:
        sink.capture_exception(e, level="debug")
    try:
        raise RuntimeError("e")
    except RuntimeError as e:
        sink.capture_exception(e, level="error")
    assert len(sink.sent) == 1


def test_scenario_pii_never_leaks_to_wire() -> None:
    sink = InMemoryErrorSink()
    try:
        raise RuntimeError("dsar")
    except RuntimeError as e:
        sink.capture_exception(e, extras={"email": "user@example.com", "cpf": "11111"})
    ev = sink.sent[0]
    assert ev["extras"]["email"] == "[REDACTED]"
    assert ev["extras"]["cpf"] == "[REDACTED]"


def test_scenario_capture_message_path() -> None:
    sink = InMemoryErrorSink()
    eid = sink.capture_message("background.failure", level="warning",
                               tags={"job": "export"})
    assert eid
    assert sink.sent[0]["message"] == "background.failure"
