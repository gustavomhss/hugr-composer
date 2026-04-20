"""TimeoutBudget primitive — hierarchical deadline with monotonic-clock budget propagation.

Implements the catalog Protocol for `resiliency.TimeoutBudget` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- TB-INV-01: every outbound call MUST use ``min(local_timeout, remaining_ms())``
  and NEVER the local timeout alone. ``for_call`` returns that minimum; callers
  that bypass the helper SHALL be caught by the observability / review contract.
- TB-INV-02: the deadline MUST be measured on a monotonic clock; the budget
  SHALL NOT move backward on wall-clock jumps. The reference implementation
  reads ``time.monotonic_ns()`` exclusively.
- TB-INV-03: a call issued when ``remaining_ms`` is not positive SHALL be
  refused before any socket I/O begins. ``for_call`` raises
  ``TimeoutBudgetExpired`` and the ``guarded_call`` helper NEVER dispatches.
- TB-INV-04: the budget CANNOT be extended inside the request scope; extensions
  are FORBIDDEN without a new request boundary. ``derive`` can only SHRINK or
  equal the parent budget; attempts to widen raise ``TimeoutBudgetInvariantError``.
- TB-INV-05: the budget SHALL be propagated across task boundaries via the
  ``CURRENT_BUDGET`` context variable, NEVER via thread-local state. ``bind``
  uses ``contextvars`` and MUST be used inside ``asyncio.Task`` / thread hops.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Nanosecond / millisecond helpers — monotonic only (TB-INV-02)
# ---------------------------------------------------------------------------
_NS_PER_MS: Final[int] = 1_000_000


def _monotonic_ns() -> int:
    """Return the current monotonic clock reading in nanoseconds.

    Encapsulated so tests may patch-under-mock a frozen clock without
    touching ``time.monotonic_ns`` globally.
    """
    return int(time.monotonic_ns())


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------
class TimeoutBudgetInvariantError(RuntimeError):
    """Raised when a TimeoutBudget invariant is violated at runtime."""


class TimeoutBudgetExpired(TimeoutBudgetInvariantError):  # noqa: N818 — TB-INV-03: the exception NAME is part of the catalog-visible API surface; callers pattern-match on `TimeoutBudgetExpired` as a short-circuit signal distinct from a generic Error.
    """Raised by ``for_call`` when no budget remains (TB-INV-03).

    Dedicated subclass so callers can distinguish an expired-budget short
    circuit from a catalog-conformance invariant breach.
    """


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class TimeoutBudget(Protocol):
    """Hierarchical monotonic deadline attached to an inbound request.

    The Protocol matches the catalog ``api_signature`` byte-for-byte:
    ``deadline_ns: int``, ``origin: str``, and three methods.
    """

    deadline_ns: int
    origin: str

    def remaining_ms(self) -> int: ...

    def for_call(self, max_ms: int) -> int: ...

    def expired(self) -> bool: ...


# ---------------------------------------------------------------------------
# Reference implementation — frozen, monotonic-only
# ---------------------------------------------------------------------------
class MonotonicTimeoutBudget:
    """Reference TimeoutBudget bound to the monotonic clock.

    Construction freezes the deadline; the value cannot be mutated post-init.
    ``derive`` produces a strictly-not-wider child budget (TB-INV-04).
    """

    __slots__ = ("_frozen", "_parent_deadline_ns", "deadline_ns", "origin")

    deadline_ns: int
    origin: str
    _parent_deadline_ns: int | None
    _frozen: bool

    def __init__(
        self,
        deadline_ns: int,
        origin: str,
        *,
        parent_deadline_ns: int | None = None,
    ) -> None:
        if not isinstance(deadline_ns, int):
            raise TimeoutBudgetInvariantError(
                "TB-INV-02: deadline_ns MUST be an int measured on the monotonic "
                f"clock (nanoseconds); got {type(deadline_ns).__name__}."
            )
        if not isinstance(origin, str) or origin == "":
            raise TimeoutBudgetInvariantError(
                "TB-INV-05: origin MUST be a non-empty str identifying the "
                "inbound request boundary; it is propagated across task hops."
            )
        if parent_deadline_ns is not None and deadline_ns > parent_deadline_ns:
            raise TimeoutBudgetInvariantError(
                "TB-INV-04: derived budget CANNOT exceed the parent's deadline; "
                f"parent={parent_deadline_ns} ns, requested={deadline_ns} ns."
            )
        # Normal assignment during init; _frozen gates further writes below.
        super().__setattr__("deadline_ns", deadline_ns)
        super().__setattr__("origin", origin)
        super().__setattr__("_parent_deadline_ns", parent_deadline_ns)
        super().__setattr__("_frozen", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            # TB-INV-04: budgets are immutable once frozen — extensions FORBIDDEN.
            raise TimeoutBudgetInvariantError(
                "TB-INV-04: TimeoutBudget is immutable; open a fresh budget at "
                f"the next request boundary (attempted to set {name!r})."
            )
        super().__setattr__(name, value)

    # ------ core API --------------------------------------------------------
    def remaining_ms(self) -> int:
        """Remaining budget in whole milliseconds, clamped to ≥ 0.

        Reads the monotonic clock; a wall-clock jump CANNOT shrink the remainder
        below what the monotonic clock reports (TB-INV-02).
        """
        delta_ns = self.deadline_ns - _monotonic_ns()
        if delta_ns <= 0:
            return 0
        return delta_ns // _NS_PER_MS

    def for_call(self, max_ms: int) -> int:
        """Return ``min(max_ms, remaining_ms())``; raise if no budget remains.

        TB-INV-01: callers MUST pass the return value as the outbound timeout.
        TB-INV-03: a non-positive remainder refuses the call BEFORE any socket
        I/O begins — the raised ``TimeoutBudgetExpired`` is the short-circuit.
        """
        if not isinstance(max_ms, int):
            raise TimeoutBudgetInvariantError(
                "TB-INV-01: for_call(max_ms) requires an int; "
                f"got {type(max_ms).__name__}."
            )
        if max_ms <= 0:
            raise TimeoutBudgetInvariantError(
                "TB-INV-01: local timeout MUST be positive; "
                f"got max_ms={max_ms}."
            )
        remaining = self.remaining_ms()
        if remaining <= 0:
            raise TimeoutBudgetExpired(
                "TB-INV-03: TimeoutBudget expired before outbound call "
                f"(origin={self.origin!r}); refusing to dispatch."
            )
        return min(max_ms, remaining)

    def expired(self) -> bool:
        """True when ``remaining_ms() <= 0``. Monotonic clock (TB-INV-02)."""
        return self.remaining_ms() <= 0

    # ------ hierarchical derivation (TB-INV-04) ------------------------------
    def derive(self, *, child_max_ms: int) -> MonotonicTimeoutBudget:
        """Return a child budget whose deadline ≤ ``self.deadline_ns``.

        The child's absolute deadline is ``min(self.deadline_ns, now_ns +
        child_max_ms * NS_PER_MS)`` so a child SHALL NEVER outlive its parent
        (TB-INV-04 — monotonic decrease, never renewed).
        """
        if not isinstance(child_max_ms, int) or child_max_ms <= 0:
            raise TimeoutBudgetInvariantError(
                "TB-INV-04: child_max_ms MUST be a positive int; "
                f"got {child_max_ms!r}."
            )
        proposed = _monotonic_ns() + child_max_ms * _NS_PER_MS
        child_deadline = min(self.deadline_ns, proposed)
        return MonotonicTimeoutBudget(
            deadline_ns=child_deadline,
            origin=self.origin,
            parent_deadline_ns=self.deadline_ns,
        )

    # ------ ergonomic factories ---------------------------------------------
    @classmethod
    def from_ms(cls, total_ms: int, origin: str) -> MonotonicTimeoutBudget:
        """Open a root budget valid for ``total_ms`` from now."""
        if not isinstance(total_ms, int) or total_ms <= 0:
            raise TimeoutBudgetInvariantError(
                "TB-INV-02: root budget MUST be a positive int in ms; "
                f"got {total_ms!r}."
            )
        deadline = _monotonic_ns() + total_ms * _NS_PER_MS
        return cls(deadline_ns=deadline, origin=origin, parent_deadline_ns=None)


# ---------------------------------------------------------------------------
# Context-variable propagation (TB-INV-05)
# ---------------------------------------------------------------------------
CURRENT_BUDGET: ContextVar[TimeoutBudget | None] = ContextVar(
    "current_budget", default=None,
)


@contextmanager
def bind(budget: TimeoutBudget) -> Iterator[TimeoutBudget]:
    """Bind ``budget`` as the current budget for the duration of the block.

    TB-INV-05: propagation MUST use ``contextvars`` so asyncio tasks and
    threads inherit the correct budget automatically. Thread-local state is
    FORBIDDEN here; see rationale inline.
    """
    token: Token[TimeoutBudget | None] = CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        CURRENT_BUDGET.reset(token)


def current() -> TimeoutBudget:
    """Return the currently bound budget or raise if none is in scope.

    TB-INV-05: a call site without an ambient budget is a contract violation —
    we refuse to default to "no deadline" which would silently disable the
    cascading-failure safeguard.
    """
    b = CURRENT_BUDGET.get()
    if b is None:
        raise TimeoutBudgetInvariantError(
            "TB-INV-05: no TimeoutBudget bound in the current context; "
            "ingress middleware MUST open one at the request boundary."
        )
    return b


# ---------------------------------------------------------------------------
# Propagation adapters — the extension surface downstream clients wire up
# ---------------------------------------------------------------------------
class DeadlineHeaderCodec:
    """Encode / decode a remaining-budget header (e.g. ``X-Deadline-Ms``).

    Symmetric codec used by HTTP / gRPC transport middlewares. The encoder
    reads ``budget.remaining_ms()`` at emit time so the propagated budget
    SHRINKS with each hop (TB-INV-04 — monotonic decrease, never renewed).
    """

    HEADER_NAME: Final[str] = "X-Deadline-Ms"

    @classmethod
    def encode(cls, budget: TimeoutBudget) -> str:
        remaining = budget.remaining_ms()
        if remaining <= 0:
            raise TimeoutBudgetExpired(
                "TB-INV-03: refusing to emit an expired deadline header; "
                f"origin={budget.origin!r}."
            )
        return str(remaining)

    @classmethod
    def decode(cls, header_value: str, origin: str) -> MonotonicTimeoutBudget:
        """Reconstruct a budget from an inbound deadline header."""
        if not isinstance(header_value, str):
            raise TimeoutBudgetInvariantError(
                "TB-INV-05: deadline header value MUST be a str; "
                f"got {type(header_value).__name__}."
            )
        try:
            ms = int(header_value.strip())
        except ValueError as exc:
            raise TimeoutBudgetInvariantError(
                "TB-INV-05: deadline header MUST be an integer number of "
                f"milliseconds; got {header_value!r}."
            ) from exc
        if ms <= 0:
            raise TimeoutBudgetExpired(
                "TB-INV-03: inbound deadline header already ≤ 0 ms; "
                f"origin={origin!r}."
            )
        return MonotonicTimeoutBudget.from_ms(total_ms=ms, origin=origin)


# ---------------------------------------------------------------------------
# Guarded dispatcher — proves TB-INV-01 / TB-INV-03 at the transport boundary
# ---------------------------------------------------------------------------
class GuardedCall:
    """Records the timeout that would be used and refuses expired dispatches.

    Tests use this helper as a mock transport: every call path that would touch
    a socket goes through ``dispatch`` so we can assert TB-INV-01 (never local
    alone) and TB-INV-03 (no dispatch when expired) at runtime.
    """

    __slots__ = ("_dispatches", "_lock", "_refused")

    _dispatches: list[tuple[str, int]]
    _refused: int
    _lock: threading.Lock

    def __init__(self) -> None:
        self._dispatches = []
        self._refused = 0
        # Lock guards the refused-counter increment so chaos tests can assert
        # the total without losing increments under thread races.
        self._lock = threading.Lock()

    @property
    def dispatches(self) -> tuple[tuple[str, int], ...]:
        return tuple(self._dispatches)

    @property
    def refused(self) -> int:
        return self._refused

    def dispatch(
        self,
        budget: TimeoutBudget,
        endpoint: str,
        local_timeout_ms: int,
    ) -> int:
        """Return the effective timeout passed to the transport or raise.

        TB-INV-01: effective = ``budget.for_call(local_timeout_ms)`` which is
        already ``min(local, remaining)`` — passing ``local_timeout_ms`` alone
        would be a contract breach.
        """
        try:
            effective = budget.for_call(local_timeout_ms)
        except TimeoutBudgetExpired:
            # TB-INV-03: count the refusal; DO NOT touch the socket.
            with self._lock:
                self._dispatches.append((endpoint, -1))  # -1 marks a refused call
                self._refused += 1
            raise
        with self._lock:
            self._dispatches.append((endpoint, effective))
        return effective


__all__ = [
    "CURRENT_BUDGET",
    "DeadlineHeaderCodec",
    "GuardedCall",
    "MonotonicTimeoutBudget",
    "TimeoutBudget",
    "TimeoutBudgetExpired",
    "TimeoutBudgetInvariantError",
    "bind",
    "current",
]
