"""Metamorphic + differential for CardinalityGuard."""

from __future__ import annotations

from CardinalityGuard import InMemoryCardinalityGuard


def test_metamorphic_idempotent_admit_under_limit() -> None:
    g = InMemoryCardinalityGuard()
    for _ in range(5):
        r = g.admit("m", {"route": "/a"})
        assert r == {"route": "/a"}


def test_metamorphic_isolation_across_metrics() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=1)
    g.admit("m1", {"k": "v"})
    r = g.admit("m2", {"k": "v"})
    assert r["k"] == "v"


def test_metamorphic_repeat_value_no_cardinality_growth() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=10_000, per_key_limit=1)
    g.admit("m", {"k": "same"})
    for _ in range(10):
        assert g.admit("m", {"k": "same"})["k"] == "same"


def test_differential_deny_list_vs_normal() -> None:
    g = InMemoryCardinalityGuard()
    r = g.admit("m", {"user.id": "x", "safe": "y"})
    assert r["user.id"] == "overflow"
    assert r["safe"] == "y"


def test_metamorphic_overflow_counter_monotone() -> None:
    g = InMemoryCardinalityGuard(per_metric_limit=1)
    g.admit("m", {"k": "a"})
    prev = g.stats("m")["overflow_events"]
    for i in range(5):
        g.admit("m", {"k": f"x{i}"})
        current = g.stats("m")["overflow_events"]
        assert current > prev
        prev = current


def test_metamorphic_new_mapping_is_independent() -> None:
    g = InMemoryCardinalityGuard()
    input_map: dict[str, str] = {"route": "/a"}
    result = g.admit("m", input_map)
    dict(result)["mutant"] = "injected"  # type: ignore[index]
    assert "mutant" not in input_map
