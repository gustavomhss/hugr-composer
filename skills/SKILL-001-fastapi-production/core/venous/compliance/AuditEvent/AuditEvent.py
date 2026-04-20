"""AuditEvent primitive — append-only tamper-evident security records.

Catalog fidelity: implements the `AuditEvent` frozen dataclass and the
`AuditEventSink` Protocol exactly as specified in
`docs/research/outputs/AGENT_7_OBSERVABILITY.json`. The Protocol surface
is `emit(event)` and `verify_chain(from_event_id=None) -> bool`.

Invariant IDs (enforced at runtime):

- AUD-INV-01: `event_hash` MUST be SHA-256 over canonical serialization of
  non-hash fields concatenated with `prev_hash`; a mismatched hash SHALL
  invalidate the chain. Callers build events via `build_event(...)`; the
  sink re-computes the hash on every `emit` and refuses tampered events.
- AUD-INV-02: once emitted, an `AuditEvent` is append-only; `InMemoryAuditSink`
  exposes no mutation / deletion API and refuses re-emission of the same
  `event_id`.
- AUD-INV-03: `outcome` MUST be one of {'success', 'failure', 'denied'}; any
  other value is FORBIDDEN to keep SIEM queries queryable.
- AUD-INV-04: `actor_id` MUST be set even for system-initiated actions;
  'system' is a reserved literal and NEVER empty.
- AUD-INV-05: `occurred_at` MUST be an absolute UTC datetime (tz-aware, offset
  0); naive timestamps are FORBIDDEN because wall-clock skew across emitters
  would falsify causal order.
- AUD-INV-06: action verbs MUST come from the controlled vocabulary
  {CREATE, READ, UPDATE, DELETE, GRANT, REVOKE, EXPORT} or be a namespaced
  extension (`domain.verb`, e.g. `payment.refund`).

Design decisions:

- The dataclass is frozen so attribute reassignment raises at runtime; the
  only construction path that computes a correct `event_hash` is `build_event`,
  which keeps test fixtures and production callers aligned.
- The canonical serialization sorts attribute keys so two events that differ
  only in insertion order of their `attributes` mapping produce the same
  `event_hash` (metamorphic property).
- The in-memory sink uses a `threading.Lock` around the append and verify
  paths so concurrent writers observe atomic behaviour. The `_by_id` index
  lets `verify_chain(from_event_id=...)` skip to a partial segment without
  a linear scan of the entire chain.
- The sink exposes a `register_before_emit` hook so downstream `TransportAdapter`
  implementations (WORM, SIEM, warm-query) can fan out to multiple destinations
  without bypassing the hash-chain check.

No I/O at import; all dependencies are stdlib.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Final, Protocol, runtime_checkable

ALLOWED_OUTCOMES: Final[frozenset[str]] = frozenset({"success", "failure", "denied"})
ALLOWED_ACTIONS: Final[frozenset[str]] = frozenset(
    {"CREATE", "READ", "UPDATE", "DELETE", "GRANT", "REVOKE", "EXPORT"}
)
RESERVED_SYSTEM_ACTOR: Final[str] = "system"


class AuditEventInvariantError(ValueError):
    """Runtime invariant violation on an AuditEvent operation."""


@dataclass(frozen=True)
class AuditEvent:
    """Immutable, hash-chained audit record.

    Field order mirrors the catalog `PrimitiveSpec.api_signature` verbatim.
    Construction goes through `build_event` which computes `event_hash`;
    direct construction is supported for tests that craft tamper scenarios,
    but the sink still re-verifies the hash on `emit`.
    """

    event_id: str
    occurred_at: datetime
    actor_id: str
    actor_type: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    attributes: Mapping[str, str]
    prev_hash: str
    event_hash: str

    def __post_init__(self) -> None:
        # AUD-INV-03: outcome enum.
        if self.outcome not in ALLOWED_OUTCOMES:
            raise AuditEventInvariantError(
                f"AUD-INV-03: outcome MUST be one of {sorted(ALLOWED_OUTCOMES)}; got {self.outcome!r}."
            )
        # AUD-INV-04: actor_id non-empty (system is reserved).
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise AuditEventInvariantError(
                "AUD-INV-04: actor_id MUST be non-empty; use 'system' for system-initiated actions."
            )
        # AUD-INV-06: controlled vocabulary OR namespaced extension.
        if self.action not in ALLOWED_ACTIONS and "." not in self.action:
            raise AuditEventInvariantError(
                f"AUD-INV-06: action MUST be in {sorted(ALLOWED_ACTIONS)} or be a "
                f"namespaced action ('domain.verb'); got {self.action!r}."
            )
        # AUD-INV-05: tz-aware UTC with utcoffset == 0.
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None:
            raise AuditEventInvariantError(
                "AUD-INV-05: occurred_at MUST be a tz-aware datetime."
            )
        actual_offset = self.occurred_at.utcoffset()
        if actual_offset is None or actual_offset.total_seconds() != 0:
            raise AuditEventInvariantError(
                "AUD-INV-05: occurred_at MUST be UTC (utcoffset == 0)."
            )
        # Freeze attributes as a snapshot copy so downstream mutation cannot
        # alter the serialised payload after construction.
        object.__setattr__(self, "attributes", dict(self.attributes))


def _attrs_canonical(attrs: Mapping[str, str]) -> str:
    """Canonical, deterministic attribute serialisation for the hash.

    Sorting keys means order-equivalent `attributes` produce identical hashes.
    """
    return ",".join(f"{k}={v}" for k, v in sorted(attrs.items()))


def compute_event_hash(event: AuditEvent) -> str:
    """AUD-INV-01: SHA-256 over canonical serialization of non-hash fields + prev_hash."""
    canonical = (
        f"{event.event_id}|{event.occurred_at.isoformat()}|{event.actor_id}|"
        f"{event.actor_type}|{event.action}|{event.resource_type}|"
        f"{event.resource_id}|{event.outcome}|{_attrs_canonical(event.attributes)}|"
        f"{event.prev_hash}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_event(
    *,
    event_id: str,
    actor_id: str,
    actor_type: str,
    action: str,
    resource_type: str,
    resource_id: str,
    outcome: str,
    attributes: Mapping[str, str],
    prev_hash: str,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    """Build an `AuditEvent` with the correct `event_hash` per AUD-INV-01.

    `occurred_at` defaults to `datetime.now(timezone.utc)`. Python's `datetime`
    preserves microsecond precision on supported platforms, satisfying the
    ≥ millisecond requirement of AUD-INV-05.
    """
    ts = occurred_at or datetime.now(timezone.utc)
    temp = AuditEvent(
        event_id=event_id,
        occurred_at=ts,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        attributes=dict(attributes),
        prev_hash=prev_hash,
        event_hash="",
    )
    h = compute_event_hash(temp)
    return replace(temp, event_hash=h)


@runtime_checkable
class AuditEventSink(Protocol):
    """Catalog-defined sink Protocol (verbatim)."""

    def emit(self, event: AuditEvent) -> None: ...
    def verify_chain(self, from_event_id: str | None = None) -> bool: ...


class InMemoryAuditSink:
    """Reference `AuditEventSink` implementation with tamper-evidence.

    Production deployments wrap this behind a `FanOutSink` that emits in
    parallel to WORM storage (S3 Object Lock, Glacier), a SIEM for real-time
    alerting, and a warm-query store for operator lookups. The hash chain is
    the tamper-evidence primitive; storage-layer WORM complements but does
    not replace it.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._by_id: dict[str, int] = {}
        self._lock = threading.Lock()
        self._before_emit: list[Callable[[AuditEvent], None]] = []

    # --------------------------------------------------------- Public API
    def emit(self, event: AuditEvent) -> None:
        """AUD-INV-01 + AUD-INV-02 + AUD-INV-05 temporal monotonicity:
        verify hash, enforce non-decreasing `occurred_at` vs the tail,
        then append atomically.

        Backdating is explicitly forbidden. An attacker (or bug) inserting an
        event with `occurred_at` earlier than the chain tail would otherwise
        hide activity inside a pre-existing time window; the hash chain links
        insertion order, not wall-clock order, so clock monotonicity MUST be
        enforced at append time.
        """
        expected = compute_event_hash(event)
        if expected != event.event_hash:
            raise AuditEventInvariantError(
                f"AUD-INV-01: event_hash mismatch. expected {expected!r}, got {event.event_hash!r}."
            )
        with self._lock:
            if event.event_id in self._by_id:
                raise AuditEventInvariantError(
                    f"AUD-INV-02: event_id {event.event_id!r} already in chain; append-only."
                )
            # AUD-INV-05 temporal monotonicity.
            if self._events:
                tail_ts = self._events[-1].occurred_at
                if event.occurred_at < tail_ts:
                    raise AuditEventInvariantError(
                        f"AUD-INV-05: occurred_at {event.occurred_at.isoformat()} is "
                        f"earlier than tail {tail_ts.isoformat()}; backdating FORBIDDEN."
                    )
            for hook in self._before_emit:
                hook(event)
            self._by_id[event.event_id] = len(self._events)
            self._events.append(event)

    def verify_chain(self, from_event_id: str | None = None) -> bool:
        """Walk the chain, verifying every hash and every `prev_hash` link.

        Returns False on the first inconsistency. When `from_event_id` is
        provided, verification starts from that event's slot, using the
        previous event's `event_hash` as the expected `prev_hash`.
        """
        with self._lock:
            start = 0
            if from_event_id is not None:
                start = self._by_id.get(from_event_id, 0)
            prev = "" if start == 0 else self._events[start - 1].event_hash
            for event in self._events[start:]:
                if event.prev_hash != prev:
                    return False
                if compute_event_hash(event) != event.event_hash:
                    return False
                prev = event.event_hash
            return True

    # --------------------------------------------------- Extension contract
    def register_before_emit(self, hook: Callable[[AuditEvent], None]) -> None:
        """Register a pre-emit hook (e.g. SIEM fan-out) that runs inside
        the append lock so all sinks observe identical ordering."""
        self._before_emit.append(hook)

    @property
    def events(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._events)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._events)


__all__ = [
    "ALLOWED_ACTIONS",
    "ALLOWED_OUTCOMES",
    "RESERVED_SYSTEM_ACTOR",
    "AuditEvent",
    "AuditEventInvariantError",
    "AuditEventSink",
    "InMemoryAuditSink",
    "build_event",
    "compute_event_hash",
]
