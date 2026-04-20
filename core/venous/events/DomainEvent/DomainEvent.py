"""DomainEvent primitive — Evans/Vernon/Richardson immutable domain fact.

Mirrors the catalog Protocol for `events.DomainEvent` and installs the runtime
invariant checkers. Module load performs zero I/O.

Invariant IDs cited by this module:

- DE-INV-01: A DomainEvent MUST be immutable after publication; mutation or
  retroactive edit is FORBIDDEN. Enforced via frozen dataclass + MappingProxyType
  on the payload so deep access cannot mutate the recorded fact.
- DE-INV-02: event_id MUST be globally unique and stable so idempotent consumers
  can dedupe reliably. Enforced via UUID v7 (time-ordered, 128-bit) format
  validation.
- DE-INV-03: The event NEVER carries commands or intents; it only states that
  something already happened. Enforced by rejecting imperative verbs in
  event_type and by having no mutator methods on the event class.
- DE-INV-04: version SHALL increment per aggregate and serve as the ordering
  key within one aggregate stream. The AggregateEventStream state machine
  enforces strictly monotonic +1 increments per (aggregate_type, aggregate_id)
  and rejects gaps / duplicates / retroactive inserts.
- DE-INV-05: Schema evolution SHALL be additive within a given event_type;
  removing or renaming fields requires a new event_type. The SchemaRegistry
  state machine enforces this across schema_version bumps.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# UUID v7 layout: xxxxxxxx-xxxx-7xxx-[89ab]xxx-xxxxxxxxxxxx (RFC 9562).
# The 13th hex nibble MUST be '7' (version), the 17th MUST be 8, 9, a, or b
# (variant). Lowercase canonical form is required for stable dedup identity.
_UUID_V7_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
)

# RFC 3339 timestamp with UTC zone only ('Z' or '+00:00'). occurred_at MUST be
# in UTC so event_id time ordering and stream replay across regions stay stable.
_RFC3339_UTC_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$",
)

# Aggregate identifier: URN-safe, 1..200 chars, no control bytes.
_AGGREGATE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_\-:.]{1,200}$")

# event_type: dotted lowercase past-tense. Must not start with an imperative
# verb (DE-INV-03). Example: "account.opened", "order.line.added".
_EVENT_TYPE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*){1,6}$",
)

# DE-INV-03: imperative / command-like verbs that are FORBIDDEN as the final
# segment of event_type. An event records a fact, not an intent.
_COMMAND_VERBS: Final[frozenset[str]] = frozenset(
    {
        "create",
        "update",
        "delete",
        "remove",
        "add",
        "set",
        "post",
        "put",
        "patch",
        "send",
        "publish",
        "execute",
        "run",
        "do",
        "perform",
        "process",
        "handle",
        "request",
        "ensure",
        "make",
        "fix",
        "place",
        "cancel",
        "reject",
        "accept",
        "approve",
        "reserve",
        "refund",
        "charge",
        "ship",
        "start",
        "stop",
        "begin",
        "end",
        "open",
        "close",
    },
)

_MAX_AGG_TYPE_LEN: Final[int] = 80
_MAX_PAYLOAD_KEYS: Final[int] = 200

# Schema version begins at 1 and MUST increment monotonically.
_MIN_SCHEMA_VERSION: Final[int] = 1


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------
class DomainEventInvariantError(ValueError):
    """Raised when a DomainEvent construction or publication violates an invariant."""


class SchemaRegistryError(DomainEventInvariantError):
    """Raised when a schema registration violates DE-INV-05."""


class AggregateStreamError(DomainEventInvariantError):
    """Raised when an aggregate-stream publish violates DE-INV-04."""


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def _freeze_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """DE-INV-01: transitively freeze a payload mapping.

    The catalog Protocol signs `payload: Mapping[str, Any]`; we accept any
    Mapping and return a MappingProxyType wrapping a deep copy. Nested dicts
    are recursively frozen. Lists become tuples so callers cannot mutate
    elements in-place.
    """
    if not isinstance(payload, Mapping):
        raise DomainEventInvariantError(
            f"DE-INV-01: payload MUST be a Mapping, got {type(payload).__name__}.",
        )
    if len(payload) > _MAX_PAYLOAD_KEYS:
        raise DomainEventInvariantError(
            f"DE-INV-01: payload has {len(payload)} keys; cap is {_MAX_PAYLOAD_KEYS}.",
        )
    frozen: dict[str, Any] = {}
    for k, v in payload.items():
        if not isinstance(k, str):
            raise DomainEventInvariantError(
                f"DE-INV-01: payload keys MUST be str, got {type(k).__name__}.",
            )
        frozen[k] = _freeze_value(v)
    return MappingProxyType(frozen)


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_payload(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(v) for v in value)
    if isinstance(value, (str, int, float, bool, bytes)) or value is None:
        return value
    # Any other object is accepted but stored by reference; callers are warned
    # via the DE-INV-01 contract text in DomainEvent.md that custom objects
    # MUST be themselves immutable.
    return value


def validate_event_id(value: object) -> str:
    """DE-INV-02: event_id MUST be a lowercase RFC 9562 UUID v7."""
    if not isinstance(value, str):
        raise DomainEventInvariantError(
            f"DE-INV-02: event_id MUST be a str, got {type(value).__name__}.",
        )
    if not _UUID_V7_RE.match(value):
        raise DomainEventInvariantError(
            f"DE-INV-02: event_id MUST be lowercase UUID v7, got {value!r}.",
        )
    return value


def validate_aggregate_id(value: object) -> str:
    if not isinstance(value, str):
        raise DomainEventInvariantError(
            f"DE-INV-02 supporting: aggregate_id MUST be str, "
            f"got {type(value).__name__}.",
        )
    if not _AGGREGATE_ID_RE.match(value):
        raise DomainEventInvariantError(
            f"DE-INV-02 supporting: aggregate_id {value!r} MUST match "
            f"[A-Za-z0-9_\\-:.]{{1,200}}.",
        )
    return value


def validate_aggregate_type(value: object) -> str:
    if not isinstance(value, str):
        raise DomainEventInvariantError(
            f"DE-INV-04 supporting: aggregate_type MUST be str, "
            f"got {type(value).__name__}.",
        )
    if not value or len(value) > _MAX_AGG_TYPE_LEN:
        raise DomainEventInvariantError(
            f"DE-INV-04 supporting: aggregate_type length {len(value)} out of range "
            f"[1..{_MAX_AGG_TYPE_LEN}].",
        )
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", value):
        raise DomainEventInvariantError(
            f"DE-INV-04 supporting: aggregate_type {value!r} MUST match "
            f"[A-Za-z][A-Za-z0-9_]*.",
        )
    return value


def validate_event_type(value: object) -> str:
    """DE-INV-03: event_type MUST be dotted lowercase and NEVER imperative."""
    if not isinstance(value, str):
        raise DomainEventInvariantError(
            f"DE-INV-03: event_type MUST be str, got {type(value).__name__}.",
        )
    if not _EVENT_TYPE_RE.match(value):
        raise DomainEventInvariantError(
            f"DE-INV-03: event_type {value!r} MUST match "
            r"'^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*){1,6}$' (dotted past-tense).",
        )
    last_segment = value.rsplit(".", 1)[-1]
    # Strip trailing "_" decorations; check the base verb.
    base = last_segment.rstrip("_").split("_")[0]
    if base in _COMMAND_VERBS:
        raise DomainEventInvariantError(
            f"DE-INV-03: event_type {value!r} ends with imperative verb "
            f"{base!r}; a domain event records a FACT, NEVER a command.",
        )
    return value


def validate_occurred_at(value: object) -> str:
    if not isinstance(value, str):
        raise DomainEventInvariantError(
            f"DE-INV-02 supporting: occurred_at MUST be str, "
            f"got {type(value).__name__}.",
        )
    if not _RFC3339_UTC_RE.match(value):
        raise DomainEventInvariantError(
            f"DE-INV-02 supporting: occurred_at {value!r} MUST be RFC 3339 UTC "
            f"(ending 'Z' or '+00:00').",
        )
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise DomainEventInvariantError(
            f"DE-INV-02 supporting: occurred_at {value!r} failed RFC 3339 parse: {e}",
        ) from e
    return value


def validate_version(value: object) -> int:
    """DE-INV-04: aggregate version MUST be a positive int fitting in 63 bits."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainEventInvariantError(
            f"DE-INV-04: version MUST be int, got {type(value).__name__}.",
        )
    if value < 1:
        raise DomainEventInvariantError(
            f"DE-INV-04: version MUST be >= 1, got {value}.",
        )
    if value >= 2**63:
        raise DomainEventInvariantError(
            f"DE-INV-04: version {value} exceeds 2^63 - 1.",
        )
    return value


def validate_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainEventInvariantError(
            f"DE-INV-05: schema_version MUST be int, got {type(value).__name__}.",
        )
    if value < _MIN_SCHEMA_VERSION:
        raise DomainEventInvariantError(
            f"DE-INV-05: schema_version MUST be >= {_MIN_SCHEMA_VERSION}, got {value}.",
        )
    return value


# ---------------------------------------------------------------------------
# Protocol surface — matches catalog api_signature verbatim
# ---------------------------------------------------------------------------
@runtime_checkable
class DomainEvent(Protocol):
    @property
    def event_id(self) -> str: ...
    @property
    def aggregate_id(self) -> str: ...
    @property
    def occurred_at(self) -> str: ...
    @property
    def version(self) -> int: ...
    @property
    def payload(self) -> Mapping[str, Any]: ...


# ---------------------------------------------------------------------------
# Frozen reference implementation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FrozenDomainEvent:
    """Reference DomainEvent — immutable, schema-versioned, ordering-aware.

    Extra fields beyond the Protocol (``aggregate_type``, ``event_type``,
    ``schema_version``) are needed for the registry (DE-INV-05) and the
    per-aggregate ordering stream (DE-INV-04). They default to safe values
    so Protocol-shape consumers see only the catalog surface.
    """

    event_id: str
    aggregate_id: str
    occurred_at: str
    version: int
    payload: Mapping[str, Any]
    aggregate_type: str = "Aggregate"
    event_type: str = "domain.event.recorded"
    schema_version: int = _MIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_event_id(self.event_id)
        validate_aggregate_id(self.aggregate_id)
        validate_occurred_at(self.occurred_at)
        validate_version(self.version)
        validate_aggregate_type(self.aggregate_type)
        validate_event_type(self.event_type)
        validate_schema_version(self.schema_version)
        # DE-INV-01: freeze payload transitively and re-assign via object.__setattr__
        # because the dataclass is frozen.
        frozen = _freeze_payload(self.payload)
        object.__setattr__(self, "payload", frozen)

    # DE-INV-01: expose a stable dedup key for consumers.
    def dedup_key(self) -> str:
        return self.event_id

    # DE-INV-04: ordering key — (aggregate_type, aggregate_id, version).
    def ordering_key(self) -> tuple[str, str, int]:
        return (self.aggregate_type, self.aggregate_id, self.version)

    # DE-INV-01: serialisation is pure read; mutation of the returned dict
    # CANNOT leak back into the frozen event.
    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "version": self.version,
            "payload": _unfreeze(self.payload),
        }


def _unfreeze(value: object) -> Any:
    if isinstance(value, MappingProxyType) or isinstance(value, Mapping):
        return {k: _unfreeze(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_unfreeze(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Schema registry (DE-INV-05)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SchemaDescriptor:
    """Describes one additive version of an event_type's schema.

    `required_fields` is a frozenset of payload keys that MUST appear in every
    instance of this (event_type, schema_version). DE-INV-05 requires that
    later versions of the SAME event_type are supersets (additive only) of
    their predecessors.
    """

    event_type: str
    schema_version: int
    required_fields: frozenset[str]

    def __post_init__(self) -> None:
        validate_event_type(self.event_type)
        validate_schema_version(self.schema_version)


class SchemaRegistry:
    """Stateful registry of `(event_type, schema_version) -> SchemaDescriptor`.

    Enforces DE-INV-05: within one event_type, schema_version N+1 MUST be a
    strict superset of schema_version N (additive evolution only). Renames or
    removals REQUIRE a new event_type — reflected by rejecting the incompatible
    registration.
    """

    def __init__(self) -> None:
        self._by_type: dict[str, dict[int, SchemaDescriptor]] = {}
        self._lock = threading.Lock()

    def register(self, descriptor: SchemaDescriptor) -> None:
        with self._lock:
            chain = self._by_type.setdefault(descriptor.event_type, {})
            if descriptor.schema_version in chain:
                existing = chain[descriptor.schema_version]
                if existing.required_fields != descriptor.required_fields:
                    raise SchemaRegistryError(
                        f"DE-INV-05: event_type {descriptor.event_type!r} version "
                        f"{descriptor.schema_version} already registered with a "
                        f"different schema; mutating a published schema is FORBIDDEN.",
                    )
                return  # idempotent re-register with identical descriptor
            if chain:
                highest = max(chain)
                if descriptor.schema_version != highest + 1:
                    raise SchemaRegistryError(
                        f"DE-INV-05: schema_version MUST increment by 1 per event_type; "
                        f"last registered was {highest}, got {descriptor.schema_version}.",
                    )
                prev = chain[highest]
                if not prev.required_fields.issubset(descriptor.required_fields):
                    missing = prev.required_fields - descriptor.required_fields
                    raise SchemaRegistryError(
                        f"DE-INV-05: event_type {descriptor.event_type!r} version "
                        f"{descriptor.schema_version} drops required fields "
                        f"{sorted(missing)}; schema evolution MUST be additive. "
                        f"Use a new event_type to rename or remove fields.",
                    )
            chain[descriptor.schema_version] = descriptor

    def get(self, event_type: str, schema_version: int) -> SchemaDescriptor:
        with self._lock:
            chain = self._by_type.get(event_type)
            if chain is None or schema_version not in chain:
                raise SchemaRegistryError(
                    f"DE-INV-05: event_type {event_type!r} version {schema_version} "
                    f"is not registered; register the schema before publishing events.",
                )
            return chain[schema_version]

    def validate_event(self, event: FrozenDomainEvent) -> None:
        """DE-INV-05: reject any event whose payload violates the registered schema."""
        descriptor = self.get(event.event_type, event.schema_version)
        missing = descriptor.required_fields - set(event.payload.keys())
        if missing:
            raise SchemaRegistryError(
                f"DE-INV-05: event {event.event_id} payload is missing required "
                f"fields {sorted(missing)} for schema "
                f"({event.event_type}, v{event.schema_version}).",
            )


# ---------------------------------------------------------------------------
# Aggregate event stream (DE-INV-04) — pre-commit collection, post-commit publish
# ---------------------------------------------------------------------------
@dataclass
class _StreamState:
    last_version: int = 0
    pending: list[FrozenDomainEvent] = field(default_factory=list)
    seen_event_ids: set[str] = field(default_factory=set)


class AggregateEventStream:
    """Per-aggregate event stream enforcing DE-INV-04 ordering.

    Lifecycle (DDD canonical):

    1. Within a unit of work, events are COLLECTED via ``stage(evt)``. Staging
       validates monotonic version and unique event_id but does NOT publish.
    2. On commit success, ``flush(publish_fn)`` calls ``publish_fn(evt)`` for
       each staged event in order and advances ``last_version``.
    3. On rollback, ``discard()`` drops the staged events without publishing.

    The stream is thread-safe for concurrent stagers on DIFFERENT aggregates;
    for the SAME aggregate, staging is serialised via an internal lock so the
    monotonic-version invariant holds under race.
    """

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self._streams: dict[tuple[str, str], _StreamState] = {}
        self._registry = registry
        self._lock = threading.Lock()

    def _key(self, evt: FrozenDomainEvent) -> tuple[str, str]:
        return (evt.aggregate_type, evt.aggregate_id)

    def stage(self, evt: FrozenDomainEvent) -> None:
        """DE-INV-04: stage an event, validating it is the strict successor."""
        if self._registry is not None:
            self._registry.validate_event(evt)
        with self._lock:
            key = self._key(evt)
            state = self._streams.setdefault(key, _StreamState())
            if evt.event_id in state.seen_event_ids:
                raise AggregateStreamError(
                    f"DE-INV-02: event_id {evt.event_id} already staged for "
                    f"aggregate {key}; event ids MUST be globally unique.",
                )
            expected = state.last_version + len(state.pending) + 1
            if evt.version != expected:
                raise AggregateStreamError(
                    f"DE-INV-04: aggregate {key} expected version {expected}, "
                    f"got {evt.version}; versions MUST increment by exactly 1 "
                    f"with no gaps and no retroactive inserts.",
                )
            state.pending.append(evt)
            state.seen_event_ids.add(evt.event_id)

    def pending_count(self, aggregate_type: str, aggregate_id: str) -> int:
        with self._lock:
            state = self._streams.get((aggregate_type, aggregate_id))
            return 0 if state is None else len(state.pending)

    def last_version(self, aggregate_type: str, aggregate_id: str) -> int:
        with self._lock:
            state = self._streams.get((aggregate_type, aggregate_id))
            return 0 if state is None else state.last_version

    def flush(
        self,
        publish_fn: PublishFn,
    ) -> list[FrozenDomainEvent]:
        """DE-INV-04: publish all staged events post-commit in order; advance watermark."""
        published: list[FrozenDomainEvent] = []
        with self._lock:
            items = [
                (key, list(state.pending))
                for key, state in self._streams.items()
                if state.pending
            ]
        # Publish outside the lock so publisher I/O cannot deadlock staging.
        for _key, batch in items:
            for evt in batch:
                publish_fn(evt)
                published.append(evt)
        with self._lock:
            for key, batch in items:
                state = self._streams[key]
                state.last_version += len(batch)
                state.pending.clear()
        return published

    def discard(self) -> None:
        """Rollback: drop staged events across all aggregates without publishing."""
        with self._lock:
            for state in self._streams.values():
                for evt in state.pending:
                    state.seen_event_ids.discard(evt.event_id)
                state.pending.clear()


class PublishFn(Protocol):
    def __call__(self, evt: FrozenDomainEvent) -> None: ...


# ---------------------------------------------------------------------------
# Dedup oracle (DE-INV-02) — reference implementation used by tests
# ---------------------------------------------------------------------------
class InMemoryDedupSet:
    """Idempotent-consumer reference oracle keyed on event_id (DE-INV-02)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def accept(self, evt: FrozenDomainEvent) -> bool:
        """Return True on first sight, False on repeat."""
        key = evt.dedup_key()
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            return True

    def size(self) -> int:
        with self._lock:
            return len(self._seen)


__all__ = [
    "AggregateEventStream",
    "AggregateStreamError",
    "DomainEvent",
    "DomainEventInvariantError",
    "FrozenDomainEvent",
    "InMemoryDedupSet",
    "PublishFn",
    "SchemaDescriptor",
    "SchemaRegistry",
    "SchemaRegistryError",
    "validate_aggregate_id",
    "validate_aggregate_type",
    "validate_event_id",
    "validate_event_type",
    "validate_occurred_at",
    "validate_schema_version",
    "validate_version",
]
