"""Metamorphic + differential tests for ConsentLedger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ConsentLedger import InMemoryConsentLedger


UTC = timezone.utc


def test_metamorphic_latest_wins() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v1", datetime(2026, 1, 1, tzinfo=UTC))
    led.revoke("s-1", "p", datetime(2026, 2, 1, tzinfo=UTC))
    led.grant("s-1", "p", "v2", datetime(2026, 3, 1, tzinfo=UTC))
    # Most-recent action is grant → granted at later time.
    assert led.is_granted("s-1", "p", datetime(2026, 4, 1, tzinfo=UTC)) is True


def test_metamorphic_history_monotonic_grow() -> None:
    led = InMemoryConsentLedger()
    sizes: list[int] = []
    for d in range(1, 6):
        led.grant("s-1", f"p{d}", "v", datetime(2026, 1, d, tzinfo=UTC))
        sizes.append(len(led.history("s-1")))
    assert sizes == [1, 2, 3, 4, 5]


def test_differential_two_subjects_isolated() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v", datetime(2026, 1, 1, tzinfo=UTC))
    # s-2 history remains empty.
    assert led.history("s-2") == []
    assert led.is_granted("s-2", "p") is False


def test_metamorphic_idempotent_revoke_sequence() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v", datetime(2026, 1, 1, tzinfo=UTC))
    led.revoke("s-1", "p", datetime(2026, 2, 1, tzinfo=UTC))
    led.revoke("s-1", "p", datetime(2026, 2, 2, tzinfo=UTC))
    # Both revokes preserved (append-only).
    assert len(led.history("s-1")) == 3
    assert led.is_granted("s-1", "p", datetime(2026, 3, 1, tzinfo=UTC)) is False


def test_metamorphic_future_time_ignores_future_rows() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v", datetime(2026, 6, 1, tzinfo=UTC))
    # Query at 2026-01-01 → row is in the future, not yet effective.
    assert led.is_granted("s-1", "p", datetime(2026, 1, 1, tzinfo=UTC)) is False


def test_differential_purpose_comma_rejected_everywhere() -> None:
    led = InMemoryConsentLedger()
    import pytest

    from ConsentLedger import ConsentLedgerError
    with pytest.raises(ConsentLedgerError):
        led.grant("s-1", "a,b", "v", datetime(2026, 1, 1, tzinfo=UTC))
