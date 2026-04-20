"""Behavioral scenarios for AuditEvent."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from AuditEvent import (
    AuditEventInvariantError,
    InMemoryAuditSink,
    build_event,
    compute_event_hash,
)


def test_scenario_dsar_export() -> None:
    e = build_event(
        event_id="evt-1", actor_id="u-alice", actor_type="human",
        action="EXPORT", resource_type="user", resource_id="u-123",
        outcome="success", attributes={"reason": "dsar"}, prev_hash="",
    )
    assert e.event_hash == compute_event_hash(e)


def test_scenario_chain_verification() -> None:
    sink = InMemoryAuditSink()
    prev = ""
    for i in range(5):
        e = build_event(event_id=f"e{i}", actor_id="system", actor_type="service",
                        action="UPDATE", resource_type="config", resource_id=f"c{i}",
                        outcome="success", attributes={}, prev_hash=prev)
        sink.emit(e)
        prev = e.event_hash
    assert sink.verify_chain() is True


def test_scenario_denied_outcome_accepted() -> None:
    e = build_event(event_id="e1", actor_id="u-1", actor_type="human",
                    action="READ", resource_type="doc", resource_id="d1",
                    outcome="denied", attributes={}, prev_hash="")
    assert e.outcome == "denied"


def test_scenario_namespaced_extension_action() -> None:
    e = build_event(event_id="e1", actor_id="u-1", actor_type="human",
                    action="payment.refund", resource_type="charge", resource_id="ch-1",
                    outcome="success", attributes={}, prev_hash="")
    assert e.action == "payment.refund"


def test_scenario_tampering_fails_verify() -> None:
    sink = InMemoryAuditSink()
    e1 = build_event(event_id="e1", actor_id="u", actor_type="h",
                     action="CREATE", resource_type="r", resource_id="1",
                     outcome="success", attributes={}, prev_hash="")
    sink.emit(e1)
    # Break chain by emitting with wrong prev_hash: build_event recomputes so
    # test by direct dataclass.
    from dataclasses import replace
    bad = replace(e1, actor_id="tampered")
    with pytest.raises(AuditEventInvariantError):
        sink.emit(bad)


def test_scenario_naive_timestamp_rejected() -> None:
    with pytest.raises(AuditEventInvariantError):
        build_event(event_id="e1", actor_id="u", actor_type="h",
                    action="CREATE", resource_type="r", resource_id="1",
                    outcome="success", attributes={}, prev_hash="",
                    occurred_at=datetime(2026, 1, 1))
