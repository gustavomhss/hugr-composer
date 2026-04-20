"""Unit tests for ConsentLedger — 3 tests per invariant."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ConsentLedger import ConsentLedgerError, InMemoryConsentLedger


UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
T2 = datetime(2026, 3, 1, tzinfo=UTC)


# CL_INV_01 — (subject, purpose) keyed; no blanket grants.
def test_inv_keyed_confirms() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "marketing_email", "v3", T0)
    assert led.is_granted("s-1", "marketing_email", T1) is True
    # A different purpose is NOT auto-granted.
    assert led.is_granted("s-1", "analytics_profiling", T1) is False


def test_inv_keyed_prevents() -> None:
    led = InMemoryConsentLedger()
    with pytest.raises(ConsentLedgerError):
        led.grant("", "marketing_email", "v3", T0)
    with pytest.raises(ConsentLedgerError):
        led.grant("s-1", "", "v3", T0)
    with pytest.raises(ConsentLedgerError):
        led.grant("s-1", "marketing_email,analytics", "v3", T0)


def test_inv_keyed_under_failure() -> None:
    led = InMemoryConsentLedger()
    # Missing both keys — multiple invariant violations.
    with pytest.raises(ConsentLedgerError):
        led.grant("  ", "  ", "v3", T0)


# CL_INV_02 — notice_version required.
def test_inv_notice_version_confirms() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "marketing_email", "notice-v3.2", T0)
    hist = led.history("s-1")
    assert hist[0]["notice_version"] == "notice-v3.2"


def test_inv_notice_version_prevents() -> None:
    led = InMemoryConsentLedger()
    with pytest.raises(ConsentLedgerError):
        led.grant("s-1", "p", "", T0)
    with pytest.raises(ConsentLedgerError):
        led.grant("s-1", "p", "   ", T0)


def test_inv_notice_version_under_failure() -> None:
    led = InMemoryConsentLedger()
    with pytest.raises(ConsentLedgerError):
        led.grant("s-1", "p", None, T0)  # type: ignore[arg-type]


# CL_INV_03 — revocation immediate.
def test_inv_revoke_immediate_confirms() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v1", T0)
    assert led.is_granted("s-1", "p", T1) is True
    led.revoke("s-1", "p", T2)
    assert led.is_granted("s-1", "p", T2 + timedelta(seconds=1)) is False


def test_inv_revoke_immediate_prevents() -> None:
    led = InMemoryConsentLedger()
    with pytest.raises(ConsentLedgerError):
        led.revoke("", "p", T0)
    with pytest.raises(ConsentLedgerError):
        led.revoke("s-1", "", T0)


def test_inv_revoke_immediate_under_failure() -> None:
    led = InMemoryConsentLedger()
    # Revoking before any grant is idempotent and leaves is_granted False.
    led.revoke("s-1", "p", T0)
    assert led.is_granted("s-1", "p", T1) is False


# CL_INV_04 — history append-only.
def test_inv_history_append_only_confirms() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v1", T0)
    led.revoke("s-1", "p", T1)
    led.grant("s-1", "p", "v2", T2)
    hist = led.history("s-1")
    assert [h["kind"] for h in hist] == ["grant", "revoke", "grant"]


def test_inv_history_append_only_prevents() -> None:
    led = InMemoryConsentLedger()
    # No mutating surface exposed.
    for attr in ("delete", "update", "remove", "pop", "set_history"):
        assert not hasattr(led, attr)


def test_inv_history_append_only_under_failure() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v1", T0)
    led.revoke("s-1", "p", T1)
    # Retrieving history twice yields identical sequences (append-only).
    h1 = led.history("s-1")
    h2 = led.history("s-1")
    assert h1 == h2


# CL_INV_05 — temporal evaluation.
def test_inv_temporal_confirms() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v1", T0)
    led.revoke("s-1", "p", T2)
    # At T1 (between grant and revoke) → granted.
    assert led.is_granted("s-1", "p", T1) is True
    # At T2 (the instant of revoke) → current latest row is the revoke.
    assert led.is_granted("s-1", "p", T2) is False
    # Before T0 → no record exists.
    assert led.is_granted("s-1", "p", T0 - timedelta(days=1)) is False


def test_inv_temporal_prevents() -> None:
    led = InMemoryConsentLedger()
    with pytest.raises(ConsentLedgerError):
        led.is_granted("s-1", "p", datetime(2026, 1, 1))  # naive


def test_inv_temporal_under_failure() -> None:
    led = InMemoryConsentLedger()
    # No consent at all → not granted at any time.
    assert led.is_granted("s-unknown", "p") is False
