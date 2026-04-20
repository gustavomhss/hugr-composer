"""Chaos tests for BreachNotificationQueue."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from BreachNotificationQueue import (
    BreachNotificationQueueError,
    InMemoryBreachNotificationQueue,
)


UTC = timezone.utc
T = datetime(2026, 4, 1, tzinfo=UTC)


def test_chaos_concurrent_opens() -> None:
    q = InMemoryBreachNotificationQueue()

    def worker(i: int) -> None:
        q.open_incident(T, "low", f"s-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert q.size == 30


def test_chaos_invalid_severity_rejected() -> None:
    q = InMemoryBreachNotificationQueue()
    for bad in ("HIGH", "severe", "", "extreme"):
        with pytest.raises(BreachNotificationQueueError):
            q.open_incident(T, bad, "x")  # type: ignore[arg-type]


def test_chaos_confirm_unknown_incident() -> None:
    q = InMemoryBreachNotificationQueue()
    with pytest.raises(BreachNotificationQueueError):
        q.confirm("nope", T, data_classes=("pii",))


def test_chaos_notify_before_confirm_rejected() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    with pytest.raises(BreachNotificationQueueError):
        q.notify_authority(rid, "IE DPC", T, "REF")


def test_chaos_close_invalid_outcome_rejected() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    with pytest.raises(BreachNotificationQueueError):
        q.close(rid, outcome="in_progress")
