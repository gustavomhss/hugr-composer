"""Chaos tests for AuditEvent."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from AuditEvent import (
    AuditEventInvariantError,
    InMemoryAuditSink,
    build_event,
    compute_event_hash,
)


def _make(**o: object) -> object:
    base = dict(event_id="e", actor_id="u", actor_type="h", action="READ",
                resource_type="r", resource_id="1", outcome="success",
                attributes={}, prev_hash="")
    base.update(o)
    return build_event(**base)  # type: ignore[arg-type]


def test_chaos_tamper_detection() -> None:
    sink = InMemoryAuditSink()
    e = _make()
    tampered = replace(e, outcome="denied")  # type: ignore[arg-type]
    with pytest.raises(AuditEventInvariantError):
        sink.emit(tampered)  # type: ignore[arg-type]


def test_chaos_broken_chain_detected() -> None:
    sink = InMemoryAuditSink()
    e1 = _make(event_id="e1", prev_hash="")
    sink.emit(e1)  # type: ignore[arg-type]
    # Build e2 with WRONG prev_hash and then sink it directly without re-verify path.
    e2 = _make(event_id="e2", prev_hash="badhash")
    sink.emit(e2)  # type: ignore[arg-type]
    # The chain now has a mismatched prev_hash link.
    assert sink.verify_chain() is False


def test_chaos_concurrent_emits_preserved() -> None:
    sink = InMemoryAuditSink()

    def worker(i: int) -> None:
        sink.emit(_make(event_id=f"e{i}"))  # type: ignore[arg-type]

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sink.events) == 20


def test_chaos_invalid_outcomes_rejected_repeatedly() -> None:
    for bad in ("ok", "partial", "", "SUCCESS"):
        with pytest.raises(AuditEventInvariantError):
            _make(outcome=bad)


def test_chaos_hash_over_large_attrs() -> None:
    attrs = {f"k{i}": "v" for i in range(100)}
    e = _make(attributes=attrs)
    assert compute_event_hash(e) == e.event_hash  # type: ignore[attr-defined]


def test_chaos_timezone_spoofing_rejected() -> None:
    from datetime import timedelta
    with pytest.raises(AuditEventInvariantError):
        _make(occurred_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-7))))
