"""Unit tests for DeprecationEntry (DE_INV_01..05).

Preserves the canonical `test_inv_sunset_header_*` function names so the
per-primitive invariant-to-test mapping in ``invariant_bindings.json``
continues to resolve.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from DeprecationEntry import DeprecationEntry


def _make(
    path: str = "/api/v1/old",
    method: str = "get",
    days_from_today: int = 90,
    replacement: str = "/api/v2/new",
    **kwargs: object,
) -> DeprecationEntry:
    sunset = (date.today() + timedelta(days=days_from_today)).isoformat()
    return DeprecationEntry(
        path=path, method=method, sunset=sunset,
        replacement=replacement, **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# DE_INV_01 / DE_INV_03 — sunset parse + sunset_header round-trip
# ---------------------------------------------------------------------------
def test_inv_sunset_header_confirms() -> None:
    """Valid ISO sunset parses AND sunset_header round-trips."""
    entry = _make(days_from_today=45)
    assert entry.sunset_date == date.today() + timedelta(days=45)
    assert entry.sunset_header == entry.sunset_date.isoformat()
    assert date.fromisoformat(entry.sunset_header) == entry.sunset_date


# ---------------------------------------------------------------------------
# DE_INV_02 — method normalisation + reject invalid sunset
# ---------------------------------------------------------------------------
def test_inv_sunset_header_prevents() -> None:
    """Invalid ISO date raises; method is upper-cased on ingestion."""
    with pytest.raises(ValueError):
        DeprecationEntry(
            path="/x", method="get", sunset="not-a-date", replacement="/y",
        )
    for raw, expected in [("get", "GET"), ("Post", "POST"), ("DELETE", "DELETE")]:
        assert _make(method=raw).method == expected


# ---------------------------------------------------------------------------
# DE_INV_04 — warn window monotone
# ---------------------------------------------------------------------------
def test_inv_sunset_header_under_failure() -> None:
    """Warn boundary behaviour — inside window warns, outside doesn't, past
    sunset always warns, and the window is per-entry configurable."""
    inside = _make(days_from_today=10, warn_days_before_sunset=30)
    outside = _make(days_from_today=60, warn_days_before_sunset=30)
    past = _make(days_from_today=-5, warn_days_before_sunset=30)
    assert inside.should_warn is True
    assert outside.should_warn is False
    assert past.should_warn is True
    assert past.days_until_sunset == -5

    # Same remaining days, different window → different verdict.
    wide = _make(days_from_today=50, warn_days_before_sunset=60)
    narrow = _make(days_from_today=50, warn_days_before_sunset=10)
    assert wide.should_warn is True
    assert narrow.should_warn is False


# ---------------------------------------------------------------------------
# DE_INV_05 — to_dict JSON-safe + complete
# ---------------------------------------------------------------------------
def test_to_dict_is_json_safe_and_complete() -> None:
    entry = _make(
        path="/api/v1/users", method="POST", days_from_today=90,
        replacement="/api/v2/users", description="Use /api/v2/users",
        warn_days_before_sunset=45,
    )
    payload = entry.to_dict()
    assert set(payload.keys()) == {
        "path", "method", "sunset", "replacement", "description",
        "warn_days_before_sunset", "days_until_sunset", "warn",
    }, "to_dict must carry every public field (DE_INV_05)"
    # The serialized warn window must round-trip — it's a public
    # constructor kwarg, so consumers reconstructing the entry from
    # its dict have to get back the same warning behaviour they
    # configured.
    assert payload["warn_days_before_sunset"] == 45
    json.dumps(payload)  # raises if any value isn't JSON-safe


def test_slots_prevent_accidental_state() -> None:
    entry = _make()
    with pytest.raises(AttributeError):
        entry.extra = "no"  # type: ignore[attr-defined]
