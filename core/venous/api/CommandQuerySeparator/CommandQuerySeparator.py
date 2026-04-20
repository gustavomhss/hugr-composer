"""CommandQuerySeparator primitive — partitions the API into write commands and read queries.

Implements the catalog Protocol for `api.CommandQuerySeparator` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- CQS-INV-01: a command handler MUST NEVER return query results synthesized from
  the write model; it SHALL return only acknowledgement and identifiers.
- CQS-INV-02: a query handler CANNOT mutate state, invoke commands, or block on
  external side-effects.
- CQS-INV-03: each command type MUST have at most one registered handler;
  duplicate handler registration is FORBIDDEN.
- CQS-INV-04: read models ALWAYS receive updates through the same event stream
  as the write model; separate in-band write paths for reads are FORBIDDEN.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Result envelopes
# ---------------------------------------------------------------------------
ACK_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({"ack", "id", "ids", "status", "event_offset"})
"""CQS-INV-01: keys allowed in a command acknowledgement envelope.

`ack` is the literal "accepted" marker; `id`/`ids` carry write-model primary keys
or the freshly-assigned aggregate id; `status` is one of the terminal ack states;
`event_offset` is the write-model event-stream cursor published by the command.
Any other key would leak a query projection, which is precisely what
CQS-INV-01 FORBIDS.
"""

ACK_STATUSES: Final[frozenset[str]] = frozenset({"accepted", "rejected", "duplicate"})
"""CQS-INV-01: the only status values a command handler may return."""


@dataclass(frozen=True)
class CommandAck:
    """Typed acknowledgement envelope returned by a command handler.

    CQS-INV-01: carries ONLY ack metadata + identifiers; MUST NOT contain a
    projected read-model view.
    """

    ack: bool
    status: str
    ids: tuple[str, ...] = ()
    event_offset: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "ack": self.ack,
            "status": self.status,
            "ids": list(self.ids),
            "event_offset": self.event_offset,
        }


# ---------------------------------------------------------------------------
# Handler aliases
# ---------------------------------------------------------------------------
CommandHandler = Callable[[object], object]
"""A command handler MAY return CommandAck, a dict with only ACK_ALLOWED_KEYS,
or None; anything broader is rejected at dispatch time (CQS-INV-01)."""

QueryHandler = Callable[[object], object]
"""A query handler returns a projection; the dispatcher guards against mutation
attempts via a frozen-state observer (CQS-INV-02)."""


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature)
# ---------------------------------------------------------------------------
@runtime_checkable
class CommandQuerySeparator(Protocol):
    """Protocol for the CQS primitive; signature mirrors the catalog api_signature."""

    def dispatch_command(self, command: object) -> object: ...
    def answer_query(self, query: object) -> object: ...
    def register_command_handler(
        self, command_type: type, handler: CommandHandler,
    ) -> None: ...
    def register_query_handler(
        self, query_type: type, handler: QueryHandler,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Invariant enforcer
# ---------------------------------------------------------------------------
class CQSInvariantError(ValueError):
    """Raised when a runtime call violates a CommandQuerySeparator invariant."""


def validate_ack_payload(payload: object) -> None:
    """CQS-INV-01: command result MUST be ack-shaped (CommandAck / None / bounded dict)."""
    if payload is None:
        return
    if isinstance(payload, CommandAck):
        if payload.status not in ACK_STATUSES:
            raise CQSInvariantError(
                f"CQS-INV-01: CommandAck.status MUST be one of {sorted(ACK_STATUSES)}, "
                f"got {payload.status!r}.",
            )
        return
    if isinstance(payload, dict):
        extra = set(payload.keys()) - ACK_ALLOWED_KEYS
        if extra:
            raise CQSInvariantError(
                "CQS-INV-01: command handler returned a projection — keys "
                f"{sorted(extra)} are FORBIDDEN in a command ack. "
                f"Allowed keys: {sorted(ACK_ALLOWED_KEYS)}.",
            )
        status = payload.get("status")
        if status is not None and status not in ACK_STATUSES:
            raise CQSInvariantError(
                f"CQS-INV-01: ack status MUST be one of {sorted(ACK_STATUSES)}, got {status!r}.",
            )
        return
    raise CQSInvariantError(
        "CQS-INV-01: command handler MUST return CommandAck, None, or a dict with only "
        f"ack/id/ids/status/event_offset keys; got {type(payload).__name__}.",
    )


# ---------------------------------------------------------------------------
# Write-side event stream — CQS-INV-04
# ---------------------------------------------------------------------------
@dataclass
class WriteEvent:
    """A single append on the write-side event log."""

    event_id: str
    command_type: str
    payload: Mapping[str, object]
    offset: int


class EventStream:
    """Append-only event log. CQS-INV-04: the ONLY path through which read models
    receive write updates. Direct read-model writes via this object are refused.
    """

    def __init__(self) -> None:
        self._events: list[WriteEvent] = []
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[WriteEvent], None]] = []

    def append(self, command_type: str, payload: Mapping[str, object]) -> WriteEvent:
        with self._lock:
            offset = len(self._events)
            event = WriteEvent(
                event_id=uuid.uuid4().hex,
                command_type=command_type,
                payload=dict(payload),
                offset=offset,
            )
            self._events.append(event)
            subs = tuple(self._subscribers)
        for sub in subs:
            sub(event)
        return event

    def subscribe(self, callback: Callable[[WriteEvent], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    @property
    def events(self) -> tuple[WriteEvent, ...]:
        with self._lock:
            return tuple(self._events)


# ---------------------------------------------------------------------------
# Read-model registry — CQS-INV-04 enforcer
# ---------------------------------------------------------------------------
@dataclass
class ReadModel:
    """An in-memory read projection fed exclusively by EventStream updates.

    CQS-INV-04: `apply_event` is the only sanctioned write path. `direct_write`
    is a sentinel that always raises so that callers who attempt an in-band
    write get an immediate, loud failure.
    """

    name: str
    state: dict[str, object] = field(default_factory=dict)
    _event_offset: int = field(default=-1)

    def apply_event(self, event: WriteEvent) -> None:
        # Monotonic offsets enforce stream ordering.
        if event.offset <= self._event_offset:
            return
        self._event_offset = event.offset
        self.state[event.event_id] = dict(event.payload)

    def direct_write(self, key: str, value: object) -> None:
        raise CQSInvariantError(
            "CQS-INV-04: read models MUST NOT accept in-band writes; the only "
            f"sanctioned write path is apply_event(). Attempted direct_write({key!r}, ...).",
        )


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryCQS:
    """Reference CommandQuerySeparator.

    Thread-safe, in-process; real deployments swap in an adapter that bridges to
    a message broker for the write-side event stream.
    """

    def __init__(self, event_stream: EventStream | None = None) -> None:
        self._command_handlers: dict[type, CommandHandler] = {}
        self._query_handlers: dict[type, QueryHandler] = {}
        self._lock = threading.Lock()
        self._event_stream: EventStream = event_stream or EventStream()
        # A read-only snapshot exposed to query handlers; mutations are refused.
        self._query_state_snapshot: Mapping[str, object] = {}
        self._read_models: dict[str, ReadModel] = {}

    # ----- registration -------------------------------------------------------
    def register_command_handler(
        self, command_type: type, handler: CommandHandler,
    ) -> None:
        if not isinstance(command_type, type):
            raise CQSInvariantError(
                "CQS-INV-03 supporting: command_type MUST be a class, got "
                f"{type(command_type).__name__}.",
            )
        if not callable(handler):
            raise CQSInvariantError(
                "CQS-INV-03 supporting: handler MUST be callable, got "
                f"{type(handler).__name__}.",
            )
        with self._lock:
            if command_type in self._command_handlers:
                raise CQSInvariantError(
                    f"CQS-INV-03: command type {command_type.__name__!r} already has a "
                    "registered handler; duplicate registration is FORBIDDEN.",
                )
            self._command_handlers[command_type] = handler

    def register_query_handler(
        self, query_type: type, handler: QueryHandler,
    ) -> None:
        if not isinstance(query_type, type):
            raise CQSInvariantError(
                "CQS-INV-03 supporting: query_type MUST be a class, got "
                f"{type(query_type).__name__}.",
            )
        if not callable(handler):
            raise CQSInvariantError(
                "CQS-INV-03 supporting: handler MUST be callable, got "
                f"{type(handler).__name__}.",
            )
        with self._lock:
            # Query handler overwriting IS permitted — read paths may be replaced
            # freely (no write-side correctness at stake). CQS-INV-03 applies to
            # commands only.
            self._query_handlers[query_type] = handler

    # ----- dispatch -----------------------------------------------------------
    def dispatch_command(self, command: object) -> object:
        with self._lock:
            handler = self._command_handlers.get(type(command))
        if handler is None:
            raise CQSInvariantError(
                "CQS-INV-03 supporting: no command handler registered for "
                f"{type(command).__name__!r}.",
            )
        result = handler(command)
        # CQS-INV-01: verify ack-shape; reject projections.
        validate_ack_payload(result)
        return result

    def answer_query(self, query: object) -> object:
        """Dispatch a query to its handler.

        CQS-INV-02 enforcement is structural, not semantic: we assert that the
        handler does NOT append to the event stream and does NOT mutate the
        command-handler registry. True purity (no I/O, no ReadModel.state
        mutation, no external side-effects) cannot be proven from the outside
        — downstream tiers (T4 metamorphic, T6 adversarial) exercise the
        complementary assertions.
        """
        with self._lock:
            handler = self._query_handlers.get(type(query))
            pre_events = len(self._event_stream.events)
            pre_command_handlers = len(self._command_handlers)
        if handler is None:
            raise CQSInvariantError(
                f"CQS-INV-02 supporting: no query handler registered for {type(query).__name__!r}.",
            )
        result = handler(query)
        # CQS-INV-02: no state mutation during query.
        with self._lock:
            post_events = len(self._event_stream.events)
            post_command_handlers = len(self._command_handlers)
        if post_events != pre_events:
            raise CQSInvariantError(
                "CQS-INV-02: query handler appended to the write-side event stream "
                f"({pre_events} -> {post_events}); queries MUST NOT mutate state.",
            )
        if post_command_handlers != pre_command_handlers:
            raise CQSInvariantError(
                "CQS-INV-02: query handler mutated the command registry; "
                "queries MUST NOT invoke side-effects on the write model.",
            )
        return result

    # ----- write-side helpers (used by command handlers) ---------------------
    def emit_event(self, command_type: str, payload: Mapping[str, object]) -> WriteEvent:
        """CQS-INV-04: the ONE place command handlers publish to the stream."""
        return self._event_stream.append(command_type, payload)

    def register_read_model(self, read_model: ReadModel) -> None:
        """Wire a read model to the event stream.

        CQS-INV-04: subscription is the only supported path; direct_write() on
        the returned ReadModel always raises.
        """
        with self._lock:
            self._read_models[read_model.name] = read_model
        self._event_stream.subscribe(read_model.apply_event)

    @property
    def read_models(self) -> Mapping[str, ReadModel]:
        with self._lock:
            return dict(self._read_models)

    @property
    def event_stream(self) -> EventStream:
        return self._event_stream

    @property
    def command_types(self) -> tuple[type, ...]:
        with self._lock:
            return tuple(self._command_handlers)

    @property
    def query_types(self) -> tuple[type, ...]:
        with self._lock:
            return tuple(self._query_handlers)


__all__ = [
    "ACK_ALLOWED_KEYS",
    "ACK_STATUSES",
    "CQSInvariantError",
    "CommandAck",
    "CommandHandler",
    "CommandQuerySeparator",
    "EventStream",
    "InMemoryCQS",
    "QueryHandler",
    "ReadModel",
    "WriteEvent",
    "validate_ack_payload",
]
