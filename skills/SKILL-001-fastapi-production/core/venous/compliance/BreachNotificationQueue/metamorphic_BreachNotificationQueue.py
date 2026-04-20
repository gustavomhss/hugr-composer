"""Metamorphic tests for BreachNotificationQueue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from BreachNotificationQueue import InMemoryBreachNotificationQueue


UTC = timezone.utc
T = datetime(2026, 4, 1, tzinfo=UTC)


def test_metamorphic_deadline_monotonic() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    a = q.time_to_deadline(rid, T)
    b = q.time_to_deadline(rid, T + timedelta(hours=1))
    assert a is not None and b is not None and a > b


def test_metamorphic_two_incidents_independent() -> None:
    q = InMemoryBreachNotificationQueue()
    r1 = q.open_incident(T, "high", "a")
    r2 = q.open_incident(T, "low", "b")
    assert r1 != r2 and q.size == 2


def test_metamorphic_multiple_notifications() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    q.notify_authority(rid, "IE DPC", T + timedelta(hours=1), "REF-1")
    q.notify_authority(rid, "FR CNIL", T + timedelta(hours=2), "REF-2")
    q.close(rid, outcome="completed")


def test_differential_close_outcomes() -> None:
    q = InMemoryBreachNotificationQueue()
    r1 = q.open_incident(T, "high", "a")
    r2 = q.open_incident(T, "low", "b")
    q.confirm(r1, T, data_classes=("pii",))
    q.confirm(r2, T, data_classes=("internal",))
    q.notify_authority(r1, "DPC", T + timedelta(hours=1), "REF")
    q.close(r1, outcome="completed")
    q.close(r2, outcome="no_notification_required", legal_basis="low risk")


def test_metamorphic_sla_warning_then_breach() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    # At T+50h: warning (between 48 and 72).
    assert q.is_sla_warning(rid, T + timedelta(hours=50)) is True
    # At T+80h: breached.
    assert q.is_sla_breached(rid, T + timedelta(hours=80)) is True
