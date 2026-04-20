"""AccessLog primitive — records reads of classified data separately from security audit.

Regulation anchors:

- HIPAA Security Rule **45 CFR § 164.312(b)** audit controls — specifically
  § 164.528 accounting of disclosures requires a separate stream of reads.
- AICPA SOC 2 Trust Services Criteria **CC6.1** — logical access to
  protected information.

Invariant IDs:

- AL_INV_01: Every read of a classified record MUST emit one AccessLog
  entry before the response leaves the process.
- AL_INV_02: `purpose_of_use` MUST be one of a registered set; ad-hoc
  free-text values SHALL be rejected.
- AL_INV_03: AccessLog entries MUST NEVER be merged with TamperEvidentAuditLog
  so high-volume read traffic cannot mask low-volume security events (no
  shared storage; the two types have distinct class identities).
- AL_INV_04: `actor` MUST be a resolved identity; 'system' without a
  concrete id is FORBIDDEN.
- AL_INV_05: A retention policy MUST be bound at registration;
  unbounded accumulation CANNOT occur.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


class AccessLogError(ValueError):
    """Runtime invariant violation."""


_MAX_FIELD_LEN = 256


def _reject_untrusted_string(field: str, value: object, inv_id: str) -> None:
    """Reject empty / non-string / overlong / control-char-bearing inputs.

    Defense against log injection and unbounded growth: AccessLog entries are
    written from arbitrary caller-supplied identifiers, so we cap length and
    strip-reject any character that could break downstream log parsers.
    """
    if not isinstance(value, str) or not value.strip():
        raise AccessLogError(f"{inv_id}: {field} MUST be a non-empty string.")
    if len(value) > _MAX_FIELD_LEN:
        raise AccessLogError(
            f"{inv_id}: {field} exceeds {_MAX_FIELD_LEN} chars ({len(value)}); "
            f"callers MUST pseudonymize or truncate before recording."
        )
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise AccessLogError(
            f"{inv_id}: {field} contains control characters; log-injection rejected."
        )


@dataclass(frozen=True)
class AccessRow:
    actor: str
    record_id: str
    data_class: str
    purpose_of_use: str
    at: datetime


@runtime_checkable
class AccessLog(Protocol):
    """Catalog-defined Protocol."""

    def record_read(
        self, actor: str, record_id: str, data_class: str,
        purpose_of_use: str, at: datetime,
    ) -> None: ...

    def query(
        self, record_id: str | None = None, actor: str | None = None,
    ) -> list[dict[str, object]]: ...

    def count_by_actor(self, actor: str, since: datetime) -> int: ...


class InMemoryAccessLog:
    """Reference AccessLog implementation."""

    def __init__(
        self,
        *,
        allowed_purposes: Iterable[str] = ("treatment", "payment", "operations", "audit"),
        retention: timedelta | None = timedelta(days=180),
    ) -> None:
        if retention is None:
            raise AccessLogError(
                "AL_INV_05: retention MUST be bound at registration; "
                "use timedelta.max for permanent retention."
            )
        self._allowed = frozenset(allowed_purposes)
        if not self._allowed:
            raise AccessLogError("AL_INV_02: at least one purpose_of_use MUST be registered.")
        self._retention = retention
        self._rows: list[AccessRow] = []
        self._lock = threading.Lock()

    def record_read(
        self, actor: str, record_id: str, data_class: str,
        purpose_of_use: str, at: datetime,
    ) -> None:
        # AL_INV_04 / AL_INV_01 defense-in-depth: reject control characters
        # and oversized strings to prevent log injection + denial via growth.
        _reject_untrusted_string("actor", actor, "AL_INV_04")
        if actor == "system":
            raise AccessLogError(
                "AL_INV_04: 'system' without a concrete id is FORBIDDEN; "
                "use 'system:<subsystem>' or a service account id."
            )
        _reject_untrusted_string("record_id", record_id, "AL_INV_01")
        _reject_untrusted_string("data_class", data_class, "AL_INV_01")
        if purpose_of_use not in self._allowed:
            raise AccessLogError(
                f"AL_INV_02: purpose_of_use MUST be one of {sorted(self._allowed)}; "
                f"got {purpose_of_use!r}."
            )
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise AccessLogError("AL_INV_01: at MUST be a tz-aware datetime.")
        off = at.utcoffset()
        if off is None or off.total_seconds() != 0:
            raise AccessLogError("AL_INV_01: at MUST be UTC.")
        with self._lock:
            self._rows.append(AccessRow(
                actor=actor, record_id=record_id, data_class=data_class,
                purpose_of_use=purpose_of_use, at=at,
            ))

    def query(
        self, record_id: str | None = None, actor: str | None = None,
    ) -> list[dict[str, object]]:
        with self._lock:
            out: list[dict[str, object]] = []
            for r in self._rows:
                if record_id is not None and r.record_id != record_id:
                    continue
                if actor is not None and r.actor != actor:
                    continue
                out.append({
                    "actor": r.actor, "record_id": r.record_id,
                    "data_class": r.data_class,
                    "purpose_of_use": r.purpose_of_use,
                    "at": r.at.isoformat(),
                })
            return out

    def count_by_actor(self, actor: str, since: datetime) -> int:
        if not isinstance(since, datetime) or since.tzinfo is None:
            raise AccessLogError("AL_INV_01: since MUST be tz-aware.")
        with self._lock:
            return sum(1 for r in self._rows if r.actor == actor and r.at >= since)

    def sweep_retention(self, now: datetime | None = None) -> int:
        """AL_INV_05: drop rows older than retention. Returns number dropped."""
        t = now or datetime.now(timezone.utc)
        with self._lock:
            kept = [r for r in self._rows if t - r.at <= self._retention]
            dropped = len(self._rows) - len(kept)
            self._rows = kept
            return dropped

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._rows)


__all__ = [
    "AccessLog",
    "AccessLogError",
    "AccessRow",
    "InMemoryAccessLog",
]
