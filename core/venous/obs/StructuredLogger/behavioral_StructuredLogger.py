"""Behavioral scenarios for StructuredLogger."""

from __future__ import annotations

import json

import pytest

from StructuredLogger import InMemoryStructuredLogger, LogInvariantError, REDACTED


def test_scenario_webhook_flow() -> None:
    log = InMemoryStructuredLogger()
    scoped = log.bind(event_id="evt-1", integration="stripe")
    scoped.info("webhook.received", payload_size=100)
    scoped.info("webhook.processed")
    assert len(scoped.records) == 2


def test_scenario_error_with_exception() -> None:
    log = InMemoryStructuredLogger()
    try:
        raise ValueError("bad")
    except ValueError as exc:
        log.error("webhook.rejected", reason="invalid", exc=exc)
    rec = json.loads(log.records[0])
    assert rec["exception.type"] == "ValueError"
    assert rec["exception.message"] == "bad"


def test_scenario_bind_isolation() -> None:
    parent = InMemoryStructuredLogger()
    child_a = parent.bind(tenant="A")
    child_b = parent.bind(tenant="B")
    child_a.info("a-msg")
    child_b.info("b-msg")
    assert json.loads(child_a.records[0])["tenant"] == "A"
    assert json.loads(child_b.records[0])["tenant"] == "B"


def test_scenario_trace_correlation_injected() -> None:
    log = InMemoryStructuredLogger()
    log.activate_span("0" * 32, "1" * 16)
    log.info("work")
    rec = json.loads(log.records[0])
    assert rec["trace_id"] == "0" * 32


def test_scenario_formatting_placeholder_rejected() -> None:
    log = InMemoryStructuredLogger()
    with pytest.raises(LogInvariantError):
        log.info("login.%d", user=123)


def test_scenario_redacts_authorization_header() -> None:
    log = InMemoryStructuredLogger()
    log.info("req", auth_header="Bearer supersecrettoken1234")
    rec = json.loads(log.records[0])
    assert REDACTED in rec["auth_header"]
