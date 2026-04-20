"""EventBus primitive — in-process named event publish/subscribe facade.

Implements the catalog Protocol for `obs.EventBus` and installs runtime invariant
checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- EVENTBUS-INV-01: publish() MUST deliver to every matching subscriber
  synchronously (or via a declared executor); delivery order per subscriber
  SHALL be the subscription order.
- EVENTBUS-INV-02: a subscriber that raises MUST NOT abort delivery to the other
  matching subscribers; the error SHALL be reported to the observability sink.
- EVENTBUS-INV-03: the returned unsubscribe callable MUST be idempotent; calling
  it twice cannot remove a different subscription.
- EVENTBUS-INV-04: event names MUST follow a dotted namespace (e.g.
  'sql.active_record'); wildcards use the documented glob-on-segment syntax.
- EVENTBUS-INV-05: payloads MUST be treated as immutable by subscribers;
  mutating a payload to signal another subscriber is FORBIDDEN.
"""

from __future__ import annotations

import contextlib
import re
import threading
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Public type aliases (mirror the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
Subscriber = Callable[[str, Mapping[str, Any]], None]

# ---------------------------------------------------------------------------
# Constants — event-name grammar and pattern syntax
# ---------------------------------------------------------------------------
# Event name: one-or-more dotted segments. Each segment is lowercase letters,
# digits, and underscores, starting with a letter (mirrors ActiveSupport::
# Notifications and Spring Boot application event naming conventions).
_EVENT_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)
# Pattern grammar:
#   * matches a single segment (one dot-separated token)
#   ** matches one or more trailing segments
#   literal segment matches exactly
# Examples: 'sql.*' matches 'sql.query' but not 'sql.query.slow';
#           'sql.**' matches 'sql.query' and 'sql.query.slow';
#           '*.active_record' matches 'sql.active_record' only.
_PATTERN_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\*\*|\*|[a-z][a-z0-9_]*)$"
)

MAX_TOTAL_SUBSCRIBERS: Final[int] = 10_000


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class EventBus(Protocol):
    def publish(self, name: str, payload: Mapping[str, Any]) -> None: ...
    def subscribe(self, pattern: str, handler: Subscriber) -> Callable[[], None]: ...


# ---------------------------------------------------------------------------
# Runtime invariant enforcers
# ---------------------------------------------------------------------------
class EventBusInvariantError(ValueError):
    """Raised when a runtime call violates an EventBus invariant."""


def validate_event_name(name: str) -> str:
    """EVENTBUS-INV-04: names MUST be dotted-namespace lowercase tokens."""
    if not isinstance(name, str) or not name:
        raise EventBusInvariantError(
            "EVENTBUS-INV-04: event name MUST be a non-empty str."
        )
    if not _EVENT_NAME_RE.match(name):
        raise EventBusInvariantError(
            f"EVENTBUS-INV-04: event name {name!r} MUST match dotted namespace "
            f"(letters, digits, underscores; at least one dot, e.g. 'sql.query')."
        )
    return name


def validate_pattern(pattern: str) -> str:
    """EVENTBUS-INV-04: patterns MUST use the documented glob-on-segment syntax."""
    if not isinstance(pattern, str) or not pattern:
        raise EventBusInvariantError(
            "EVENTBUS-INV-04: pattern MUST be a non-empty str."
        )
    segments = pattern.split(".")
    if len(segments) < 1:
        raise EventBusInvariantError(
            f"EVENTBUS-INV-04: pattern {pattern!r} MUST have at least one segment."
        )
    for seg in segments:
        if not _PATTERN_SEGMENT_RE.match(seg):
            raise EventBusInvariantError(
                f"EVENTBUS-INV-04: pattern {pattern!r} has invalid segment {seg!r}; "
                f"segments MUST be '*', '**', or [a-z][a-z0-9_]*."
            )
    # '**' may only appear as the last segment.
    for i, seg in enumerate(segments):
        if seg == "**" and i != len(segments) - 1:
            raise EventBusInvariantError(
                f"EVENTBUS-INV-04: pattern {pattern!r} — '**' is only allowed as "
                f"the final segment."
            )
    return pattern


def pattern_matches(pattern: str, name: str) -> bool:
    """Return True iff ``name`` is matched by ``pattern`` per the documented grammar."""
    p_segs = pattern.split(".")
    n_segs = name.split(".")
    # Handle trailing '**'
    if p_segs[-1] == "**":
        head = p_segs[:-1]
        if len(n_segs) < len(head) + 1:
            return False
        return all(
            a in ("*", b) for a, b in zip(head, n_segs[: len(head)], strict=False)
        )
    if len(p_segs) != len(n_segs):
        return False
    return all(a in ("*", b) for a, b in zip(p_segs, n_segs, strict=True))


def validate_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """EVENTBUS-INV-05: payload MUST be a Mapping; delivered as a read-only view."""
    if not isinstance(payload, Mapping):
        raise EventBusInvariantError(
            "EVENTBUS-INV-05: payload MUST be a Mapping[str, Any]."
        )
    return payload


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class _Subscription:
    """A single subscription record.

    Holds the pattern, handler, insertion order, and an `active` flag used to
    guarantee unsubscribe idempotency (EVENTBUS-INV-03) without removing a
    different subscription on a second call.
    """

    __slots__ = ("active", "handler", "order", "pattern")

    def __init__(self, pattern: str, handler: Subscriber, order: int) -> None:
        self.pattern: str = pattern
        self.handler: Subscriber = handler
        self.order: int = order
        self.active: bool = True


class InMemoryEventBus:
    """Reference EventBus implementation.

    Stateless from the caller's perspective — the bus is a dep, not a singleton.
    Subscriber bookkeeping is internal and scoped to the instance; discarding
    the instance discards the subscriptions.
    """

    def __init__(
        self,
        *,
        error_sink: Callable[[str, BaseException, Mapping[str, Any]], None] | None = None,
    ) -> None:
        self._subs: list[_Subscription] = []
        self._lock = threading.Lock()
        self._order_counter: int = 0
        self._error_sink: Callable[[str, BaseException, Mapping[str, Any]], None] | None = (
            error_sink
        )
        self._errors: list[tuple[str, str, str]] = []  # (event_name, exc_type, message)
        self._publish_calls: int = 0
        self._delivered_calls: int = 0

    # ----- catalog API --------------------------------------------------------
    def publish(self, name: str, payload: Mapping[str, Any]) -> None:
        """EVENTBUS-INV-01/02/05: synchronous fan-out, insertion order,
        exception isolation, and immutable-view payload delivery."""
        validate_event_name(name)
        validate_payload(payload)

        # Snapshot matching subscribers under the lock so concurrent
        # subscribe/unsubscribe cannot mutate the dispatch list mid-iteration.
        with self._lock:
            self._publish_calls += 1
            matching = [s for s in self._subs if s.active and pattern_matches(s.pattern, name)]
            # EVENTBUS-INV-01: stable insertion order.
            matching.sort(key=lambda s: s.order)

        # EVENTBUS-INV-05: wrap the payload in a read-only view before delivery.
        frozen: Mapping[str, Any] = MappingProxyType(dict(payload))

        for sub in matching:
            self._dispatch_one(sub, name, frozen)

    def _dispatch_one(
        self,
        sub: _Subscription,
        name: str,
        frozen: Mapping[str, Any],
    ) -> None:
        """Dispatch one subscriber with EVENTBUS-INV-02 exception isolation.

        Extracted so the per-iteration try/except does not sit in the hot
        publish() loop body (ruff PERF203) and so the sink swallow is a
        contextlib.suppress (ruff SIM105).
        """
        try:
            sub.handler(name, frozen)
        except BaseException as exc:  # noqa: BLE001 — EVENTBUS-INV-02 isolation mandates catch-all
            self._errors.append((name, type(exc).__name__, str(exc)))
            if self._error_sink is not None:
                # EVENTBUS-INV-02 supporting: a broken sink MUST NOT break delivery.
                with contextlib.suppress(BaseException):
                    self._error_sink(name, exc, frozen)
        else:
            self._delivered_calls += 1

    def subscribe(self, pattern: str, handler: Subscriber) -> Callable[[], None]:
        """EVENTBUS-INV-03/04: validated pattern + idempotent unsubscribe."""
        validate_pattern(pattern)
        if not callable(handler):
            raise EventBusInvariantError(
                "EVENTBUS-INV-01 supporting: handler MUST be callable."
            )
        with self._lock:
            if len(self._subs) >= MAX_TOTAL_SUBSCRIBERS:
                raise EventBusInvariantError(
                    f"EVENTBUS-INV-01 supporting: subscription cap "
                    f"{MAX_TOTAL_SUBSCRIBERS} reached."
                )
            order = self._order_counter
            self._order_counter += 1
            sub = _Subscription(pattern=pattern, handler=handler, order=order)
            self._subs.append(sub)

        def _unsubscribe() -> None:
            # EVENTBUS-INV-03: idempotent. Flipping active=False twice is a no-op,
            # and since we key on THIS subscription object, no other subscription
            # can be removed by a second call.
            with self._lock:
                sub.active = False

        return _unsubscribe

    # ----- observability hooks -----------------------------------------------
    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._subs if s.active)

    @property
    def publish_calls(self) -> int:
        return self._publish_calls

    @property
    def delivered_calls(self) -> int:
        return self._delivered_calls

    @property
    def errors(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(self._errors)


__all__ = [
    "MAX_TOTAL_SUBSCRIBERS",
    "EventBus",
    "EventBusInvariantError",
    "InMemoryEventBus",
    "Subscriber",
    "pattern_matches",
    "validate_event_name",
    "validate_pattern",
    "validate_payload",
]
