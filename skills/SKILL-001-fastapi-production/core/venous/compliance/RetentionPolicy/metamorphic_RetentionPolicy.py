"""Metamorphic + differential tests for RetentionPolicy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from RetentionPolicy import InMemoryRetentionEnforcer, RetentionPolicy


def _policy(**o: object) -> RetentionPolicy:
    base: dict[str, object] = {
        "data_class": "dc", "max_age": timedelta(days=1),
        "legal_basis": "internal", "deletion_mode": "hard",
    }
    base.update(o)
    return RetentionPolicy(**base)  # type: ignore[arg-type]


def test_metamorphic_sweep_twice_yields_same_state() -> None:
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(_policy())
    for i in range(5):
        enf.enforce_on_write("dc", f"r{i}")
    clock[0] = datetime(2026, 1, 5, tzinfo=timezone.utc)
    first = enf.sweep()
    size_after_first = enf.size
    second = enf.sweep()
    assert second == 0
    assert enf.size == size_after_first
    assert first == 5


def test_metamorphic_bind_is_last_writer_wins() -> None:
    enf = InMemoryRetentionEnforcer()
    enf.bind(_policy(max_age=timedelta(days=1)))
    enf.bind(_policy(max_age=timedelta(days=7)))  # rebind
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf2 = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf2.bind(_policy(max_age=timedelta(days=7)))
    enf2.enforce_on_write("dc", "r")
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    # 2 days < 7 day max_age, so still there.
    assert enf2.sweep() == 0


def test_metamorphic_frozen_policy_is_hashable() -> None:
    p1 = _policy()
    p2 = _policy()
    assert p1 == p2
    assert {p1}  # hashable because frozen


def test_differential_multiple_data_classes() -> None:
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(_policy(data_class="a", max_age=timedelta(days=1)))
    enf.bind(_policy(data_class="b", max_age=timedelta(days=30)))
    enf.enforce_on_write("a", "a1")
    enf.enforce_on_write("b", "b1")
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert enf.sweep() == 1  # only 'a' has aged out


def test_metamorphic_adding_policy_does_not_affect_other_class_records() -> None:
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(_policy(data_class="a", max_age=timedelta(days=1)))
    enf.enforce_on_write("a", "a1")
    # Binding a new class b does not evict records from a.
    enf.bind(_policy(data_class="b", max_age=timedelta(days=365)))
    assert enf.size == 1
