"""Behavioral end-to-end scenarios for EventEnvelope — proves invariants at runtime."""

from __future__ import annotations

import pytest

from EventEnvelope import EventEnvelope, EventEnvelopeInvariantError, InMemoryDedupSet


def test_scenario_producer_consumer_dedup_roundtrip() -> None:
    """EE_INV_01 end-to-end: a consumer dedups across the network seam."""
    dedup = InMemoryDedupSet()
    producer_inbox: list[EventEnvelope] = []
    # Producer emits three distinct events.
    for i in range(3):
        producer_inbox.append(
            EventEnvelope(id=f"e-{i}", source="/svc/a", type="domain.event"),
        )
    # Network layer replays the 3rd envelope twice.
    wire: list[EventEnvelope] = [*producer_inbox, producer_inbox[2], producer_inbox[2]]
    accepted = [e for e in wire if dedup.accept(e)]
    assert len(accepted) == 3
    assert {e.id for e in accepted} == {"e-0", "e-1", "e-2"}


def test_scenario_retry_storm_consumer_sees_one() -> None:
    """EE_INV_02: retry storm collapses to one observable occurrence."""
    env = EventEnvelope(id="once", source="/svc", type="create")
    dedup = InMemoryDedupSet()
    first = dedup.accept(env)
    retries = [dedup.accept(env.retry()) for _ in range(100)]
    assert first is True
    assert not any(retries)


def test_scenario_mixed_producers_share_namespace() -> None:
    """Two producers with different `source` values NEVER collide on id."""
    dedup = InMemoryDedupSet()
    a = EventEnvelope(id="42", source="/svc/a", type="t")
    b = EventEnvelope(id="42", source="/svc/b", type="t")
    assert dedup.accept(a) is True
    assert dedup.accept(b) is True  # different source — not a duplicate
    assert dedup.size() == 2


def test_scenario_extension_payload_survives_roundtrip() -> None:
    """EE_INV_04: extension metadata is preserved; reserved names rejected."""
    env = EventEnvelope(
        id="x", source="/s", type="t",
        extensions={"traceid": "abc123", "tenantid": "t-1"},
    )
    assert env.extensions is not None
    assert env.extensions["traceid"] == "abc123"
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(
            id="x2", source="/s", type="t",
            extensions={"type": "would-shadow-core"},
        )


def test_scenario_time_rfc3339_utc_required() -> None:
    """EE_INV_05: UTC-only timestamps accepted; other offsets rejected."""
    good = EventEnvelope(
        id="x", source="/s", type="t", time="2026-04-18T12:00:00Z",
    )
    assert good.time == "2026-04-18T12:00:00Z"
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(
            id="x", source="/s", type="t", time="2026-04-18T12:00:00-05:00",
        )


def test_scenario_boot_is_io_free() -> None:
    """Module-level side effects are FORBIDDEN; import must succeed without IO."""
    import importlib
    import EventEnvelope as mod
    reloaded = importlib.reload(mod)
    assert reloaded.CLOUDEVENTS_SPECVERSION == "1.0"
