"""Unit tests for EventEnvelope — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import pytest
from EventEnvelope import (
    EventEnvelope,
    EventEnvelopeInvariantError,
    InMemoryDedupSet,
    validate_extension_name,
    validate_extensions,
    validate_specversion,
    validate_time,
)


# ---------------------------------------------------------------------------
# EE_INV_01 — (source, id) uniqueness for dedup
# ---------------------------------------------------------------------------
def test_inv_dedup_identity_confirms() -> None:
    dedup = InMemoryDedupSet()
    env = EventEnvelope(id="e-1", source="/svc/orders", type="order.created")
    assert dedup.accept(env) is True
    # Same key is rejected (second sight) — proves stable identity.
    again = EventEnvelope(id="e-1", source="/svc/orders", type="order.created")
    assert dedup.accept(again) is False
    assert env.dedup_key() == again.dedup_key() == ("/svc/orders", "e-1")


def test_inv_dedup_identity_prevents() -> None:
    # Empty / whitespace / null-byte inputs MUST be rejected on construction.
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(id="", source="/svc", type="t")
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(id="x", source="", type="t")
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(id="x", source="/svc", type="")
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(id="\x00bad", source="/svc", type="t")
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(id="x", source="/svc", type="t", subject="")


def test_inv_dedup_identity_under_failure() -> None:
    # Under heavy re-send / mixed keys, InMemoryDedupSet keeps the invariant.
    dedup = InMemoryDedupSet()
    for i in range(100):
        env = EventEnvelope(id=f"e-{i}", source="/svc", type="order.created")
        assert dedup.accept(env) is True
    # Re-send the same 100 envelopes — none should be accepted again.
    for i in range(100):
        env = EventEnvelope(id=f"e-{i}", source="/svc", type="order.created")
        assert dedup.accept(env) is False
    assert dedup.size() == 100


# ---------------------------------------------------------------------------
# EE_INV_02 — retry reuses id (dedup identity preserved)
# ---------------------------------------------------------------------------
def test_inv_retry_reuses_id_confirms() -> None:
    original = EventEnvelope(
        id="evt-42", source="/svc/orders", type="order.created",
    )
    retried = original.retry()
    assert retried.dedup_key() == original.dedup_key()
    assert retried.id == original.id
    assert retried.source == original.source


def test_inv_retry_reuses_id_prevents() -> None:
    # retry() MUST NOT mint a new id (which would break consumer dedup).
    original = EventEnvelope(
        id="evt-stable", source="/svc", type="x",
    )
    dedup = InMemoryDedupSet()
    assert dedup.accept(original) is True
    for _ in range(5):
        assert dedup.accept(original.retry()) is False


def test_inv_retry_reuses_id_under_failure() -> None:
    # Even after many retries under a scenario that simulates transient failure,
    # consumer observes exactly one distinct occurrence.
    original = EventEnvelope(
        id="evt-once", source="/svc", type="transient",
    )
    dedup = InMemoryDedupSet()
    observations: list[bool] = []
    # First attempt succeeds.
    observations.append(dedup.accept(original))
    # 50 retries; each should be rejected as a duplicate.
    for _ in range(50):
        observations.append(dedup.accept(original.retry()))
    assert observations[0] is True
    assert all(o is False for o in observations[1:])
    assert dedup.size() == 1


# ---------------------------------------------------------------------------
# EE_INV_03 — specversion MUST equal '1.0'
# ---------------------------------------------------------------------------
def test_inv_specversion_confirms() -> None:
    env = EventEnvelope(id="x", source="/s", type="t")
    assert env.specversion == "1.0"
    # Explicit '1.0' is accepted.
    env2 = EventEnvelope(id="x", source="/s", type="t", specversion="1.0")
    assert env2.specversion == "1.0"
    assert validate_specversion("1.0") == "1.0"


def test_inv_specversion_prevents() -> None:
    for bad in ("0.3", "2.0", "1", "1.0.0", "", "v1.0"):
        with pytest.raises(EventEnvelopeInvariantError):
            EventEnvelope(id="x", source="/s", type="t", specversion=bad)
    with pytest.raises(EventEnvelopeInvariantError):
        validate_specversion(None)
    with pytest.raises(EventEnvelopeInvariantError):
        validate_specversion(1.0)


def test_inv_specversion_under_failure() -> None:
    # Under a flood of well-formed construction attempts, specversion locks to 1.0.
    for _ in range(200):
        env = EventEnvelope(id="x", source="/s", type="t")
        assert env.specversion == "1.0"


# ---------------------------------------------------------------------------
# EE_INV_04 — extension name rules
# ---------------------------------------------------------------------------
def test_inv_extension_name_confirms() -> None:
    # Valid extension names: lowercase letters and digits, 1..20 chars.
    for name in ("trace", "tenantid", "v2", "a"):
        assert validate_extension_name(name) == name
    env = EventEnvelope(
        id="x", source="/s", type="t",
        extensions={"trace": "abc", "tenantid": "t-1"},
    )
    assert env.extensions is not None
    assert env.extensions["trace"] == "abc"


def test_inv_extension_name_prevents() -> None:
    # Reserved names, uppercase, underscores, dots, too long — all rejected.
    for bad in ("id", "source", "TYPE", "my_ext", "my.ext", "x" * 21,
                "", "ext-dash"):
        with pytest.raises(EventEnvelopeInvariantError):
            validate_extension_name(bad)
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(
            id="x", source="/s", type="t",
            extensions={"id": "collision"},  # collides with core
        )
    with pytest.raises(EventEnvelopeInvariantError):
        # Non-str value
        validate_extensions({"good": 123})  # type: ignore[dict-item]


def test_inv_extension_name_under_failure() -> None:
    # Under a dict with many valid + one invalid, construction MUST fail atomically.
    bad_mix: dict[str, str] = {f"ext{i}": "v" for i in range(10)}
    bad_mix["BAD"] = "v"  # invalid
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(
            id="x", source="/s", type="t", extensions=bad_mix,
        )


# ---------------------------------------------------------------------------
# EE_INV_05 — time MUST be RFC 3339 UTC
# ---------------------------------------------------------------------------
def test_inv_time_format_confirms() -> None:
    for good in (
        "2025-01-02T03:04:05Z",
        "2025-01-02T03:04:05.123Z",
        "2025-01-02T03:04:05+00:00",
        "2025-01-02T03:04:05.123456+00:00",
    ):
        assert validate_time(good) == good
    env = EventEnvelope(
        id="x", source="/s", type="t", time="2025-01-02T03:04:05Z",
    )
    assert env.time == "2025-01-02T03:04:05Z"


def test_inv_time_format_prevents() -> None:
    for bad in (
        "2025-01-02T03:04:05",          # no zone
        "2025-01-02T03:04:05-05:00",    # non-UTC
        "2025-01-02 03:04:05Z",         # space instead of 'T'
        "20250102T030405Z",             # no dashes
        "not-a-date",
        "",
    ):
        with pytest.raises(EventEnvelopeInvariantError):
            validate_time(bad)
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(
            id="x", source="/s", type="t", time="2025-13-40T99:99:99Z",
        )


def test_inv_time_format_under_failure() -> None:
    # None is allowed (optional field); junk mixed with good input still
    # rejects junk eagerly and accepts None silently.
    env = EventEnvelope(id="x", source="/s", type="t", time=None)
    assert env.time is None
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(id="x", source="/s", type="t", time=12345)  # type: ignore[arg-type]
