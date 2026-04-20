"""ConsentLedger primitive — append-only per-(subject, purpose) consent history.

Catalog fidelity: implements the `ConsentLedger` Protocol verbatim.

Regulation anchors:

- GDPR **Article 6(1)(a)** lawful basis via consent; **Article 7** conditions
  for consent (demonstrable, as easy to withdraw as to give, reference the
  version of the notice presented).
- AICPA SOC 2 Trust Services Criteria Privacy P3.1 — consent collection and
  documentation.

Invariant IDs:

- CL_INV_01: Consent MUST be keyed by (subject_id, purpose); blanket grants
  CANNOT be recorded.
- CL_INV_02: Every grant MUST cite a `notice_version`; missing or empty
  version SHALL raise.
- CL_INV_03: Revocation MUST take effect immediately: future `is_granted`
  calls for that (subject, purpose) MUST return False.
- CL_INV_04: History is append-only; a revocation NEVER erases a prior grant,
  it supersedes it in time.
- CL_INV_05: `is_granted(..., at=T)` MUST be evaluated against the state at
  `T` (or now), not against the current state, so audits reproduce past
  authorizations.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Literal, Protocol, runtime_checkable

ActionKind = Literal["grant", "revoke"]


class ConsentLedgerError(ValueError):
    """Runtime invariant violation."""


@dataclass(frozen=True)
class ConsentRow:
    """One append-only entry."""

    entry_id: str
    subject_id: str
    purpose: str
    kind: ActionKind
    notice_version: str  # empty for revoke
    at: datetime
    actor: str


@runtime_checkable
class ConsentLedger(Protocol):
    """Catalog-defined Protocol (verbatim)."""

    def grant(
        self, subject_id: str, purpose: str, notice_version: str, at: datetime,
    ) -> str: ...

    def revoke(self, subject_id: str, purpose: str, at: datetime) -> None: ...

    def is_granted(
        self, subject_id: str, purpose: str, at: datetime | None = None,
    ) -> bool: ...

    def history(self, subject_id: str) -> list[dict[str, object]]: ...


_RESERVED_ACTOR: Final[str] = "system"


def _check_utc(ts: datetime, field: str) -> None:
    if not isinstance(ts, datetime) or ts.tzinfo is None:
        raise ConsentLedgerError(f"CL_INV_05: {field} MUST be a tz-aware datetime.")
    off = ts.utcoffset()
    if off is None or off.total_seconds() != 0:
        raise ConsentLedgerError(f"CL_INV_05: {field} MUST be UTC.")


def _check_non_empty(v: object, name: str, inv: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ConsentLedgerError(f"{inv}: {name} MUST be a non-empty string.")
    return v


class InMemoryConsentLedger:
    """Reference `ConsentLedger` implementation: append-only, per-subject indexed."""

    def __init__(self) -> None:
        self._rows: list[ConsentRow] = []
        self._by_subject: dict[str, list[int]] = {}
        self._lock = threading.Lock()
        self._seq = 0

    # ------------------------------------------------------------- Public API
    def grant(
        self,
        subject_id: str,
        purpose: str,
        notice_version: str,
        at: datetime,
        *,
        actor: str = _RESERVED_ACTOR,
    ) -> str:
        """CL_INV_01 + CL_INV_02: record a scoped grant citing notice version."""
        _check_non_empty(subject_id, "subject_id", "CL_INV_01")
        _check_non_empty(purpose, "purpose", "CL_INV_01")
        _check_non_empty(notice_version, "notice_version", "CL_INV_02")
        _check_non_empty(actor, "actor", "CL_INV_01")
        _check_utc(at, "at")
        if "," in purpose:
            raise ConsentLedgerError(
                "CL_INV_01: purpose MUST be a single token; comma-separated "
                "blanket grants CANNOT be recorded."
            )
        return self._append(
            subject_id=subject_id, purpose=purpose, kind="grant",
            notice_version=notice_version, at=at, actor=actor,
        )

    def revoke(
        self,
        subject_id: str,
        purpose: str,
        at: datetime,
        *,
        actor: str = _RESERVED_ACTOR,
    ) -> None:
        """CL_INV_03: revocation takes effect immediately at `at`."""
        _check_non_empty(subject_id, "subject_id", "CL_INV_03")
        _check_non_empty(purpose, "purpose", "CL_INV_03")
        _check_non_empty(actor, "actor", "CL_INV_03")
        _check_utc(at, "at")
        self._append(
            subject_id=subject_id, purpose=purpose, kind="revoke",
            notice_version="", at=at, actor=actor,
        )

    def is_granted(
        self, subject_id: str, purpose: str, at: datetime | None = None,
    ) -> bool:
        """CL_INV_05: evaluate against history at time `at` (or now)."""
        when = at if at is not None else datetime.now(timezone.utc)
        _check_utc(when, "at")
        with self._lock:
            idxs = self._by_subject.get(subject_id, [])
            latest: ConsentRow | None = None
            for i in idxs:
                row = self._rows[i]
                if row.purpose != purpose:
                    continue
                if row.at > when:
                    continue
                if latest is None or row.at > latest.at:
                    latest = row
            return latest is not None and latest.kind == "grant"

    def history(self, subject_id: str) -> list[dict[str, object]]:
        """CL_INV_04: return every row ever appended for this subject."""
        with self._lock:
            idxs = self._by_subject.get(subject_id, [])
            out: list[dict[str, object]] = []
            for i in idxs:
                r = self._rows[i]
                out.append({
                    "entry_id": r.entry_id,
                    "subject_id": r.subject_id,
                    "purpose": r.purpose,
                    "kind": r.kind,
                    "notice_version": r.notice_version,
                    "at": r.at.isoformat(),
                    "actor": r.actor,
                })
            return out

    # ------------------------------------------------------------- Internal
    def _append(
        self,
        *,
        subject_id: str,
        purpose: str,
        kind: ActionKind,
        notice_version: str,
        at: datetime,
        actor: str,
    ) -> str:
        with self._lock:
            self._seq += 1
            eid = f"cl-{self._seq:012d}"
            row = ConsentRow(
                entry_id=eid, subject_id=subject_id, purpose=purpose,
                kind=kind, notice_version=notice_version, at=at, actor=actor,
            )
            self._by_subject.setdefault(subject_id, []).append(len(self._rows))
            self._rows.append(row)
            return eid

    # ------------------------------------------------------------- Test view
    @property
    def size(self) -> int:
        with self._lock:
            return len(self._rows)


__all__ = [
    "ActionKind",
    "ConsentLedger",
    "ConsentLedgerError",
    "ConsentRow",
    "InMemoryConsentLedger",
]
