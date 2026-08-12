"""Unit tests for DomainEvent — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading
import uuid

import pytest
from DomainEvent import (
    AggregateEventStream,
    AggregateStreamError,
    DomainEventInvariantError,
    FrozenDomainEvent,
    InMemoryDedupSet,
    SchemaDescriptor,
    SchemaRegistry,
    SchemaRegistryError,
)

# ---------------------------------------------------------------------------
# Helpers — synthetic UUID v7 generator (no real time dependency)
# ---------------------------------------------------------------------------
_UUID_COUNTER = 0
_UUID_LOCK = threading.Lock()


def uuid_v7(seed: int | None = None) -> str:
    """Deterministic UUID v7-shaped string for tests.

    Layout: 8-4-4-4-12 hex. Nibble 13 forced to '7' (version), nibble 17 to '8'..'b'.
    We use a simple counter so tests are deterministic and unique per call.
    """
    global _UUID_COUNTER
    with _UUID_LOCK:
        if seed is None:
            _UUID_COUNTER += 1
            seed = _UUID_COUNTER
    raw = uuid.UUID(int=seed | (0x7 << 76) | (0x8 << 60))
    s = str(raw)
    # Force version nibble (index 14) to '7' and variant nibble (index 19) to '8'..'b'.
    chars = list(s)
    chars[14] = "7"
    if chars[19] not in ("8", "9", "a", "b"):
        chars[19] = "8"
    return "".join(chars)


def make_event(
    *,
    version: int = 1,
    aggregate_id: str = "acct-1",
    aggregate_type: str = "Account",
    event_type: str = "account.opened",
    schema_version: int = 1,
    payload: dict[str, object] | None = None,
    event_id: str | None = None,
    occurred_at: str = "2025-01-01T00:00:00Z",
) -> FrozenDomainEvent:
    return FrozenDomainEvent(
        event_id=event_id or uuid_v7(),
        aggregate_id=aggregate_id,
        occurred_at=occurred_at,
        version=version,
        payload=payload or {"currency": "USD"},
        aggregate_type=aggregate_type,
        event_type=event_type,
        schema_version=schema_version,
    )


# ---------------------------------------------------------------------------
# DE_INV_01 — immutability after construction
# ---------------------------------------------------------------------------
def test_inv_immutable_confirms() -> None:
    evt = make_event(payload={"amount": 100, "nested": {"k": "v"}})
    # Attribute mutation is forbidden (frozen dataclass).
    with pytest.raises((AttributeError, TypeError, DomainEventInvariantError)):
        evt.version = 2  # type: ignore[misc]  # DE-INV-01: frozen
    # Payload is a MappingProxyType — reassigning keys must fail.
    with pytest.raises(TypeError):
        evt.payload["amount"] = 999  # type: ignore[index]  # DE-INV-01: MappingProxyType
    # Deep payload mutation must also fail (nested dict is frozen).
    with pytest.raises(TypeError):
        evt.payload["nested"]["k"] = "x"  # type: ignore[index]  # DE-INV-01: nested proxy


def test_inv_immutable_prevents() -> None:
    # Mutating the source dict after construction MUST NOT affect the event.
    src: dict[str, object] = {"amount": 100}
    evt = make_event(payload=src)
    src["amount"] = 999
    src["new"] = "added"
    assert evt.payload["amount"] == 100
    assert "new" not in evt.payload


def test_inv_immutable_under_failure() -> None:
    # Rolled-back / discarded streams still observe immutability of staged events.
    stream = AggregateEventStream()
    evt = make_event(version=1)
    stream.stage(evt)
    stream.discard()
    # Event object itself is still frozen and readable.
    assert evt.version == 1
    assert evt.payload["currency"] == "USD"
    with pytest.raises((AttributeError, TypeError)):
        evt.version = 42  # type: ignore[misc]  # DE-INV-01: frozen


# ---------------------------------------------------------------------------
# DE_INV_02 — event_id globally unique (UUID v7) and stable
# ---------------------------------------------------------------------------
def test_inv_event_id_unique_confirms() -> None:
    dedup = InMemoryDedupSet()
    ids = {uuid_v7() for _ in range(500)}
    assert len(ids) == 500
    for eid in ids:
        evt = make_event(event_id=eid)
        assert dedup.accept(evt) is True
    assert dedup.size() == 500


def test_inv_event_id_unique_prevents() -> None:
    # Non-UUID-v7 strings are rejected at construction.
    with pytest.raises(DomainEventInvariantError):
        make_event(event_id="not-a-uuid")
    with pytest.raises(DomainEventInvariantError):
        # UUID v4 (version nibble '4') is rejected.
        make_event(event_id="12345678-1234-4234-8234-123456789012")
    # Staging the same event_id twice is rejected.
    stream = AggregateEventStream()
    eid = uuid_v7()
    stream.stage(make_event(event_id=eid, version=1))
    with pytest.raises(AggregateStreamError):
        stream.stage(make_event(event_id=eid, version=2))


def test_inv_event_id_unique_under_failure() -> None:
    dedup = InMemoryDedupSet()
    eid = uuid_v7()
    evt = make_event(event_id=eid)
    assert dedup.accept(evt) is True
    # Retries with the same event_id NEVER dedupe through twice.
    for _ in range(100):
        assert dedup.accept(evt) is False
    assert dedup.size() == 1


# ---------------------------------------------------------------------------
# DE_INV_03 — fact-only, no commands / intents
# ---------------------------------------------------------------------------
def test_inv_fact_only_confirms() -> None:
    # Past-tense, dotted, lowercase — accepted.
    for et in [
        "account.opened",
        "order.placed",
        "invoice.issued",
        "order.line.added_at_checkout",
        "payment.captured",
    ]:
        evt = make_event(event_type=et)
        assert evt.event_type == et


def test_inv_fact_only_prevents() -> None:
    # Imperative verbs MUST be rejected as the terminal segment.
    for bad in [
        "account.create",
        "order.place",
        "user.update",
        "payment.process",
        "order.delete",
    ]:
        with pytest.raises(DomainEventInvariantError):
            make_event(event_type=bad)


def test_inv_fact_only_under_failure() -> None:
    # Malformed / non-string types MUST all be rejected with a DE-INV-03 message.
    bad_inputs: list[object] = ["", "NoDot", "Bad.Case", "no-dots", 42, None, "a..b"]
    for bad in bad_inputs:
        with pytest.raises(DomainEventInvariantError):
            make_event(event_type=bad)  # type: ignore[arg-type]  # DE-INV-03: intentional bad input


# ---------------------------------------------------------------------------
# DE_INV_04 — strictly monotonic per-aggregate versioning
# ---------------------------------------------------------------------------
def test_inv_version_monotonic_confirms() -> None:
    stream = AggregateEventStream()
    published: list[FrozenDomainEvent] = []
    for v in range(1, 11):
        stream.stage(make_event(version=v, aggregate_id="acct-1"))
    stream.flush(published.append)
    assert [e.version for e in published] == list(range(1, 11))
    assert stream.last_version("Account", "acct-1") == 10


def test_inv_version_monotonic_prevents() -> None:
    stream = AggregateEventStream()
    # Gap — versions must start at 1.
    with pytest.raises(AggregateStreamError):
        stream.stage(make_event(version=2, aggregate_id="acct-1"))
    stream.stage(make_event(version=1, aggregate_id="acct-1"))
    # Duplicate version within same aggregate.
    with pytest.raises(AggregateStreamError):
        stream.stage(make_event(version=1, aggregate_id="acct-1"))
    # Retroactive / gap after successful stage.
    with pytest.raises(AggregateStreamError):
        stream.stage(make_event(version=3, aggregate_id="acct-1"))


def test_inv_version_monotonic_under_failure() -> None:
    stream = AggregateEventStream()
    # Attempt many invalid versions; only the valid stream progresses.
    stream.stage(make_event(version=1, aggregate_id="acct-2"))
    for bad_v in [1, 3, 5, 100, 0]:
        try:
            stream.stage(make_event(version=bad_v, aggregate_id="acct-2"))
        except (AggregateStreamError, DomainEventInvariantError):
            pass
    stream.stage(make_event(version=2, aggregate_id="acct-2"))
    published: list[FrozenDomainEvent] = []
    stream.flush(published.append)
    assert [e.version for e in published] == [1, 2]


# ---------------------------------------------------------------------------
# DE_INV_05 — additive schema evolution
# ---------------------------------------------------------------------------
def test_inv_schema_additive_confirms() -> None:
    reg = SchemaRegistry()
    reg.register(SchemaDescriptor("account.opened", 1, frozenset({"currency"})))
    # Additive evolution: superset is accepted.
    reg.register(
        SchemaDescriptor("account.opened", 2, frozenset({"currency", "owner"})),
    )
    # Event matching v2 schema validates.
    evt = make_event(
        schema_version=2,
        payload={"currency": "USD", "owner": "alice"},
    )
    reg.validate_event(evt)


def test_inv_schema_additive_prevents() -> None:
    reg = SchemaRegistry()
    reg.register(SchemaDescriptor("order.placed", 1, frozenset({"sku", "qty"})))
    # Removing `qty` is forbidden.
    with pytest.raises(SchemaRegistryError):
        reg.register(SchemaDescriptor("order.placed", 2, frozenset({"sku"})))
    # Renaming is equivalent to removal — also forbidden.
    with pytest.raises(SchemaRegistryError):
        reg.register(
            SchemaDescriptor("order.placed", 2, frozenset({"sku", "quantity"})),
        )
    # Non-monotonic schema_version is forbidden.
    with pytest.raises(SchemaRegistryError):
        reg.register(SchemaDescriptor("order.placed", 3, frozenset({"sku", "qty"})))


def test_inv_schema_additive_under_failure() -> None:
    reg = SchemaRegistry()
    reg.register(SchemaDescriptor("invoice.issued", 1, frozenset({"total"})))
    # Publishing an event missing required fields MUST be rejected.
    evt = make_event(event_type="invoice.issued", schema_version=1, payload={"note": "x"})
    with pytest.raises(SchemaRegistryError):
        reg.validate_event(evt)
    # Publishing an UNREGISTERED (event_type, schema_version) is rejected.
    with pytest.raises(SchemaRegistryError):
        reg.validate_event(make_event(event_type="invoice.issued", schema_version=9))
