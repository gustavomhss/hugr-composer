"""Chaos tests for ConsentLedger."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from ConsentLedger import ConsentLedgerError, InMemoryConsentLedger


UTC = timezone.utc


def test_chaos_concurrent_grants_all_recorded() -> None:
    led = InMemoryConsentLedger()

    def worker(i: int) -> None:
        led.grant(f"s-{i}", "p", "v", datetime(2026, 1, 1, tzinfo=UTC))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert led.size == 50


def test_chaos_naive_timestamp_rejected() -> None:
    led = InMemoryConsentLedger()
    with pytest.raises(ConsentLedgerError):
        led.grant("s", "p", "v", datetime(2026, 1, 1))


def test_chaos_unicode_homoglyph_subjects_distinct() -> None:
    led = InMemoryConsentLedger()
    t = datetime(2026, 1, 1, tzinfo=UTC)
    led.grant("admin", "p", "v", t)  # Latin a
    led.grant("\u0430dmin", "p", "v", t)  # Cyrillic a
    # Two distinct subjects, not conflated.
    assert len(led.history("admin")) == 1
    assert len(led.history("\u0430dmin")) == 1


def test_chaos_whitespace_purpose_rejected() -> None:
    led = InMemoryConsentLedger()
    for bad in ("", "   ", "\t", "\n"):
        with pytest.raises(ConsentLedgerError):
            led.grant("s", bad, "v", datetime(2026, 1, 1, tzinfo=UTC))


def test_chaos_many_revocations_preserved() -> None:
    led = InMemoryConsentLedger()
    for i in range(20):
        led.revoke("s", "p", datetime(2026, 1, i + 1, tzinfo=UTC))
    assert len(led.history("s")) == 20
    assert led.is_granted("s", "p", datetime(2026, 2, 1, tzinfo=UTC)) is False


def test_chaos_blanket_grant_attempt_rejected() -> None:
    led = InMemoryConsentLedger()
    with pytest.raises(ConsentLedgerError):
        led.grant("s", "marketing_email,analytics", "v", datetime(2026, 1, 1, tzinfo=UTC))
