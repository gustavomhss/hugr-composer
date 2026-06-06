"""Multi-tenant admin — tenant-scope + impersonation + audit.

Self-contained demo. Production version wires these to CurrentPrincipal +
RequestGuard + TamperEvidentAuditLog under core/venous/.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    is_super_admin: bool = False
    impersonated_tenant_id: str | None = None

    @property
    def effective_tenant(self) -> str:
        return self.impersonated_tenant_id or self.tenant_id


@dataclass(frozen=True)
class AuditRecord:
    index: int
    actor: str                   # real user_id (NOT impersonated)
    tenant_id: str               # effective tenant (impersonated if any)
    action: str                  # "READ" / "WRITE" / "IMPERSONATE" / ...
    resource: str
    before: str
    after: str
    prev_hash: str
    this_hash: str


def _hash(prev: str, payload: dict) -> str:
    blob = prev.encode() + b"|" + json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


class TenantStore:
    """In-memory tenant-scoped key-value store with a cross-tenant guard."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict] = {}  # (tenant, row_id) → data
        self._lock = threading.Lock()

    def get(self, principal: Principal, row_id: str) -> dict | None:
        with self._lock:
            for (tid, rid), val in self._rows.items():
                if rid == row_id and tid == principal.effective_tenant:
                    return dict(val)
            # No match — could be "doesn't exist" OR "other tenant". Return
            # None in both cases (404) so we never leak existence.
            return None

    def put(self, principal: Principal, row_id: str, data: dict) -> dict:
        with self._lock:
            self._rows[(principal.effective_tenant, row_id)] = dict(data)
            return dict(data)

    def purge_tenant(self, tenant_id: str) -> int:
        with self._lock:
            keys = [k for k in self._rows if k[0] == tenant_id]
            for k in keys:
                del self._rows[k]
            return len(keys)


class TamperEvidentAuditLog:
    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def append(
        self, *, actor: str, tenant_id: str, action: str,
        resource: str, before: str = "", after: str = "",
    ) -> AuditRecord:
        with self._lock:
            prev = self._records[-1].this_hash if self._records else self.GENESIS
            idx = len(self._records)
            payload = {
                "index": idx, "actor": actor, "tenant_id": tenant_id,
                "action": action, "resource": resource,
                "before": before, "after": after,
            }
            rec = AuditRecord(
                index=idx, actor=actor, tenant_id=tenant_id, action=action,
                resource=resource, before=before, after=after,
                prev_hash=prev, this_hash=_hash(prev, payload),
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
                "index": r.index, "actor": r.actor, "tenant_id": r.tenant_id,
                "action": r.action, "resource": r.resource,
                "before": r.before, "after": r.after,
            })
            if r.this_hash != expected:
                return False
            prev = r.this_hash
        return True


def impersonate(principal: Principal, target_tenant: str, log: TamperEvidentAuditLog) -> Principal:
    if not principal.is_super_admin:
        raise PermissionError("only super-admins can impersonate")
    # Audit BEFORE switching identity, so the record carries the real user.
    log.append(
        actor=principal.user_id, tenant_id=target_tenant,
        action="IMPERSONATE", resource=f"tenant:{target_tenant}",
    )
    return Principal(
        user_id=principal.user_id, tenant_id=principal.tenant_id,
        is_super_admin=True, impersonated_tenant_id=target_tenant,
    )
