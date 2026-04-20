"""LegalHold primitive — suspends retention + erasure for recorded scopes.

Regulation anchors:

- AICPA SOC 2 Trust Services Criteria **CC2.3** internal communication
  about obligations; evidence preservation.
- NIST SP 800-53 rev 5 **AU-11** Audit Record Retention — preservation for
  investigations.

Invariant IDs:

- LH_INV_01: RetentionPolicy.sweep + DataSubjectRequest erasure MUST call
  `covers(record_id)` before deletion; deletion of held records is FORBIDDEN.
- LH_INV_02: Opening and releasing a hold MUST each emit a
  TamperEvidentAuditLog entry with actor + scope.
- LH_INV_03: A hold CANNOT be silently released; release requires a
  distinct `released_by` actor from `opened_by` (or an explicit override).
- LH_INV_04: Held records MUST remain readable; indexes SHALL NOT drop them.
- LH_INV_05: `scope_query` MUST be stable against schema evolution;
  unresolved fields SHALL raise at open time.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class LegalHoldError(ValueError):
    """Runtime invariant violation."""


@dataclass(frozen=True)
class LegalHold:
    hold_id: str
    scope_query: str
    opened_at: datetime
    opened_by: str

    def __post_init__(self) -> None:
        for name, val in (("hold_id", self.hold_id), ("scope_query", self.scope_query),
                          ("opened_by", self.opened_by)):
            if not isinstance(val, str) or not val.strip():
                raise LegalHoldError(f"LH_INV_02: {name} MUST be non-empty.")
        if not isinstance(self.opened_at, datetime) or self.opened_at.tzinfo is None:
            raise LegalHoldError("LH_INV_02: opened_at MUST be tz-aware UTC.")


@runtime_checkable
class AuditSink(Protocol):
    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: Mapping[str, object]) -> str: ...


@runtime_checkable
class LegalHoldRegistry(Protocol):
    """Catalog-defined Protocol."""

    def open(self, hold: LegalHold) -> None: ...
    def release(self, hold_id: str, released_by: str) -> None: ...
    def covers(self, record_id: str) -> bool: ...


class InMemoryLegalHoldRegistry:
    """Reference registry.

    `scope_query` is evaluated against a pluggable matcher — the default
    matcher uses simple prefix matching (`tenant_id:ACME:*`). Production
    wires an SQL-query evaluator whose schema tokens are validated at open.
    """

    def __init__(
        self,
        *,
        audit_sink: AuditSink,
        known_fields: frozenset[str] = frozenset({"tenant_id", "created_at", "record_id"}),
    ) -> None:
        # LH_INV_02: audit_sink is MANDATORY. A hold registry without an audit
        # trail would let open/release happen silently, violating the invariant.
        if audit_sink is None:
            raise LegalHoldError(
                "LH_INV_02: audit_sink is REQUIRED; legal-hold lifecycle "
                "cannot emit invariant-required audit events without one."
            )
        self._holds: dict[str, LegalHold] = {}
        self._released: set[str] = set()
        self._audit = audit_sink
        self._known_fields = known_fields
        self._lock = threading.Lock()

    def open(self, hold: LegalHold) -> None:
        if not isinstance(hold, LegalHold):
            raise LegalHoldError("LH_INV_02: open() requires a LegalHold instance.")
        # LH_INV_05: every field token in scope_query MUST be a known field.
        tokens = _extract_field_tokens(hold.scope_query)
        unknown = tokens - self._known_fields
        if unknown:
            raise LegalHoldError(
                f"LH_INV_05: scope_query references unknown fields {sorted(unknown)}."
            )
        # LH_INV_02: audit MUST be durable BEFORE state mutation so an audit
        # failure cannot leave the registry with an untracked hold.
        self._audit.append(
            actor=hold.opened_by, action="legal_hold.open",
            resource=f"hold:{hold.hold_id}", outcome="success",
            attributes={"scope_query": hold.scope_query},
        )
        with self._lock:
            if hold.hold_id in self._holds and hold.hold_id not in self._released:
                raise LegalHoldError(
                    f"LH_INV_02: hold {hold.hold_id!r} already open."
                )
            self._holds[hold.hold_id] = hold
            self._released.discard(hold.hold_id)

    def release(
        self, hold_id: str, released_by: str,
        *, override: bool = False, override_reason: str | None = None,
    ) -> None:
        if not isinstance(released_by, str) or not released_by.strip():
            raise LegalHoldError("LH_INV_03: released_by MUST be non-empty.")
        # LH_INV_03: separation-of-duty override REQUIRES a justification string
        # so the audit trail carries the reason for the single-actor release.
        if override and (not isinstance(override_reason, str) or not override_reason.strip()):
            raise LegalHoldError(
                "LH_INV_03: override=True requires a non-empty override_reason "
                "for the audit trail."
            )
        with self._lock:
            h = self._holds.get(hold_id)
            if h is None:
                raise LegalHoldError(f"LH_INV_02: unknown hold_id {hold_id!r}.")
            if hold_id in self._released:
                raise LegalHoldError(f"LH_INV_03: hold {hold_id!r} already released.")
            if released_by == h.opened_by and not override:
                raise LegalHoldError(
                    "LH_INV_03: released_by MUST differ from opened_by "
                    "(or pass override=True with an override_reason)."
                )
        # LH_INV_02: emit audit BEFORE finalizing release. An audit sink failure
        # leaves the hold active (safer default than a silent release).
        self._audit.append(
            actor=released_by, action="legal_hold.release",
            resource=f"hold:{hold_id}", outcome="success",
            attributes={
                "override": override,
                "override_reason": override_reason or "",
                "opened_by": h.opened_by,
            },
        )
        with self._lock:
            self._released.add(hold_id)

    def covers(self, record_id: str) -> bool:
        """LH_INV_01: returns True if any active hold's scope matches record_id."""
        with self._lock:
            for hid, h in self._holds.items():
                if hid in self._released:
                    continue
                if _simple_match(h.scope_query, record_id):
                    return True
            return False

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._holds) - len(self._released)


def _extract_field_tokens(query: str) -> frozenset[str]:
    """Very permissive tokeniser: identifiers followed by `=` or `>=` / `<=`."""
    import re
    pattern = re.compile(r"\b([a-z_][a-z0-9_]*)\s*(=|>=|<=|>|<|!=)")
    return frozenset(m.group(1) for m in pattern.finditer(query))


def _simple_match(query: str, record_id: str) -> bool:
    """Default scope evaluator.

    The reference implementation treats a `scope_query` like
    `record_id = 'user:42'` as a prefix match. Production wires a real SQL
    evaluator via the extension contract; this is enough to exercise the
    invariants in tests.
    """
    import re
    # record_id = 'prefix:*' style
    m = re.search(r"record_id\s*=\s*'([^']+)'", query)
    if m:
        needle = m.group(1)
        if needle.endswith("*"):
            return record_id.startswith(needle[:-1])
        return record_id == needle
    m = re.search(r"record_id\s*LIKE\s*'([^']+)'", query, re.IGNORECASE)
    if m:
        prefix = m.group(1).replace("%", "")
        return record_id.startswith(prefix)
    return False


__all__ = [
    "AuditSink",
    "InMemoryLegalHoldRegistry",
    "LegalHold",
    "LegalHoldError",
    "LegalHoldRegistry",
]
