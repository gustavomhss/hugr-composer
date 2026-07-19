"""Unit tests for BreachNotificationQueue — 3 per invariant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from BreachNotificationQueue import (
    BreachNotificationQueueError,
    InMemoryBreachNotificationQueue,
)

UTC = UTC
T = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)


# BNQ_INV_01 — 72-hour deadline & SLA alert.
def test_inv_sla_72h_confirms() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "anomaly")
    q.confirm(rid, T, data_classes=("pii",))
    q.notify_authority(rid, "IE DPC", T + timedelta(hours=1), "REF-1")
    # Before deadline → not breached.
    assert q.is_sla_breached(rid, T + timedelta(hours=2)) is False


def test_inv_sla_72h_prevents() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "anomaly")
    with pytest.raises(BreachNotificationQueueError):
        q.notify_authority(rid, "IE DPC", T, "REF")  # not confirmed yet


def test_inv_sla_72h_under_failure() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "critical", "breach")
    q.confirm(rid, T, data_classes=("pii",))
    # Past 72h with no notification → SLA breached.
    assert q.is_sla_breached(rid, T + timedelta(hours=80)) is True


# BNQ_INV_02 — open callable without gating.
def test_inv_open_non_gating_confirms() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "low", "minor")
    assert rid.startswith("inc-")


def test_inv_open_non_gating_prevents() -> None:
    q = InMemoryBreachNotificationQueue()
    with pytest.raises(BreachNotificationQueueError):
        q.open_incident(T, "XTREME", "x")  # type: ignore[arg-type]
    with pytest.raises(BreachNotificationQueueError):
        q.open_incident(T, "high", "")
    with pytest.raises(BreachNotificationQueueError):
        q.open_incident(datetime(2026, 4, 1), "high", "x")


def test_inv_open_non_gating_under_failure() -> None:
    q = InMemoryBreachNotificationQueue()
    # Many rapid opens succeed — no dependency on other primitives.
    ids = [q.open_incident(T, "low", f"s-{i}") for i in range(10)]
    assert len(set(ids)) == 10


# BNQ_INV_03 — every transition emits audit.
class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: object) -> str:
        self.rows.append({"action": action})
        return "h"


def test_inv_audit_lifecycle_confirms() -> None:
    sink = _Sink()
    q = InMemoryBreachNotificationQueue(audit_sink=sink)
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    q.notify_authority(rid, "IE DPC", T + timedelta(hours=1), "REF")
    q.close(rid, outcome="completed")
    actions = [r["action"] for r in sink.rows]
    assert actions == ["breach.open", "breach.confirm", "breach.notify", "breach.close"]


def test_inv_audit_lifecycle_prevents() -> None:
    sink = _Sink()
    q = InMemoryBreachNotificationQueue(audit_sink=sink)
    with pytest.raises(BreachNotificationQueueError):
        q.open_incident(T, "BAD", "x")  # type: ignore[arg-type]
    assert sink.rows == []


def test_inv_audit_lifecycle_under_failure() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    assert q.size == 1


# BNQ_INV_04 — data_classes non-empty + registered.
def test_inv_data_classes_confirms() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii", "phi"))


def test_inv_data_classes_prevents() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    with pytest.raises(BreachNotificationQueueError):
        q.confirm(rid, T, data_classes=())


def test_inv_data_classes_under_failure() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    with pytest.raises(BreachNotificationQueueError):
        q.confirm(rid, T, data_classes=("made_up_class",))


# BNQ_INV_05 — close requires notify or explicit no_notification_required.
def test_inv_close_gated_confirms() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    q.notify_authority(rid, "IE DPC", T + timedelta(hours=1), "REF")
    q.close(rid, outcome="completed")


def test_inv_close_gated_prevents() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    with pytest.raises(BreachNotificationQueueError):
        q.close(rid, outcome="completed")  # no notify, no legal_basis


def test_inv_close_gated_under_failure() -> None:
    q = InMemoryBreachNotificationQueue()
    rid = q.open_incident(T, "high", "x")
    q.confirm(rid, T, data_classes=("pii",))
    q.close(rid, outcome="no_notification_required", legal_basis="low severity; no personal data affected")
