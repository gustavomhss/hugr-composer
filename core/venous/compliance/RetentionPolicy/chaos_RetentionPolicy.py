"""Chaos tests for RetentionPolicy."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from RetentionPolicy import (
    InMemoryRetentionEnforcer,
    RetentionPolicy,
    RetentionPolicyError,
)


def _policy(**o: object) -> RetentionPolicy:
    base: dict[str, object] = {
        "data_class": "dc", "max_age": timedelta(days=1),
        "legal_basis": "internal", "deletion_mode": "hard",
    }
    base.update(o)
    return RetentionPolicy(**base)  # type: ignore[arg-type]


def test_chaos_concurrent_writes_counted() -> None:
    enf = InMemoryRetentionEnforcer()
    enf.bind(_policy())

    def worker(i: int) -> None:
        enf.enforce_on_write("dc", f"r{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Python list.append is threadsafe for CPython; all 50 should land.
    assert enf.size == 50


def test_chaos_unregistered_class_rejected_repeatedly() -> None:
    enf = InMemoryRetentionEnforcer()
    for _ in range(5):
        with pytest.raises(RetentionPolicyError):
            enf.enforce_on_write("nope", "x")


def test_chaos_sweep_with_no_records_returns_zero() -> None:
    enf = InMemoryRetentionEnforcer()
    enf.bind(_policy())
    for _ in range(10):
        assert enf.sweep() == 0


def test_chaos_hold_flips_during_sweep_respected() -> None:
    covered = ["held-1"]

    class _Hold:
        def covers(self, rid: str) -> bool:
            return rid in covered

    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf = InMemoryRetentionEnforcer(hold_check=_Hold(), now=lambda: clock[0])
    enf.bind(_policy(max_age=timedelta(days=1)))
    enf.enforce_on_write("dc", "held-1")
    enf.enforce_on_write("dc", "free-1")
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert enf.sweep() == 1
    # Release the hold; next sweep purges.
    covered.clear()
    assert enf.sweep() == 1
    assert enf.size == 0


def test_chaos_policy_validation_rejects_broken_values() -> None:
    for bad in ("BAD", "", "hard-delete"):
        with pytest.raises(RetentionPolicyError):
            RetentionPolicy(
                data_class="dc", max_age=timedelta(days=1),
                legal_basis="l", deletion_mode=bad,
            )
