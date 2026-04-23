"""Unit tests for DeprecationRegistry (DR_INV_01..04)."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pytest

from DeprecationRegistry import DeprecationRegistry


def _iso(days_ahead: int) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


# ---------------------------------------------------------------------------
# DR_INV_01 — key uniqueness (method+path composite)
# ---------------------------------------------------------------------------
def test_inv_register_confirms() -> None:
    """Register then get returns the same entry; separate keys coexist."""
    reg = DeprecationRegistry()
    a = reg.register("/api/v1/a", "GET", _iso(60), "/api/v2/a")
    b = reg.register("/api/v1/b", "POST", _iso(90), "/api/v2/b")
    assert reg.get("/api/v1/a", "GET") is a
    assert reg.get("/api/v1/b", "POST") is b
    assert len(reg.list_all()) == 2


def test_register_same_key_replaces_entry() -> None:
    """DR_INV_01: re-registering same (method, path) replaces; no dupes."""
    reg = DeprecationRegistry()
    first = reg.register("/p", "GET", _iso(60), "/p2", description="first")
    second = reg.register("/p", "GET", _iso(30), "/p3", description="second")
    assert reg.get("/p", "GET") is second
    assert second is not first
    assert len(reg.list_all()) == 1


# ---------------------------------------------------------------------------
# DR_INV_02 — method case-insensitivity
# ---------------------------------------------------------------------------
def test_inv_register_prevents() -> None:
    """get() matches regardless of method case (DR_INV_02)."""
    reg = DeprecationRegistry()
    reg.register("/api/x", "get", _iso(60), "/api/v2/x")
    assert reg.get("/api/x", "get") is not None
    assert reg.get("/api/x", "GET") is not None
    assert reg.get("/api/x", "Get") is not None
    assert reg.get("/api/x", "POST") is None  # different method key


# ---------------------------------------------------------------------------
# DR_INV_03 — warn-on-register
# ---------------------------------------------------------------------------
def test_inv_register_under_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Inside warn-window registrations emit logger.warning.

    Outside the window: no warning. Default warn window is 30 days;
    a sunset 10 days out is inside → warn emitted.
    """
    reg = DeprecationRegistry()
    caplog.set_level(logging.WARNING)

    # Inside window — should warn
    reg.register("/urgent", "GET", _iso(10), "/new-urgent")
    messages = [r.message for r in caplog.records]
    assert any("GET /urgent" in m for m in messages), messages

    # Outside window — no new warning for this endpoint
    caplog.clear()
    reg.register("/calm", "GET", _iso(180), "/new-calm")
    assert not any("GET /calm" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# DR_INV_04 — list_all sort order
# ---------------------------------------------------------------------------
def test_list_all_sorted_by_sunset_ascending() -> None:
    reg = DeprecationRegistry()
    reg.register("/late", "GET", _iso(120), "/new-late")
    reg.register("/urgent", "GET", _iso(7), "/new-urgent")
    reg.register("/mid", "GET", _iso(60), "/new-mid")
    result = reg.list_all()
    assert [r["path"] for r in result] == ["/urgent", "/mid", "/late"]


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
def test_slots_prevent_accidental_state() -> None:
    reg = DeprecationRegistry()
    with pytest.raises(AttributeError):
        reg.extra = "no"  # type: ignore[attr-defined]


def test_get_unknown_returns_none() -> None:
    reg = DeprecationRegistry()
    assert reg.get("/nothing", "GET") is None
