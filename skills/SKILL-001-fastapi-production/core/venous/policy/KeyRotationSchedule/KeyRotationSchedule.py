"""KeyRotationSchedule primitive — scheduled key rotation with overlap window.

Regulation anchors:

- PCI-DSS v4.0 **Req 3.7.4** cryptographic key changes at defined cryptoperiod.
- NIST SP 800-53 rev 5 **SC-12** Cryptographic Key Establishment and Management.

Invariant IDs:

- KRS_INV_01: A new key version MUST be produced on or before
  `next_rotation_at`; a missed rotation raises an alert.
- KRS_INV_02: `overlap` MUST be > 0 so decryption of records written with
  the prior version NEVER fails during cutover.
- KRS_INV_03: `active_key()` MUST return exactly one current key per alias
  at any instant; ties or gaps CANNOT occur.
- KRS_INV_04: Keys past `cadence + overlap` MUST be marked decrypt-only;
  new writes with such keys SHALL be rejected.
- KRS_INV_05: Rotation events MUST emit a TamperEvidentAuditLog entry
  capturing old and new key versions.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


class KeyRotationScheduleError(ValueError):
    """Runtime invariant violation."""


@dataclass(frozen=True)
class KeyRotationSchedule:
    key_alias: str
    cadence: timedelta
    overlap: timedelta
    next_rotation_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.key_alias, str) or not self.key_alias.strip():
            raise KeyRotationScheduleError("KRS_INV_03: key_alias MUST be non-empty.")
        if not isinstance(self.cadence, timedelta) or self.cadence <= timedelta(0):
            raise KeyRotationScheduleError("KRS_INV_01: cadence MUST be > 0.")
        if not isinstance(self.overlap, timedelta) or self.overlap <= timedelta(0):
            raise KeyRotationScheduleError(
                "KRS_INV_02: overlap MUST be > 0 to cover prior-version decryption."
            )
        if (
            not isinstance(self.next_rotation_at, datetime)
            or self.next_rotation_at.tzinfo is None
        ):
            raise KeyRotationScheduleError(
                "KRS_INV_01: next_rotation_at MUST be tz-aware UTC."
            )


@dataclass(frozen=True)
class _KeyVersion:
    alias: str
    version: str
    created_at: datetime
    retired_at: datetime | None = None  # becomes decrypt-only after cadence + overlap


@runtime_checkable
class AuditSink(Protocol):
    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: Mapping[str, object]) -> str: ...


@runtime_checkable
class KeyRotator(Protocol):
    """Catalog-defined Protocol."""

    def schedule(self, sched: KeyRotationSchedule) -> None: ...
    def rotate_now(self, key_alias: str) -> str: ...
    def active_key(self, key_alias: str, at: datetime) -> str: ...


_EPOCH: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)


class InMemoryKeyRotator:
    def __init__(self, *, audit_sink: AuditSink | None = None) -> None:
        self._schedules: dict[str, KeyRotationSchedule] = {}
        self._versions: dict[str, list[_KeyVersion]] = {}
        self._audit = audit_sink
        self._lock = threading.Lock()
        self._seq = 0

    def schedule(self, sched: KeyRotationSchedule) -> None:
        if not isinstance(sched, KeyRotationSchedule):
            raise KeyRotationScheduleError("schedule() requires a KeyRotationSchedule.")
        with self._lock:
            self._schedules[sched.key_alias] = sched
            if sched.key_alias not in self._versions:
                # v1 is anchored at EPOCH so historical queries always find it
                # active until rotate_now() stamps a later version.
                v = _KeyVersion(
                    alias=sched.key_alias, version="v1",
                    created_at=_EPOCH,
                )
                self._versions[sched.key_alias] = [v]
                self._seq = 1

    def rotate_now(self, key_alias: str) -> str:
        with self._lock:
            sched = self._schedules.get(key_alias)
            if sched is None:
                raise KeyRotationScheduleError(
                    f"KRS_INV_01: no schedule for {key_alias!r}."
                )
            versions = self._versions.setdefault(key_alias, [])
            new_version_id = f"v{len(versions) + 1}"
            # Use wall-clock "now" verbatim — never clamp to next_rotation_at.
            # Clamping would hide missed-rotation evidence (KRS_INV_01).
            now = datetime.now(timezone.utc)
            # Mark previous version as "retired" at now + overlap; after that it
            # becomes decrypt-only.
            if versions:
                prev = versions[-1]
                versions[-1] = _KeyVersion(
                    alias=prev.alias, version=prev.version,
                    created_at=prev.created_at,
                    retired_at=now + sched.overlap,
                )
            new = _KeyVersion(alias=key_alias, version=new_version_id, created_at=now)
            versions.append(new)
            # KRS_INV_01: advance next_rotation_at so subsequent calls
            # measure missed rotations against the next deadline, not a stale one.
            self._schedules[key_alias] = KeyRotationSchedule(
                key_alias=sched.key_alias,
                cadence=sched.cadence,
                overlap=sched.overlap,
                next_rotation_at=now + sched.cadence,
            )
            old_version = versions[-2].version if len(versions) >= 2 else "(none)"
        if self._audit is not None:
            self._audit.append(
                actor="key-rotator", action="key.rotate",
                resource=f"key:{key_alias}", outcome="success",
                attributes={"old": old_version, "new": new_version_id},
            )
        return new_version_id

    def active_key(self, key_alias: str, at: datetime) -> str:
        """KRS_INV_04: return the encrypt-usable key at `at`.

        Versions with `retired_at is not None AND at > retired_at` are
        decrypt-only and MUST NOT be selected for new encryption.
        """
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise KeyRotationScheduleError("KRS_INV_03: at MUST be tz-aware.")
        with self._lock:
            versions = self._versions.get(key_alias, [])
            if not versions:
                raise KeyRotationScheduleError(
                    f"KRS_INV_03: no key versions for {key_alias!r}."
                )
            # Newest created_at <= at among non-decrypt-only versions.
            active: _KeyVersion | None = None
            for v in versions:
                if v.created_at > at:
                    continue
                if v.retired_at is not None and at > v.retired_at:
                    continue  # decrypt-only past retirement — KRS_INV_04
                if active is None or v.created_at > active.created_at:
                    active = v
            if active is None:
                raise KeyRotationScheduleError(
                    f"KRS_INV_04: no encrypt-usable key at {at.isoformat()} "
                    f"for {key_alias!r} (all versions retired)."
                )
            return active.version

    def is_decrypt_only(self, key_alias: str, version: str, at: datetime) -> bool:
        """KRS_INV_04: True iff the version has been retired AND `at` is past
        its retirement timestamp. `retired_at` is stamped at rotation time as
        `rotation_now + overlap`, so the overlap window is honored.
        """
        with self._lock:
            for v in self._versions.get(key_alias, []):
                if v.version == version:
                    return v.retired_at is not None and at > v.retired_at

        return False

    def is_missed_rotation(self, key_alias: str, now: datetime) -> bool:
        """KRS_INV_01: True if now > next_rotation_at AND there is no new version."""
        with self._lock:
            sched = self._schedules.get(key_alias)
            versions = self._versions.get(key_alias, [])
        if sched is None:
            return False
        if now <= sched.next_rotation_at:
            return False
        # KRS_INV_01: missed iff no version was produced at/after the deadline.
        return all(v.created_at < sched.next_rotation_at for v in versions)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._schedules)


__all__ = [
    "AuditSink",
    "InMemoryKeyRotator",
    "KeyRotationSchedule",
    "KeyRotationScheduleError",
    "KeyRotator",
]
