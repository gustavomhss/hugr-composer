"""Unit tests for StructuredLogger — confirms/prevents/under_failure per invariant."""

from __future__ import annotations

import json

import pytest
from StructuredLogger import (
    ALLOWED_LEVELS,
    REDACTED,
    InMemoryStructuredLogger,
    LogInvariantError,
    redact,
    validate_event_message,
    validate_level,
)


# LOG_INV_01 — one JSON line with ts/level/event + fields
def test_inv_json_single_line_confirms() -> None:
    log = InMemoryStructuredLogger()
    log.info("cache.hit", key="abc")
    line = log.records[0]
    assert "\n" not in line
    rec = json.loads(line)
    assert set(["ts", "level", "event"]).issubset(rec.keys())
    assert rec["event"] == "cache.hit" and rec["key"] == "abc"


def test_inv_json_single_line_prevents() -> None:
    log = InMemoryStructuredLogger()
    with pytest.raises(LogInvariantError):
        log.info("")
    with pytest.raises(LogInvariantError):
        validate_event_message("")


def test_inv_json_single_line_under_failure() -> None:
    log = InMemoryStructuredLogger()
    log.info("weird.values", payload=b"\x00\x01binary")  # type: ignore[arg-type]
    rec = json.loads(log.records[0])
    # Even binary-like fields must serialise to a string; line count = 1.
    assert "\n" not in log.records[0]
    assert "payload" in rec


# LOG_INV_02 — level taxonomy
def test_inv_level_taxonomy_confirms() -> None:
    assert frozenset({"DEBUG", "INFO", "WARN", "ERROR"}) == ALLOWED_LEVELS
    for level in ALLOWED_LEVELS:
        validate_level(level)


def test_inv_level_taxonomy_prevents() -> None:
    with pytest.raises(LogInvariantError):
        validate_level("TRACE")
    with pytest.raises(LogInvariantError):
        validate_level("FATAL")
    with pytest.raises(LogInvariantError):
        validate_level("notice")


def test_inv_level_taxonomy_under_failure() -> None:
    log = InMemoryStructuredLogger()
    # 50 valid emissions; none accidentally switch to a forbidden level.
    for _ in range(50):
        log.info("x")
    for line in log.records:
        assert json.loads(line)["level"] in ALLOWED_LEVELS


# LOG_INV_03 — span attachment when active
def test_inv_span_attachment_confirms() -> None:
    log = InMemoryStructuredLogger()
    log.activate_span("a" * 32, "b" * 16)
    log.info("scoped")
    rec = json.loads(log.records[0])
    assert rec["trace_id"] == "a" * 32
    assert rec["span_id"] == "b" * 16


def test_inv_span_attachment_prevents() -> None:
    log = InMemoryStructuredLogger()
    log.clear_span()
    log.info("none")
    rec = json.loads(log.records[0])
    assert "trace_id" not in rec
    assert "span_id" not in rec


def test_inv_span_attachment_under_failure() -> None:
    log = InMemoryStructuredLogger()
    log.activate_span("a" * 32, "b" * 16)
    log.clear_span()
    log.info("after.clear")
    rec = json.loads(log.records[0])
    assert "trace_id" not in rec


# LOG_INV_04 — no formatting placeholders in event
def test_inv_no_formatting_confirms() -> None:
    validate_event_message("user.login")
    validate_event_message("webhook.received")


def test_inv_no_formatting_prevents() -> None:
    with pytest.raises(LogInvariantError):
        validate_event_message("user.%s")
    with pytest.raises(LogInvariantError):
        validate_event_message("user.{id}")
    log = InMemoryStructuredLogger()
    with pytest.raises(LogInvariantError):
        log.info("login.%s", username="bob")


def test_inv_no_formatting_under_failure() -> None:
    log = InMemoryStructuredLogger()
    # Even under repeated emission attempts, invalid events NEVER serialise.
    for _ in range(10):
        with pytest.raises(LogInvariantError):
            log.info("bad.{thing}")
    assert log.records == []


# LOG_INV_05 — redaction
def test_inv_redaction_confirms() -> None:
    assert redact("Bearer abc123def456") == REDACTED
    assert redact("authorization: token") == REDACTED


def test_inv_redaction_prevents() -> None:
    log = InMemoryStructuredLogger()
    log.info("secret", header="Bearer abcdef1234")
    rec = json.loads(log.records[0])
    assert REDACTED in rec["header"]
    assert "abcdef1234" not in rec["header"]


def test_inv_redaction_under_failure() -> None:
    log = InMemoryStructuredLogger()
    log.error("ccfail", card="4111 1111 1111 1111")
    rec = json.loads(log.records[0])
    assert "4111" not in rec["card"]


# LOG_INV_06 — bind returns immutable child
def test_inv_bind_immutable_confirms() -> None:
    parent = InMemoryStructuredLogger()
    child = parent.bind(service="checkout")
    assert parent is not child
    child.info("msg")
    assert child.records and not parent.records


def test_inv_bind_immutable_prevents() -> None:
    parent = InMemoryStructuredLogger()
    child = parent.bind(k="v")
    # Bind MUST NOT mutate parent's bound dict.
    child.bind(x="y")
    parent.info("evt")
    rec = json.loads(parent.records[0])
    assert "k" not in rec  # parent's bound did not leak
    assert "x" not in rec


def test_inv_bind_immutable_under_failure() -> None:
    parent = InMemoryStructuredLogger()
    c1 = parent.bind(a=1)
    c2 = c1.bind(b=2)
    c2.info("e")
    parent.info("p")
    p_rec = json.loads(parent.records[0])
    c_rec = json.loads(c2.records[0])
    assert "a" not in p_rec
    assert "b" not in p_rec
    assert c_rec["a"] == 1 and c_rec["b"] == 2
