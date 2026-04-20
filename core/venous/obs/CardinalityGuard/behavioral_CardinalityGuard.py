"""Behavioral scenarios for CardinalityGuard."""

from __future__ import annotations

from CardinalityGuard import InMemoryCardinalityGuard


def test_scenario_http_route_pass_through() -> None:
    g = InMemoryCardinalityGuard()
    r = g.admit("http.server.duration", {
        "http.route": "/checkout",
        "http.response.status_code": "200",
    })
    assert r["http.route"] == "/checkout"


def test_scenario_user_id_collapsed() -> None:
    g = InMemoryCardinalityGuard()
    r = g.admit("metric", {"user.id": "u-123", "route": "/"})
    assert r["user.id"] == "overflow"
    assert r["route"] == "/"


def test_scenario_many_routes_overflow() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=10)
    for i in range(10):
        g.admit("m", {"route": f"/r{i}"})
    r = g.admit("m", {"route": "/new"})
    assert r == {"overflow": "overflow"}
    assert g.stats("m")["overflow_events"] == 1


def test_scenario_per_key_limit_collapses_one_key() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=10_000, per_key_limit=2)
    for i in range(3):
        g.admit("m", {"tag": f"t{i}", "route": "/"})
    r = g.admit("m", {"tag": "t4", "route": "/"})
    assert r["tag"] == "overflow"
    assert r["route"] == "/"


def test_scenario_configure_frozen_after_first_admit() -> None:
    g = InMemoryCardinalityGuard()
    g.admit("m", {"k": "v"})
    import pytest
    with pytest.raises(Exception):
        g.configure(per_metric_limit=5, per_key_limit=1)


def test_scenario_stats_track_series_growth() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=5)
    for i in range(5):
        g.admit("m", {"k": f"v{i}"})
    assert g.stats("m")["series"] == 5
