"""RetentionPolicy primitive — declarative data-class TTL with hard write gate.

Catalog fidelity: implements `RetentionPolicy` dataclass + `RetentionEnforcer`
Protocol verbatim from `docs/research/outputs/AGENT_6_COMPLIANCE.json`.

Regulation anchors:

- GDPR Article 5(1)(e) — storage limitation: personal data MUST be kept no
  longer than necessary; `max_age` codifies this per `data_class`.
- PCI-DSS v4.0 Requirement 3.2 — do not store cardholder data beyond
  retention need; enforced by `enforce_on_write`.
- NIST SP 800-53 rev 5 SI-12 — information management and retention.

Invariant IDs:

- RP_INV_01: Every persisted record MUST be tagged with a `data_class`
  that maps to a registered policy; untagged writes SHALL be rejected.
- RP_INV_02: `max_age` MUST be finite and > 0. 'Keep forever' without an
  explicit `legal_basis` override CANNOT be registered.
- RP_INV_03: `deletion_mode` MUST be one of 'hard', 'crypto_shred',
  'anonymize'. Other values SHALL raise on bind.
- RP_INV_04: `sweep()` MUST be idempotent and SHALL NOT delete records
  under an active `LegalHold`.
- RP_INV_05: Every purge action MUST emit a `TamperEvidentAuditLog`
  entry with the policy id and record count.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, runtime_checkable

ALLOWED_DELETION_MODES: Final[frozenset[str]] = frozenset(
    {"hard", "crypto_shred", "anonymize"}
)


class RetentionPolicyError(ValueError):
    """Runtime invariant violation on RetentionPolicy."""


@dataclass(frozen=True)
class RetentionPolicy:
    """Immutable policy binding (data_class → max_age + deletion mode)."""

    data_class: str
    max_age: timedelta
    legal_basis: str
    deletion_mode: str  # 'hard' | 'crypto_shred' | 'anonymize'

    def __post_init__(self) -> None:
        # RP_INV_01: data_class non-empty.
        if not isinstance(self.data_class, str) or not self.data_class.strip():
            raise RetentionPolicyError(
                "RP_INV_01: data_class MUST be a non-empty string."
            )
        # RP_INV_02: max_age finite and > 0.
        if not isinstance(self.max_age, timedelta):
            raise RetentionPolicyError("RP_INV_02: max_age MUST be a timedelta.")
        if self.max_age <= timedelta(0):
            raise RetentionPolicyError(
                "RP_INV_02: max_age MUST be > 0; 'keep forever' CANNOT be registered."
            )
        if not isinstance(self.legal_basis, str) or not self.legal_basis.strip():
            raise RetentionPolicyError(
                "RP_INV_02: legal_basis MUST be a non-empty string citing the statute / control."
            )
        # RP_INV_03: deletion_mode enum.
        if self.deletion_mode not in ALLOWED_DELETION_MODES:
            raise RetentionPolicyError(
                f"RP_INV_03: deletion_mode MUST be in {sorted(ALLOWED_DELETION_MODES)}; "
                f"got {self.deletion_mode!r}."
            )


@runtime_checkable
class HoldCheck(Protocol):
    """LegalHold interception hook (duck-typed to avoid circular imports)."""

    def covers(self, record_id: str) -> bool: ...


@runtime_checkable
class AuditSink(Protocol):
    """Emits one TamperEvidentAuditLog entry per purge; decoupled from the log impl."""

    def append(
        self,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        attributes: Mapping[str, object],
    ) -> str: ...


@runtime_checkable
class RetentionEnforcer(Protocol):
    """Catalog-defined Protocol."""

    def bind(self, policy: RetentionPolicy) -> None: ...
    def enforce_on_write(self, data_class: str, record_id: str) -> None: ...
    def sweep(self) -> int: ...


# A record row: (record_id, data_class, written_at).
_RecordRow = tuple[str, str, datetime]


class InMemoryRetentionEnforcer:
    """Reference enforcer for tests and CI.

    Production wires storage-specific deletion adapters; this class proves the
    invariants hold against an in-memory record set.
    """

    def __init__(
        self,
        *,
        audit_sink: AuditSink | None = None,
        hold_check: HoldCheck | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._policies: dict[str, RetentionPolicy] = {}
        self._records: list[_RecordRow] = []
        self._audit = audit_sink
        self._hold = hold_check
        self._now = now or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------- Public API
    def bind(self, policy: RetentionPolicy) -> None:
        if not isinstance(policy, RetentionPolicy):
            raise RetentionPolicyError(
                "RP_INV_03: bind() requires a RetentionPolicy instance."
            )
        self._policies[policy.data_class] = policy

    def enforce_on_write(self, data_class: str, record_id: str) -> None:
        """RP_INV_01: reject any write whose data_class is not registered."""
        if data_class not in self._policies:
            raise RetentionPolicyError(
                f"RP_INV_01: data_class {data_class!r} has no bound RetentionPolicy; "
                f"write rejected."
            )
        if not isinstance(record_id, str) or not record_id.strip():
            raise RetentionPolicyError("RP_INV_01: record_id MUST be a non-empty string.")
        self._records.append((record_id, data_class, self._now()))

    def sweep(self) -> int:
        """RP_INV_04: idempotent; RP_INV_04+05: skip held records, emit audit row."""
        now = self._now()
        survivors: list[_RecordRow] = []
        purged_by_class: dict[str, int] = {}
        for rid, dc, written_at in self._records:
            policy = self._policies.get(dc)
            if policy is None:
                # A record whose policy was unbound is retained. This cannot
                # happen via enforce_on_write but could via tests; keep it.
                survivors.append((rid, dc, written_at))
                continue
            age = now - written_at
            if age <= policy.max_age:
                survivors.append((rid, dc, written_at))
                continue
            # RP_INV_04: skip records under active LegalHold.
            if self._hold is not None and self._hold.covers(rid):
                survivors.append((rid, dc, written_at))
                continue
            purged_by_class[dc] = purged_by_class.get(dc, 0) + 1
        self._records = survivors
        total = sum(purged_by_class.values())
        if total and self._audit is not None:
            # RP_INV_05: emit one audit entry per policy id.
            for dc, count in purged_by_class.items():
                self._audit.append(
                    actor="retention-sweeper",
                    action="purge",
                    resource=f"data_class:{dc}",
                    outcome="success",
                    attributes={"count": count, "mode": self._policies[dc].deletion_mode},
                )
        return total

    # ---------------------------------------------------------- Test surface
    @property
    def size(self) -> int:
        return len(self._records)

    def records(self) -> Iterable[_RecordRow]:
        return list(self._records)


__all__ = [
    "ALLOWED_DELETION_MODES",
    "AuditSink",
    "HoldCheck",
    "InMemoryRetentionEnforcer",
    "RetentionEnforcer",
    "RetentionPolicy",
    "RetentionPolicyError",
]
