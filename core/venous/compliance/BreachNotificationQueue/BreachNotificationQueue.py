"""BreachNotificationQueue primitive — GDPR Art 33 72-hour clock.

Regulation anchors:

- GDPR **Article 33** notification of personal data breach to supervisory
  authority within 72 hours.
- HIPAA Security Rule **§ 164.308(a)(6)** Security incident procedures.

Invariant IDs:

- BNQ_INV_01: An incident confirmed as affecting personal data MUST have a
  `notify_authority` call within 72 hours of `confirmed_at`; the queue
  SHALL emit a breach-of-SLA alert at T-24h.
- BNQ_INV_02: `open_incident` MUST be callable from any service with write
  access; NEVER a gating step that delays detection recording.
- BNQ_INV_03: Every state transition (open, confirm, notify, close) MUST
  emit a TamperEvidentAuditLog entry.
- BNQ_INV_04: `data_classes` on confirm MUST be a non-empty tuple of
  PiiClassification-registered classes.
- BNQ_INV_05: An incident CANNOT close without either a `notify_authority`
  entry or an explicit `no_notification_required` outcome with legal_basis.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal, Protocol, runtime_checkable

Severity = Literal["low", "medium", "high", "critical"]
ALLOWED_SEVERITIES: Final[frozenset[str]] = frozenset(
    {"low", "medium", "high", "critical"},
)

# GDPR Article 33 statutory window.
STATUTORY_WINDOW: Final[timedelta] = timedelta(hours=72)
SLA_WARNING: Final[timedelta] = timedelta(hours=48)  # T-24h from confirmed_at


class BreachNotificationQueueError(ValueError):
    """Runtime invariant violation."""


@runtime_checkable
class AuditSink(Protocol):
    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: Mapping[str, object]) -> str: ...


@dataclass
class _Incident:
    incident_id: str
    detected_at: datetime
    severity: Severity
    summary: str
    confirmed_at: datetime | None = None
    data_classes: tuple[str, ...] = ()
    notifications: list[tuple[str, datetime, str]] = field(default_factory=list)
    closed_outcome: str | None = None
    legal_basis: str | None = None


@runtime_checkable
class BreachNotificationQueue(Protocol):
    """Catalog-defined Protocol."""

    def open_incident(
        self, detected_at: datetime, severity: Severity, summary: str,
    ) -> str: ...

    def confirm(
        self, incident_id: str, confirmed_at: datetime,
        data_classes: tuple[str, ...],
    ) -> None: ...

    def notify_authority(
        self, incident_id: str, authority: str,
        at: datetime, reference: str,
    ) -> None: ...

    def close(self, incident_id: str, outcome: str) -> None: ...


class InMemoryBreachNotificationQueue:
    def __init__(
        self,
        *,
        audit_sink: AuditSink | None = None,
        registered_data_classes: frozenset[str] = frozenset(
            {"pii", "phi", "pci", "internal"},
        ),
    ) -> None:
        self._incidents: dict[str, _Incident] = {}
        self._audit = audit_sink
        self._registered = registered_data_classes
        self._lock = threading.Lock()

    def open_incident(
        self, detected_at: datetime, severity: Severity, summary: str,
    ) -> str:
        if severity not in ALLOWED_SEVERITIES:
            raise BreachNotificationQueueError(
                f"BNQ_INV_02: severity MUST be in {sorted(ALLOWED_SEVERITIES)}."
            )
        if not isinstance(summary, str) or not summary.strip():
            raise BreachNotificationQueueError("BNQ_INV_02: summary MUST be non-empty.")
        if not isinstance(detected_at, datetime) or detected_at.tzinfo is None:
            raise BreachNotificationQueueError("BNQ_INV_02: detected_at MUST be tz-aware.")
        rid = f"inc-{uuid.uuid4().hex[:16]}"
        with self._lock:
            self._incidents[rid] = _Incident(
                incident_id=rid, detected_at=detected_at,
                severity=severity, summary=summary,
            )
        if self._audit is not None:
            self._audit.append(
                actor="breach-detector", action="breach.open",
                resource=f"inc:{rid}", outcome="success",
                attributes={"severity": severity},
            )
        return rid

    def confirm(
        self, incident_id: str, confirmed_at: datetime,
        data_classes: tuple[str, ...],
    ) -> None:
        if not isinstance(confirmed_at, datetime) or confirmed_at.tzinfo is None:
            raise BreachNotificationQueueError("BNQ_INV_04: confirmed_at MUST be tz-aware.")
        if not data_classes:
            raise BreachNotificationQueueError(
                "BNQ_INV_04: data_classes MUST be a non-empty tuple."
            )
        unregistered = {dc for dc in data_classes if dc not in self._registered}
        if unregistered:
            raise BreachNotificationQueueError(
                f"BNQ_INV_04: unregistered data_classes {sorted(unregistered)}."
            )
        with self._lock:
            inc = self._incidents.get(incident_id)
            if inc is None:
                raise BreachNotificationQueueError(
                    f"BNQ_INV_02: unknown incident_id {incident_id!r}."
                )
            inc.confirmed_at = confirmed_at
            inc.data_classes = tuple(data_classes)
        if self._audit is not None:
            self._audit.append(
                actor="breach-coord", action="breach.confirm",
                resource=f"inc:{incident_id}", outcome="success",
                attributes={"data_classes": list(data_classes)},
            )

    def notify_authority(
        self, incident_id: str, authority: str, at: datetime, reference: str,
    ) -> None:
        if not isinstance(authority, str) or not authority.strip():
            raise BreachNotificationQueueError("BNQ_INV_01: authority MUST be non-empty.")
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise BreachNotificationQueueError("BNQ_INV_01: at MUST be tz-aware.")
        with self._lock:
            inc = self._incidents.get(incident_id)
            if inc is None:
                raise BreachNotificationQueueError(
                    f"BNQ_INV_02: unknown incident_id {incident_id!r}."
                )
            if inc.confirmed_at is None:
                raise BreachNotificationQueueError(
                    "BNQ_INV_01: incident MUST be confirmed before notify_authority."
                )
            inc.notifications.append((authority, at, reference))
        if self._audit is not None:
            self._audit.append(
                actor="breach-coord", action="breach.notify",
                resource=f"inc:{incident_id}", outcome="success",
                attributes={"authority": authority, "reference": reference},
            )

    def close(
        self, incident_id: str, outcome: str,
        *, legal_basis: str | None = None,
    ) -> None:
        if outcome not in ("completed", "no_notification_required"):
            raise BreachNotificationQueueError(
                "BNQ_INV_05: outcome MUST be 'completed' or 'no_notification_required'."
            )
        with self._lock:
            inc = self._incidents.get(incident_id)
            if inc is None:
                raise BreachNotificationQueueError(
                    f"BNQ_INV_02: unknown incident_id {incident_id!r}."
                )
            if outcome == "completed" and not inc.notifications:
                raise BreachNotificationQueueError(
                    "BNQ_INV_05: close('completed') requires at least one notify_authority entry."
                )
            if outcome == "no_notification_required":
                if not legal_basis or not legal_basis.strip():
                    raise BreachNotificationQueueError(
                        "BNQ_INV_05: outcome='no_notification_required' requires legal_basis."
                    )
            inc.closed_outcome = outcome
            inc.legal_basis = legal_basis
        if self._audit is not None:
            self._audit.append(
                actor="breach-coord", action="breach.close",
                resource=f"inc:{incident_id}", outcome="success",
                attributes={"closed_outcome": outcome, "legal_basis": legal_basis or ""},
            )

    # ------------------------------------------------------------- Helpers
    def time_to_deadline(self, incident_id: str, now: datetime) -> timedelta | None:
        """BNQ_INV_01: seconds left to the 72-hour statutory deadline."""
        with self._lock:
            inc = self._incidents.get(incident_id)
            if inc is None or inc.confirmed_at is None:
                return None
            return (inc.confirmed_at + STATUTORY_WINDOW) - now

    def is_sla_warning(self, incident_id: str, now: datetime) -> bool:
        ttd = self.time_to_deadline(incident_id, now)
        if ttd is None:
            return False
        return ttd <= (STATUTORY_WINDOW - SLA_WARNING) and ttd > timedelta(0)

    def is_sla_breached(self, incident_id: str, now: datetime) -> bool:
        """BNQ_INV_01: True if the 72h deadline has passed AND no notification
        was filed **on time**. A late notification (after deadline) does NOT
        clear the breach — the regulatory violation is the late filing itself.
        """
        with self._lock:
            inc = self._incidents.get(incident_id)
            if inc is None or inc.confirmed_at is None:
                return False
            deadline = inc.confirmed_at + STATUTORY_WINDOW
            if now < deadline:
                return False
            on_time = any(n_at <= deadline for (_auth, n_at, _ref) in inc.notifications)
            return not on_time

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._incidents)


__all__ = [
    "ALLOWED_SEVERITIES",
    "SLA_WARNING",
    "STATUTORY_WINDOW",
    "AuditSink",
    "BreachNotificationQueue",
    "BreachNotificationQueueError",
    "InMemoryBreachNotificationQueue",
    "Severity",
]
