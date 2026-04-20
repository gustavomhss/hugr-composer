"""Chaos / fault-injection for StructuredLogger."""

from __future__ import annotations

import json
import threading

import pytest

from StructuredLogger import InMemoryStructuredLogger, LogInvariantError


def test_chaos_concurrent_bind_and_emit() -> None:
    parent = InMemoryStructuredLogger()

    def worker(i: int) -> None:
        child = parent.bind(thread_id=i)
        for _ in range(50):
            child.info("work")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Parent received nothing; records are local per child.
    assert parent.records == []


def test_chaos_malformed_event_string_rejected_repeatedly() -> None:
    log = InMemoryStructuredLogger()
    bad_events = ("%s.attempt", "user.{x}", "")
    for event in bad_events:
        for _ in range(10):
            with pytest.raises(LogInvariantError):
                log.info(event)
    assert log.records == []


def test_chaos_large_payload_still_single_line() -> None:
    log = InMemoryStructuredLogger()
    big = "a" * 50_000
    log.info("big.payload", blob=big)
    assert "\n" not in log.records[0]


def test_chaos_binary_field_does_not_crash() -> None:
    log = InMemoryStructuredLogger()
    log.info("binary", blob=b"\x00\x01\x02")  # type: ignore[arg-type]
    rec = json.loads(log.records[0])
    assert "blob" in rec


def test_chaos_forbidden_level_blocked_even_in_burst() -> None:
    log = InMemoryStructuredLogger()
    with pytest.raises(LogInvariantError):
        log._emit("TRACE", "x", {})  # type: ignore[attr-defined]
    with pytest.raises(LogInvariantError):
        log._emit("FATAL", "x", {})  # type: ignore[attr-defined]
    # Valid levels still work after failed attempts.
    log.info("recovery")
    assert len(log.records) == 1


def test_chaos_no_redaction_bypass_via_case() -> None:
    log = InMemoryStructuredLogger()
    log.info("mixed", k="BeArEr SecretToken1234")
    rec = json.loads(log.records[0])
    assert "SecretToken1234" not in rec["k"]


def test_chaos_concurrent_emit_thread_safe() -> None:
    log = InMemoryStructuredLogger()

    def worker() -> None:
        for _ in range(200):
            log.info("race")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(log.records) == 800
