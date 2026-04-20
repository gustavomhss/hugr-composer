"""Behavioral scenarios for BreachNotificationQueue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from BreachNotificationQueue import (
    BreachNotificationQueueError,
    InMemoryBreachNotificationQueue,
)


UTC = timezone.utc


def test_scenario_72h_notification_flow() -> None:
    q = InMemoryBreachNotificationQueue()
    detected = datetime(2026, 4, 1, tzinfo=UTC)
    rid = q.open_incident(detected, "critical", "prod-db exfil suspicion")
    q.confirm(rid, detected + timedelta(hours=4), data_classes=("pii", "phi"))
    q.notify_authority(rid, "IE DPC", detected + timedelta(hours=20), "REF-2026-042")
    q.close(rid, outcome="completed")


def test_scenario_sla_warning_at_48h() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(datetime(2026, 4, 1, tzinfo=UTC), "high", "x")
    q.confirm(rid, datetime(2026, 4, 1, tzinfo=UTC), data_classes=("pii",))
    # Within the 48-72h window → warning.
    assert q.is_sla_warning(rid, datetime(2026, 4, 3, hour=1, tzinfo=UTC)) is True


def test_scenario_close_requires_notify_or_basis() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(datetime(2026, 4, 1, tzinfo=UTC), "low", "x")
    q.confirm(rid, datetime(2026, 4, 1, tzinfo=UTC), data_classes=("internal",))
    with pytest.raises(BreachNotificationQueueError):
        q.close(rid, outcome="completed")


def test_scenario_no_notification_with_legal_basis() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(datetime(2026, 4, 1, tzinfo=UTC), "low", "x")
    q.confirm(rid, datetime(2026, 4, 1, tzinfo=UTC), data_classes=("internal",))
    q.close(rid, outcome="no_notification_required", legal_basis="Art 33(1) unlikely risk")


def test_scenario_late_notification_breaches_sla() -> None:
    q = InMemoryBreachNotificationQueue()
    t = datetime(2026, 4, 1, tzinfo=UTC)
    rid = q.open_incident(t, "high", "x")
    q.confirm(rid, t, data_classes=("pii",))
    # 80h after confirm, no notification → breached.
    assert q.is_sla_breached(rid, t + timedelta(hours=80)) is True
