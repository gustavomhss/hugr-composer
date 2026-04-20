"""Metamorphic + differential tests for EventEnvelope.

Algebraic laws:
- dedup_key is deterministic and order-independent of field population.
- retry() is idempotent on dedup_key (EE_INV_02).
- specversion is immutable under construction (EE_INV_03).
- extension validation is monotonic: any invalid entry rejects the whole bag.
"""

from __future__ import annotations

import pytest

from EventEnvelope import (
    EventEnvelope,
    EventEnvelopeInvariantError,
    InMemoryDedupSet,
)


def test_metamorphic_dedup_key_stable_across_equal_envelopes() -> None:
    a = EventEnvelope(id="x", source="/s", type="t")
    b = EventEnvelope(id="x", source="/s", type="t", subject="optional")
    # Different subjects, same dedup key: source and id are the identity.
    assert a.dedup_key() == b.dedup_key() == ("/s", "x")


def test_metamorphic_retry_is_dedup_idempotent() -> None:
    env = EventEnvelope(id="retry-me", source="/s", type="t")
    keys = [env.retry().dedup_key() for _ in range(20)]
    assert all(k == env.dedup_key() for k in keys)


def test_metamorphic_consumer_accept_then_reject() -> None:
    env = EventEnvelope(id="k", source="/s", type="t")
    dedup = InMemoryDedupSet()
    observations = [dedup.accept(env) for _ in range(10)]
    # Exactly one True followed by nine False — dedup is deterministic.
    assert observations == [True] + [False] * 9


def test_differential_different_source_same_id_are_distinct() -> None:
    dedup = InMemoryDedupSet()
    for source in ("/a", "/b", "/c", "/d"):
        env = EventEnvelope(id="shared", source=source, type="t")
        assert dedup.accept(env) is True
    assert dedup.size() == 4


def test_metamorphic_specversion_cannot_be_mutated() -> None:
    env = EventEnvelope(id="x", source="/s", type="t")
    # Frozen dataclass — assignment raises.
    with pytest.raises(Exception):  # noqa: BLE001,PT011 — FrozenInstanceError is a dataclasses internal (EE_INV_03)
        env.specversion = "2.0"  # type: ignore[misc]  # intended negative test (EE_INV_03)
    assert env.specversion == "1.0"


def test_metamorphic_extension_validation_monotonic() -> None:
    # If N good extensions + 1 bad are submitted, the entire construction MUST fail.
    good: dict[str, str] = {f"ext{i}": "v" for i in range(15)}
    bad = {**good, "Bad-One": "v"}
    with pytest.raises(EventEnvelopeInvariantError):
        EventEnvelope(id="x", source="/s", type="t", extensions=bad)


def test_differential_type_vs_subject_dont_affect_dedup() -> None:
    a = EventEnvelope(id="x", source="/s", type="typeA", subject="sA")
    b = EventEnvelope(id="x", source="/s", type="typeB", subject="sB")
    assert a.dedup_key() == b.dedup_key()
