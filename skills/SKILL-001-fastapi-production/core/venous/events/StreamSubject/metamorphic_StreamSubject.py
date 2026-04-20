"""Metamorphic / differential tests for StreamSubject."""

from __future__ import annotations

from StreamSubject import StreamSubject, SubjectRegistry


def test_metamorphic_exact_match_is_reflexive() -> None:
    for name in ("a", "a.b", "a.b.c.d"):
        s = StreamSubject(name)
        assert s.matches(name)


def test_metamorphic_star_position_is_local() -> None:
    s = StreamSubject("a.b.c")
    # * at each position.
    assert s.matches("*.b.c")
    assert s.matches("a.*.c")
    assert s.matches("a.b.*")


def test_differential_registry_delivery_count_matches_predicate() -> None:
    reg = SubjectRegistry()
    for i in range(5):
        reg.subscribe(f"a.{i}.>", f"c{i}")
    # A subject matches exactly one pattern.
    s = StreamSubject("a.2.x.y")
    assert reg.publish(s) == 1


def test_metamorphic_greedy_dominates_exact() -> None:
    s = StreamSubject("a.b.c.d")
    assert s.matches("a.>")  # True
    assert s.matches("a.b.>")  # True
    assert s.matches("a.b.c.>")  # True


def test_metamorphic_star_then_greedy_composed() -> None:
    s = StreamSubject("a.X.c.d.e")
    assert s.matches("a.*.c.>")


def test_differential_publish_is_monotonic_in_subs() -> None:
    reg = SubjectRegistry()
    s = StreamSubject("a.b")
    assert reg.publish(s) == 0
    reg.subscribe("a.>", "c1")
    assert reg.publish(s) == 1
    reg.subscribe("a.b", "c2")
    assert reg.publish(s) == 2
