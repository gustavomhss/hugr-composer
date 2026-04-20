"""Metamorphic + differential for AuditEvent."""

from __future__ import annotations

from AuditEvent import InMemoryAuditSink, build_event, compute_event_hash


def _make(**o: object) -> "object":
    base = dict(event_id="e", actor_id="u", actor_type="h", action="READ",
                resource_type="r", resource_id="1", outcome="success",
                attributes={}, prev_hash="")
    base.update(o)
    return build_event(**base)  # type: ignore[return-value,arg-type]


def test_metamorphic_hash_deterministic_for_same_fields() -> None:
    e1 = _make()
    e2 = _make()
    # Same event_id + same fields except occurred_at → hashes differ; but stable input → stable hash.
    assert compute_event_hash(e1) == e1.event_hash  # type: ignore[attr-defined]
    assert compute_event_hash(e2) == e2.event_hash  # type: ignore[attr-defined]


def test_metamorphic_chain_links_verified() -> None:
    sink = InMemoryAuditSink()
    prev = ""
    hashes: list[str] = []
    for i in range(10):
        e = _make(event_id=f"e{i}", prev_hash=prev)
        sink.emit(e)  # type: ignore[arg-type]
        hashes.append(e.event_hash)  # type: ignore[attr-defined]
        prev = e.event_hash  # type: ignore[attr-defined]
    assert sink.verify_chain() is True
    # Each prev_hash equals the previous event's hash.
    for i in range(1, 10):
        assert sink.events[i].prev_hash == hashes[i - 1]


def test_metamorphic_modify_one_field_changes_hash() -> None:
    e1 = _make(actor_id="u-1")
    e2 = _make(actor_id="u-2")
    assert e1.event_hash != e2.event_hash  # type: ignore[attr-defined]


def test_metamorphic_attributes_order_insensitive() -> None:
    from datetime import datetime, timezone
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    e1 = _make(attributes={"a": "1", "b": "2"}, occurred_at=fixed)
    e2 = _make(attributes={"b": "2", "a": "1"}, occurred_at=fixed)
    # Canonical serialization sorts keys → same hash when all other fields match.
    assert compute_event_hash(e1) == compute_event_hash(e2)  # type: ignore[arg-type]


def test_differential_namespaced_action_vs_core() -> None:
    e1 = _make(action="READ")
    e2 = _make(action="payment.refund")
    assert e1.action != e2.action  # type: ignore[attr-defined]


def test_metamorphic_verify_chain_from_midpoint() -> None:
    sink = InMemoryAuditSink()
    prev = ""
    for i in range(5):
        e = _make(event_id=f"e{i}", prev_hash=prev)
        sink.emit(e)  # type: ignore[arg-type]
        prev = e.event_hash  # type: ignore[attr-defined]
    assert sink.verify_chain(from_event_id="e2") is True
