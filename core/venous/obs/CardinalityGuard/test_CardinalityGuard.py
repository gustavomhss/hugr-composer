"""Unit tests for CardinalityGuard."""

from __future__ import annotations

import pytest
from CardinalityGuard import (
    DEFAULT_DENY_KEYS,
    CardinalityInvariantError,
    InMemoryCardinalityGuard,
)


# CARD_INV_01 — per-metric overflow
def test_inv_per_metric_overflow_confirms() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=3, per_key_limit=100)
    for i in range(3):
        g.admit("m", {"route": f"/r{i}"})
    # The 4th distinct combination triggers overflow.
    result = g.admit("m", {"route": "/r4"})
    assert result == {"overflow": "overflow"}


def test_inv_per_metric_overflow_prevents() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=5)
    # Within limit, originals pass through.
    for i in range(5):
        r = g.admit("m", {"route": f"/x{i}"})
        assert "overflow" not in r.values() or r["route"] != "overflow"


def test_inv_per_metric_overflow_under_failure() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=2)
    for i in range(2):
        g.admit("m", {"k": f"v{i}"})
    # Multiple overflows all collapse to the same overflow series.
    for _ in range(5):
        assert g.admit("m", {"k": "vOther"}) == {"overflow": "overflow"}


# CARD_INV_02 — per-key limit
def test_inv_per_key_limit_confirms() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=10_000, per_key_limit=3)
    for i in range(3):
        r = g.admit("m", {"tag": f"t{i}"})
        assert r["tag"] == f"t{i}"
    # The 4th distinct value for same key gets collapsed.
    r = g.admit("m", {"tag": "t4"})
    assert r["tag"] == "overflow"


def test_inv_per_key_limit_prevents() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=10_000, per_key_limit=2)
    g.admit("m", {"tag": "a"})
    g.admit("m", {"tag": "b"})
    # Repeating an existing value does not count against the limit.
    r = g.admit("m", {"tag": "a"})
    assert r["tag"] == "a"


def test_inv_per_key_limit_under_failure() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=10_000, per_key_limit=1)
    g.admit("m", {"tag": "first"})
    for _ in range(10):
        r = g.admit("m", {"tag": "new"})
        assert r["tag"] == "overflow"


# CARD_INV_03 — deny-list
def test_inv_deny_list_confirms() -> None:
    g = InMemoryCardinalityGuard()
    r = g.admit("m", {"user.id": "abc", "route": "/"})
    assert r["user.id"] == "overflow"
    assert r["route"] == "/"


def test_inv_deny_list_prevents() -> None:
    g = InMemoryCardinalityGuard()
    r = g.admit("m", {"email": "a@b.com"})
    assert r["email"] == "overflow"
    r = g.admit("m", {"any": "user@domain.io"})
    assert r["any"] == "overflow"


def test_inv_deny_list_under_failure() -> None:
    g = InMemoryCardinalityGuard()
    for denied in DEFAULT_DENY_KEYS:
        r = g.admit("m", {denied: "anything"})
        assert r[denied] == "overflow"


# CARD_INV_04 — deterministic admit
def test_inv_deterministic_admit_confirms() -> None:
    g = InMemoryCardinalityGuard()
    first = g.admit("m", {"route": "/a"})
    for _ in range(10):
        assert g.admit("m", {"route": "/a"}) == first


def test_inv_deterministic_admit_prevents() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=1)
    g.admit("m", {"k": "first"})
    # Once at limit, ANY new combination → overflow, stable result.
    for _ in range(5):
        assert g.admit("m", {"k": "other"}) == {"overflow": "overflow"}


def test_inv_deterministic_admit_under_failure() -> None:
    g = InMemoryCardinalityGuard()
    # Different metrics have independent cardinality budgets.
    g.admit("m1", {"route": "/a"})
    assert g.admit("m2", {"route": "/a"})["route"] == "/a"


# CARD_INV_05 — no in-place mutation
def test_inv_no_mutation_confirms() -> None:
    g = InMemoryCardinalityGuard()
    input_map: dict[str, str] = {"route": "/"}
    result = g.admit("m", input_map)
    assert result is not input_map
    assert input_map == {"route": "/"}


def test_inv_no_mutation_prevents() -> None:
    g = InMemoryCardinalityGuard()
    input_map: dict[str, str] = {"email": "leak@x"}
    result = g.admit("m", input_map)
    assert input_map == {"email": "leak@x"}
    assert result["email"] == "overflow"


def test_inv_no_mutation_under_failure() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=1)
    input_map: dict[str, str] = {"k": "v"}
    g.admit("m", input_map)
    result = g.admit("m", {"k": "v2"})
    assert input_map == {"k": "v"}
    assert result == {"overflow": "overflow"}


# CARD_INV_06 — overflow counter observable
def test_inv_overflow_counter_confirms() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=1)
    g.admit("m", {"k": "v1"})
    g.admit("m", {"k": "v2"})
    g.admit("m", {"k": "v3"})
    stats = g.stats("m")
    assert stats["overflow_events"] == 2


def test_inv_overflow_counter_prevents() -> None:
    g = InMemoryCardinalityGuard()
    g.admit("m", {"k": "v1"})
    stats = g.stats("m")
    assert stats["overflow_events"] == 0


def test_inv_overflow_counter_under_failure() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=1)
    for i in range(5):
        g.admit("m", {"k": f"v{i}"})
    assert g.stats("m")["overflow_events"] >= 4


# CARD_INV_07 — configure locked after first admit
def test_inv_configure_locked_confirms() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=100)
    g.configure(per_metric_limit=50, per_key_limit=5)
    g.admit("m", {"k": "v"})
    with pytest.raises(CardinalityInvariantError):
        g.configure(per_metric_limit=200, per_key_limit=10)


def test_inv_configure_locked_prevents() -> None:
    g = InMemoryCardinalityGuard()
    # Configure before first admit → ok.
    g.configure(per_metric_limit=10, per_key_limit=2)


def test_inv_configure_locked_under_failure() -> None:
    g = InMemoryCardinalityGuard()
    g.admit("m", {"k": "v"})
    for _ in range(5):
        with pytest.raises(CardinalityInvariantError):
            g.configure(per_metric_limit=5, per_key_limit=1)
