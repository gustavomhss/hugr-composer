"""Unit tests for DeprecationReporter (DP_INV_01..04)."""
from __future__ import annotations

import pytest
from DeprecationReporter import DeprecationReporter


def test_inv_record_confirms() -> None:
    """DP_INV_01 + DP_INV_02: record increments the (METHOD, path) counter."""
    rep = DeprecationReporter()
    rep.record("/api/v1/x", "GET")
    rep.record("/api/v1/x", "get")  # same bucket (case-insensitive)
    rep.record("/api/v1/x", "GET")
    assert rep.get_count("/api/v1/x", "GET") == 3
    assert rep.get_count("/api/v1/x", "Get") == 3

    # Different method = different bucket
    rep.record("/api/v1/x", "POST")
    assert rep.get_count("/api/v1/x", "POST") == 1
    # GET count unchanged
    assert rep.get_count("/api/v1/x", "GET") == 3


def test_inv_record_prevents() -> None:
    """DP_INV_03 + DP_INV_04: usage_report sorted desc; reset clears all."""
    rep = DeprecationReporter()
    for _ in range(5):
        rep.record("/popular", "GET")
    for _ in range(2):
        rep.record("/quiet", "GET")
    for _ in range(10):
        rep.record("/viral", "POST")

    report = rep.usage_report()
    assert [r["endpoint"] for r in report] == [
        "POST /viral", "GET /popular", "GET /quiet",
    ]
    assert [r["call_count"] for r in report] == [10, 5, 2]

    # DP_INV_04 reset
    rep.reset()
    assert rep.usage_report() == []
    assert rep.get_count("/popular", "GET") == 0
    assert rep.get_count("/viral", "POST") == 0


def test_inv_record_under_failure() -> None:
    """Unseen endpoints return 0 — no KeyError / missing-bucket surprise."""
    rep = DeprecationReporter()
    assert rep.get_count("/never", "GET") == 0
    # Reading a missing counter MUST NOT implicitly create one
    # (usage_report should still be empty after the get_count call).
    assert rep.usage_report() == []


def test_slots_prevent_accidental_state() -> None:
    rep = DeprecationReporter()
    with pytest.raises(AttributeError):
        rep.extra = 1  # type: ignore[attr-defined]
