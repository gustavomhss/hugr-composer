"""Unit tests for AuditEvent."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from AuditEvent import (
    ALLOWED_ACTIONS,
    ALLOWED_OUTCOMES,
    AuditEvent,
    AuditEventInvariantError,
    InMemoryAuditSink,
    build_event,
    compute_event_hash,
)


def _evt(**overrides: object) -> AuditEvent:
    base: dict[str, object] = {
        "event_id": "evt-001",
        "actor_id": "u-1",
        "actor_type": "human",
        "action": "EXPORT",
        "resource_type": "user",
        "resource_id": "user-1",
        "outcome": "success",
        "attributes": {"reason": "dsar"},
        "prev_hash": "",
    }
    base.update(overrides)
    return build_event(**base)  # type: ignore[arg-type]


# AUD_INV_01 — hash chain integrity
def test_inv_hash_chain_confirms() -> None:
    e = _evt()
    assert compute_event_hash(e) == e.event_hash


def test_inv_hash_chain_prevents() -> None:
    sink = InMemoryAuditSink()
    e = _evt()
    tampered = replace(e, actor_id="tampered")
    with pytest.raises(AuditEventInvariantError):
        sink.emit(tampered)


def test_inv_hash_chain_under_failure() -> None:
    sink = InMemoryAuditSink()
    e1 = _evt(event_id="e1", prev_hash="")
    sink.emit(e1)
    # Build e2 with prev_hash pointing at e1.event_hash → chain verifies.
    e2 = _evt(event_id="e2", prev_hash=e1.event_hash)
    sink.emit(e2)
    assert sink.verify_chain() is True


# AUD_INV_02 — append-only
def test_inv_append_only_confirms() -> None:
    sink = InMemoryAuditSink()
    e = _evt()
    sink.emit(e)
    assert len(sink.events) == 1


def test_inv_append_only_prevents() -> None:
    sink = InMemoryAuditSink()
    # No delete/update surface is exposed.
    for attr in ("delete", "update", "remove", "pop"):
        assert not hasattr(sink, attr)


def test_inv_append_only_under_failure() -> None:
    sink = InMemoryAuditSink()
    for i in range(10):
        prev = sink.events[-1].event_hash if sink.events else ""
        sink.emit(_evt(event_id=f"e{i}", prev_hash=prev))
    assert len(sink.events) == 10


# AUD_INV_03 — outcome enum
def test_inv_outcome_enum_confirms() -> None:
    for outcome in ALLOWED_OUTCOMES:
        _evt(outcome=outcome)


def test_inv_outcome_enum_prevents() -> None:
    with pytest.raises(AuditEventInvariantError):
        _evt(outcome="okay")
    with pytest.raises(AuditEventInvariantError):
        _evt(outcome="partial")


def test_inv_outcome_enum_under_failure() -> None:
    with pytest.raises(AuditEventInvariantError):
        _evt(outcome="")


# AUD_INV_04 — actor required
def test_inv_actor_required_confirms() -> None:
    _evt(actor_id="system")
    _evt(actor_id="u-42")


def test_inv_actor_required_prevents() -> None:
    with pytest.raises(AuditEventInvariantError):
        _evt(actor_id="")


def test_inv_actor_required_under_failure() -> None:
    # None → build_event passes through to AuditEvent; dataclass requires str.
    with pytest.raises((AuditEventInvariantError, TypeError)):
        _evt(actor_id=None)  # type: ignore[arg-type]


# AUD_INV_05 — UTC timestamp required
def test_inv_utc_timestamp_confirms() -> None:
    e = _evt(occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert e.occurred_at.tzinfo is timezone.utc


def test_inv_utc_timestamp_prevents() -> None:
    with pytest.raises(AuditEventInvariantError):
        _evt(occurred_at=datetime(2026, 1, 1))  # naive


def test_inv_utc_timestamp_under_failure() -> None:
    from datetime import timedelta
    non_utc = timezone(timedelta(hours=3))
    with pytest.raises(AuditEventInvariantError):
        _evt(occurred_at=datetime(2026, 1, 1, tzinfo=non_utc))


# AUD_INV_06 — action vocabulary
def test_inv_action_vocabulary_confirms() -> None:
    for action in ALLOWED_ACTIONS:
        _evt(action=action)
    # Namespaced actions are accepted as explicit extensions.
    _evt(action="payment.refund")


def test_inv_action_vocabulary_prevents() -> None:
    with pytest.raises(AuditEventInvariantError):
        _evt(action="CUSTOM_ACTION")
    with pytest.raises(AuditEventInvariantError):
        _evt(action="whatever")


def test_inv_action_vocabulary_under_failure() -> None:
    with pytest.raises(AuditEventInvariantError):
        _evt(action="")
