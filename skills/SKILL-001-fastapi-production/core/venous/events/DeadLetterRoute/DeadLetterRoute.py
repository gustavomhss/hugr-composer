"""DeadLetterRoute primitive — named destination for undeliverable events.

Implements the catalog `events.DeadLetterRoute` frozen dataclass and its
`DeadLetterSink` Protocol. The module performs zero I/O at import. It also
ships an in-memory reference sink (`InMemoryDeadLetterSink`) that parks
failed envelopes with reason + failure_count + first_failed_at and exposes
inspect / requeue / purge operations with an audit trail.

Invariant IDs cited by this module:

- DLR_INV_01: A message delivered more than `max_deliveries` times MUST be
  routed to `destination_topic` and NEVER returned to the main topic.
- DLR_INV_02: The original EventEnvelope id and source ALWAYS survive
  routing so downstream audit can correlate.
- DLR_INV_03: `max_deliveries` MUST be a positive integer; zero or negative
  values SHALL raise a configuration error.
- DLR_INV_04: Routing to the dead letter destination CANNOT itself dead
  letter recursively in the same route.
- DLR_INV_05: The sink MUST record the terminal failure reason so operators
  can decide whether to replay.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from EventEnvelope import (  # type: ignore[import-not-found]  # DLR_INV_02 — sibling primitive resolved via conftest.py sys.path insert.
    EventEnvelope,
)

# ---------------------------------------------------------------------------
# Defaults / constants
# ---------------------------------------------------------------------------
_MAX_REASON_LEN: Final[int] = 512

# Audit event names (dotted, lowercase — observability schema).
_AUDIT_SEND: Final[str] = "dlq.sent"
_AUDIT_INSPECT: Final[str] = "dlq.inspected"
_AUDIT_REQUEUE: Final[str] = "dlq.requeued"
_AUDIT_PURGE: Final[str] = "dlq.purged"


# ---------------------------------------------------------------------------
# Dataclass surface — MATCHES CATALOG api_signature verbatim
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DeadLetterRoute:
    """Named dead-letter route configuration.

    `source_topic` is the origin where the envelope first circulated.
    `destination_topic` is where parked envelopes land once the redelivery
    budget is exhausted. `max_deliveries` is the positive delivery budget.

    Construction validates DLR_INV_03 — a non-positive `max_deliveries`
    raises `DeadLetterRouteInvariantError`. Construction also validates the
    DLR_INV_04 precondition: `source_topic` and `destination_topic` MUST
    differ, otherwise a route would recursively dead-letter itself.
    """

    source_topic: str
    destination_topic: str
    max_deliveries: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_topic, str) or not self.source_topic:
            raise DeadLetterRouteInvariantError(
                "DLR_INV_04: source_topic MUST be a non-empty string.",
            )
        if not isinstance(self.destination_topic, str) or not self.destination_topic:
            raise DeadLetterRouteInvariantError(
                "DLR_INV_04: destination_topic MUST be a non-empty string.",
            )
        if self.source_topic == self.destination_topic:
            # DLR_INV_04: a route whose destination equals its source is a
            # recursion trap — parking would re-enter the same topic.
            raise DeadLetterRouteInvariantError(
                "DLR_INV_04: destination_topic MUST differ from source_topic "
                "(a route CANNOT dead-letter into itself).",
            )
        if not isinstance(self.max_deliveries, int) or isinstance(
            self.max_deliveries, bool,
        ):
            # DLR_INV_03: reject bool (which is a subclass of int) explicitly —
            # accepting True/False would collapse the budget to 0 or 1 silently.
            raise DeadLetterRouteInvariantError(
                "DLR_INV_03: max_deliveries MUST be an integer (not bool).",
            )
        if self.max_deliveries <= 0:
            raise DeadLetterRouteInvariantError(
                "DLR_INV_03: max_deliveries MUST be a positive integer; "
                f"got {self.max_deliveries}.",
            )


# ---------------------------------------------------------------------------
# Protocol surface — MATCHES CATALOG api_signature verbatim
# ---------------------------------------------------------------------------
@runtime_checkable
class DeadLetterSink(Protocol):
    async def send(
        self,
        route: DeadLetterRoute,
        envelope: EventEnvelope,
        reason: str,
        attempt: int,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class DeadLetterRouteInvariantError(RuntimeError):
    """Raised when a DeadLetterRoute invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Parked record — one envelope sitting on the DLQ with audit metadata
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ParkedRecord:
    """One parked envelope with full terminal failure context.

    `first_failed_at` is an epoch-seconds float captured on the FIRST park of
    the (source_topic, source, id) tuple. Subsequent same-envelope parks (if
    the caller re-invokes `send` for the same dedup key) update
    `last_failed_at`, `last_reason`, and increment `failure_count` — but
    NEVER overwrite `first_failed_at` (DLR_INV_05 + DLR_INV_02 combined:
    audit lineage is monotonic).
    """

    route: DeadLetterRoute
    envelope: EventEnvelope
    last_reason: str
    first_failed_at: float
    last_failed_at: float
    failure_count: int
    last_attempt: int
    # Snapshot of identity (DLR_INV_02). Stored explicitly so an audit trail
    # survives even if the envelope object is later garbage-collected.
    origin_source: str
    origin_id: str


# ---------------------------------------------------------------------------
# Audit event — immutable record of every state-machine transition
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuditEvent:
    """One entry in the DLQ audit log."""

    event_name: str
    route_source: str
    route_destination: str
    envelope_source: str
    envelope_id: str
    reason: str
    attempt: int
    timestamp: float


# ---------------------------------------------------------------------------
# Reason normalizer — DLR_INV_05
# ---------------------------------------------------------------------------
def normalize_reason(reason: object) -> str:
    """Coerce an arbitrary reason-like object into a bounded string.

    DLR_INV_05: the sink MUST record *some* terminal reason. None / empty /
    whitespace-only inputs collapse to "unspecified" — but never to the
    empty string, which would make audit entries indistinguishable from
    missing data.
    """
    if reason is None:
        return "unspecified"
    text = str(reason).strip()
    if not text:
        return "unspecified"
    if len(text) > _MAX_REASON_LEN:
        return text[:_MAX_REASON_LEN]
    return text


# ---------------------------------------------------------------------------
# Requeue sink Protocol — the target the DLQ replays back to
# ---------------------------------------------------------------------------
class RequeueTarget(Protocol):
    async def republish(self, topic: str, envelope: EventEnvelope) -> None: ...


# ---------------------------------------------------------------------------
# Reference implementation — InMemoryDeadLetterSink
# ---------------------------------------------------------------------------
class InMemoryDeadLetterSink:
    """Reference `DeadLetterSink` that parks envelopes with full audit.

    State machine (per dedup key on a given route):

    ::

        UNKNOWN ---send---> PARKED ---requeue---> REPUBLISHED
                                 \\
                                  --purge------> EVICTED

    Once an envelope is REPUBLISHED or EVICTED it leaves `parked` — it can
    be PARKED again by a subsequent `send` (this is the normal retry path
    from the bus). Every transition emits an `AuditEvent`.

    Invariant coverage:

    - DLR_INV_01: `send` ALWAYS writes to `route.destination_topic` (via the
      internal parked map keyed by destination); it NEVER writes to the
      source topic. `requeue` hands the envelope to a `RequeueTarget`
      using `route.source_topic` as the republish destination — the caller
      (operator) decides whether to replay.
    - DLR_INV_02: `origin_source` and `origin_id` are captured at park time
      and are stable across inspect / requeue / purge.
    - DLR_INV_03: validated on `DeadLetterRoute` construction (above).
    - DLR_INV_04: `send` refuses to park an envelope whose route has
      `source_topic == destination_topic` (already rejected at construction)
      AND refuses to park an envelope that is already transiting the DLQ
      side (the envelope carries the `_DLQ_PARKED_MARKER` extension key).
    - DLR_INV_05: `last_reason` is recorded on every park — absent / blank
      reasons collapse to "unspecified" but NEVER vanish.
    """

    _DLQ_PARKED_MARKER: Final[str] = "dlqparked"

    def __init__(self) -> None:
        # (destination_topic, source, id) -> ParkedRecord
        self._parked: dict[tuple[str, str, str], ParkedRecord] = {}
        # Immutable audit log (append-only; exposed read-only).
        self._audit: list[AuditEvent] = []
        # Monotonic clock hook — tests override via subclass to freeze time.
        self._now: Callable[[], float] = time.time
        self._lock = threading.Lock()

    # ---- core send ---------------------------------------------------------
    async def send(
        self,
        route: DeadLetterRoute,
        envelope: EventEnvelope,
        reason: str,
        attempt: int,
    ) -> None:
        """Park `envelope` on `route.destination_topic`.

        The `attempt` argument SHOULD be `route.max_deliveries + 1` (the
        exhausted-budget invocation) per the catalog consumption example;
        lower values are accepted but logged verbatim so operators can
        reconstruct the timeline.
        """
        # DLR_INV_04: refuse recursive DLQ — an envelope that is already
        # marked as parked MUST NOT be re-parked on a route whose destination
        # IS its current source (that would loop).
        exts = envelope.extensions or {}
        if (
            exts.get(self._DLQ_PARKED_MARKER) == route.destination_topic
            and exts.get("dlqdest") == route.destination_topic
        ):
            raise DeadLetterRouteInvariantError(
                "DLR_INV_04: envelope is already parked on this destination — "
                "recursive dead-letter is FORBIDDEN.",
            )

        norm_reason = normalize_reason(reason)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            # Defensive: a negative / zero / bool attempt is meaningless and
            # would corrupt audit math downstream.
            raise DeadLetterRouteInvariantError(
                "DLR_INV_05: attempt MUST be a positive integer.",
            )

        with self._lock:
            now = self._now()
            key = (route.destination_topic, envelope.source, envelope.id)
            existing = self._parked.get(key)
            if existing is None:
                record = ParkedRecord(
                    route=route,
                    envelope=envelope,
                    last_reason=norm_reason,
                    first_failed_at=now,
                    last_failed_at=now,
                    failure_count=1,
                    last_attempt=attempt,
                    origin_source=envelope.source,
                    origin_id=envelope.id,
                )
            else:
                # DLR_INV_02 + DLR_INV_05: identity + lineage stable; counter
                # monotonic; first_failed_at IS NOT overwritten.
                record = ParkedRecord(
                    route=existing.route,
                    envelope=envelope,
                    last_reason=norm_reason,
                    first_failed_at=existing.first_failed_at,
                    last_failed_at=now,
                    failure_count=existing.failure_count + 1,
                    last_attempt=attempt,
                    origin_source=existing.origin_source,
                    origin_id=existing.origin_id,
                )
            self._parked[key] = record
            self._audit.append(
                AuditEvent(
                    event_name=_AUDIT_SEND,
                    route_source=route.source_topic,
                    route_destination=route.destination_topic,
                    envelope_source=envelope.source,
                    envelope_id=envelope.id,
                    reason=norm_reason,
                    attempt=attempt,
                    timestamp=now,
                ),
            )

    # ---- inspection --------------------------------------------------------
    def inspect(
        self, destination_topic: str, *, emit_audit: bool = True,
    ) -> tuple[ParkedRecord, ...]:
        """Return a snapshot of all parked records on `destination_topic`.

        A read-only operation; emits an audit event so operator reads are
        traceable. Pass `emit_audit=False` when the caller is itself a
        metrics scraper that MUST NOT pollute the audit log.
        """
        with self._lock:
            out = tuple(
                r for (dest, _src, _id), r in self._parked.items()
                if dest == destination_topic
            )
            if emit_audit:
                self._audit.append(
                    AuditEvent(
                        event_name=_AUDIT_INSPECT,
                        route_source="",
                        route_destination=destination_topic,
                        envelope_source="",
                        envelope_id="",
                        reason=f"count={len(out)}",
                        attempt=0,
                        timestamp=self._now(),
                    ),
                )
        return out

    # ---- requeue -----------------------------------------------------------
    async def requeue(
        self,
        destination_topic: str,
        envelope_source: str,
        envelope_id: str,
        target: RequeueTarget,
    ) -> ParkedRecord:
        """Re-publish a parked envelope to its original source topic.

        DLR_INV_02: the republished envelope carries the ORIGINAL id and
        source. DLR_INV_01 directionality: requeue goes DLQ -> source, never
        DLQ -> DLQ. On success the parked record is removed; failure keeps
        it parked and re-raises so operators can retry.

        Returns the ParkedRecord that WAS parked (for audit correlation).
        """
        with self._lock:
            key = (destination_topic, envelope_source, envelope_id)
            record = self._parked.get(key)
            if record is None:
                raise DeadLetterRouteInvariantError(
                    "DLR_INV_02: cannot requeue unknown envelope "
                    f"({envelope_source!r}, {envelope_id!r}) on "
                    f"{destination_topic!r}.",
                )
            # DLR_INV_02 idempotency: ATOMICALLY remove the parked record AND
            # journal the requeue intent BEFORE calling the async broker.
            # If the broker republish crashes or is retried by the caller, the
            # record is already gone from the parked set — the operator's retry
            # re-raises "unknown envelope" instead of silently re-publishing a
            # duplicate. On republish failure we re-park below.
            self._parked.pop(key, None)
            self._audit.append(
                AuditEvent(
                    event_name=_AUDIT_REQUEUE,
                    route_source=record.route.source_topic,
                    route_destination=record.route.destination_topic,
                    envelope_source=record.origin_source,
                    envelope_id=record.origin_id,
                    reason=record.last_reason,
                    attempt=record.last_attempt,
                    timestamp=self._now(),
                ),
            )

        # Republish OUTSIDE the lock — target may be async and slow.
        try:
            await target.republish(record.route.source_topic, record.envelope)
        except BaseException:
            # DLR_INV_02: republish failed — re-park so the caller can retry
            # without losing the envelope. Re-park is idempotent: duplicate
            # `requeue` post-re-park simply finds the record again.
            with self._lock:
                self._parked[key] = record
            raise
        return record

    # ---- purge -------------------------------------------------------------
    def purge(
        self,
        destination_topic: str,
        *,
        envelope_source: str | None = None,
        envelope_id: str | None = None,
        reason: str = "operator_purge",
    ) -> tuple[ParkedRecord, ...]:
        """Remove parked records. Returns the records evicted.

        If both `envelope_source` and `envelope_id` are None the whole
        destination is drained. Otherwise the single keyed record is evicted.
        An audit event is emitted per eviction so a mass-purge is reconstructible.
        """
        norm_reason = normalize_reason(reason)
        evicted: list[ParkedRecord] = []
        with self._lock:
            now = self._now()
            if envelope_source is None and envelope_id is None:
                to_evict = [
                    k for k in self._parked if k[0] == destination_topic
                ]
            elif envelope_source is not None and envelope_id is not None:
                key = (destination_topic, envelope_source, envelope_id)
                to_evict = [key] if key in self._parked else []
            else:
                raise DeadLetterRouteInvariantError(
                    "DLR_INV_05: purge MUST receive both envelope_source and "
                    "envelope_id, or neither.",
                )
            for k in to_evict:
                rec = self._parked.pop(k)
                evicted.append(rec)
                self._audit.append(
                    AuditEvent(
                        event_name=_AUDIT_PURGE,
                        route_source=rec.route.source_topic,
                        route_destination=rec.route.destination_topic,
                        envelope_source=rec.origin_source,
                        envelope_id=rec.origin_id,
                        reason=norm_reason,
                        attempt=rec.last_attempt,
                        timestamp=now,
                    ),
                )
        return tuple(evicted)

    # ---- introspection -----------------------------------------------------
    def depth(self, destination_topic: str) -> int:
        """Return the current parked count on `destination_topic`."""
        with self._lock:
            return sum(1 for (d, _s, _i) in self._parked if d == destination_topic)

    def audit_log(self) -> tuple[AuditEvent, ...]:
        """Return the immutable audit log snapshot."""
        with self._lock:
            return tuple(self._audit)

    def iter_parked(
        self, destination_topic: str,
    ) -> Iterator[ParkedRecord]:
        """Yield parked records on `destination_topic` in park order.

        Yields a snapshot — safe against concurrent mutation.
        """
        return iter(self.inspect(destination_topic, emit_audit=False))


# ---------------------------------------------------------------------------
# Observability sink — structured events for test harnesses
# ---------------------------------------------------------------------------
@dataclass
class DlqObservabilitySink:
    """Collects structured events for test harnesses.

    Mirrors the TopicBus `ObservabilitySink` shape so downstream aggregators
    can ingest both primitives with a single schema.
    """

    logs: list[dict[str, object]] = field(default_factory=list)

    def on_send(
        self, route: DeadLetterRoute, envelope: EventEnvelope, reason: str, attempt: int,
    ) -> None:
        self.logs.append(
            {
                "event_name": _AUDIT_SEND,
                "route_source": route.source_topic,
                "route_destination": route.destination_topic,
                "envelope_source": envelope.source,
                "envelope_id": envelope.id,
                "reason": reason,
                "attempt": attempt,
                "timestamp": time.time(),
            },
        )

    def on_requeue(self, record: ParkedRecord) -> None:
        self.logs.append(
            {
                "event_name": _AUDIT_REQUEUE,
                "route_source": record.route.source_topic,
                "route_destination": record.route.destination_topic,
                "envelope_source": record.origin_source,
                "envelope_id": record.origin_id,
                "reason": record.last_reason,
                "attempt": record.last_attempt,
            },
        )

    def on_purge(self, records: Sequence[ParkedRecord], reason: str) -> None:
        for r in records:
            self.logs.append(
                {
                    "event_name": _AUDIT_PURGE,
                    "route_source": r.route.source_topic,
                    "route_destination": r.route.destination_topic,
                    "envelope_source": r.origin_source,
                    "envelope_id": r.origin_id,
                    "reason": reason,
                },
            )


# ---------------------------------------------------------------------------
# Audit helpers (pure functions, read-only) — composable over an audit log
# ---------------------------------------------------------------------------
def filter_audit(
    audit: Sequence[AuditEvent], *, event_name: str | None = None,
) -> tuple[AuditEvent, ...]:
    """Return the subset of audit events matching `event_name`."""
    if event_name is None:
        return tuple(audit)
    return tuple(a for a in audit if a.event_name == event_name)


def audit_as_mapping(event: AuditEvent) -> Mapping[str, object]:
    """Render an `AuditEvent` as a plain Mapping for serialization harnesses."""
    return {
        "event_name": event.event_name,
        "route_source": event.route_source,
        "route_destination": event.route_destination,
        "envelope_source": event.envelope_source,
        "envelope_id": event.envelope_id,
        "reason": event.reason,
        "attempt": event.attempt,
        "timestamp": event.timestamp,
    }


__all__ = [
    "AuditEvent",
    "DeadLetterRoute",
    "DeadLetterRouteInvariantError",
    "DeadLetterSink",
    "DlqObservabilitySink",
    "InMemoryDeadLetterSink",
    "ParkedRecord",
    "RequeueTarget",
    "audit_as_mapping",
    "filter_audit",
    "normalize_reason",
]
