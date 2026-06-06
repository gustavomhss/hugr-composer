"""RBAC + tamper-evident audit + break-glass role.

Self-contained demo of the `RequestGuard` + `TamperEvidentAuditLog` recipe.
The production version wires these stubs to primitives under `core/venous/`.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Literal


Decision = Literal["allow", "deny"]


@dataclass(frozen=True)
class AuditRecord:
    index: int
    user: str
    resource: str
    decision: Decision
    reason: str
    prev_hash: str
    this_hash: str


def _hash(prev_hash: str, payload: dict) -> str:
    blob = prev_hash.encode() + b"|" + json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


class TamperEvidentAuditLog:
    """Mirror of `TamperEvidentAuditLog` primitive.

    Invariant: ``verify()`` returns True iff every record's ``this_hash``
    equals ``sha256(prev_hash || payload)``. Altering any field breaks it.
    """

    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def append(self, *, user: str, resource: str, decision: Decision, reason: str) -> AuditRecord:
        with self._lock:
            prev = self._records[-1].this_hash if self._records else self.GENESIS
            idx = len(self._records)
            payload = {"index": idx, "user": user, "resource": resource,
                       "decision": decision, "reason": reason}
            rec = AuditRecord(
                index=idx, user=user, resource=resource, decision=decision,
                reason=reason, prev_hash=prev, this_hash=_hash(prev, payload),
            )
            self._records.append(rec)
            return rec

    def records(self) -> list[AuditRecord]:
        return list(self._records)

    def verify(self, records: list[AuditRecord] | None = None) -> bool:
        records = records if records is not None else list(self._records)
        prev = self.GENESIS
        for i, r in enumerate(records):
            if r.index != i or r.prev_hash != prev:
                return False
            expected = _hash(prev, {
                "index": r.index, "user": r.user, "resource": r.resource,
                "decision": r.decision, "reason": r.reason,
            })
            if r.this_hash != expected:
                return False
            prev = r.this_hash
        return True


@dataclass
class Grant:
    role: str
    reason: str
    expires_at: float


class BreakGlassRegistry:
    """Mirror of break-glass component. Grants expire; cannot be renewed
    without a fresh ``reason``.
    """

    def __init__(self) -> None:
        self._grants: dict[str, Grant] = {}
        self._lock = threading.Lock()

    def grant(self, user: str, reason: str, *, now: float, ttl_s: float) -> Grant:
        if not reason.strip():
            raise ValueError("break-glass requires a reason")
        with self._lock:
            existing = self._grants.get(user)
            if existing and existing.reason == reason and existing.expires_at > now:
                raise ValueError("break-glass grant cannot be renewed with the same reason")
            g = Grant(role="break_glass_admin", reason=reason, expires_at=now + ttl_s)
            self._grants[user] = g
            return g

    def active_role(self, user: str, *, now: float) -> str | None:
        with self._lock:
            g = self._grants.get(user)
            if g is None or g.expires_at <= now:
                return None
            return g.role


class RequestGuard:
    """Mirror of `RequestGuard` primitive. Records every check to the audit log."""

    def __init__(self, audit: TamperEvidentAuditLog) -> None:
        self._audit = audit

    def check(self, *, user: str, user_roles: set[str], resource: str,
              required_role: str) -> tuple[Decision, AuditRecord]:
        if required_role in user_roles:
            rec = self._audit.append(user=user, resource=resource,
                                     decision="allow", reason="role-match")
            return "allow", rec
        rec = self._audit.append(user=user, resource=resource,
                                 decision="deny", reason=f"missing role {required_role}")
        return "deny", rec
