"""RequestGuard primitive — allow/deny predicate that short-circuits the pipeline.

Implements the catalog Protocol for `auth.RequestGuard` and ships a stateful
CompositeGuard that enforces the full life-cycle contract (OPEN → EVALUATING
→ TERMINAL). The module performs zero I/O at import and does not import its
sibling primitives (`CurrentPrincipal`, `RequestContext`) at module scope —
the catalog Protocol cites them as forward references; duck-typing keeps the
module loadable in isolation (mypy --strict still verifies structural types).

Invariant IDs cited by this module:

- RG-INV-01: a False return from the composed guard evaluation MUST prevent
  the wrapped handler from running and SHALL produce a 401/403 outcome
  (`GuardOutcome.DENY_UNAUTHENTICATED` for anonymous, `DENY_FORBIDDEN`
  otherwise). No handler call path reaches user code after a deny.
- RG-INV-02: a guard MUST NOT mutate the request body nor the principal.
  The runtime checker snapshots `ctx.assigns` + `principal` before evaluation
  and, after every guard call, asserts equality; any drift aborts with
  `RequestGuardInvariantError`.
- RG-INV-03: multiple guards MUST compose with logical AND; a single False
  blocks the request, and a short-circuit SHALL skip remaining guards so a
  denied request never reaches a later guard's side-channel.
- RG-INV-04: guards MUST execute after authentication middleware has bound a
  principal — evaluation on an unbound principal is forbidden — and BEFORE
  the handler runs. A terminal CompositeGuard CANNOT be re-opened; a fresh
  instance is required for the next request.
- RG-INV-05: a guard that raises NEVER gets silently treated as allow;
  exceptions bubble as `GuardOutcome.ERROR` (mapped to HTTP 500 by the
  integration layer) and the CompositeGuard transitions to TERMINAL_ERROR —
  it is FORBIDDEN to swallow the exception or to default to True.
"""

from __future__ import annotations

import asyncio
import copy
import enum
import inspect
import threading
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Life-cycle states (RG-INV-04)
# ---------------------------------------------------------------------------
class GuardState(str, enum.Enum):
    """The CompositeGuard life-cycle — a strictly monotone state machine."""

    OPEN = "open"
    EVALUATING = "evaluating"
    TERMINAL_ALLOW = "terminal_allow"
    TERMINAL_DENY = "terminal_deny"
    TERMINAL_ERROR = "terminal_error"


TERMINAL_STATES: Final[frozenset[GuardState]] = frozenset({
    GuardState.TERMINAL_ALLOW,
    GuardState.TERMINAL_DENY,
    GuardState.TERMINAL_ERROR,
})


# ---------------------------------------------------------------------------
# Outcome taxonomy (RG-INV-01 / RG-INV-05)
# ---------------------------------------------------------------------------
class GuardOutcome(str, enum.Enum):
    """How the error filter MUST translate a guard evaluation.

    - ALLOW → handler runs.
    - DENY_UNAUTHENTICATED → pipeline responds 401 (anonymous principal).
    - DENY_FORBIDDEN → pipeline responds 403 (authenticated but disallowed).
    - ERROR → pipeline responds 500 (guard raised an exception).
    """

    ALLOW = "allow"
    DENY_UNAUTHENTICATED = "deny_unauthenticated"
    DENY_FORBIDDEN = "deny_forbidden"
    ERROR = "error"


HTTP_STATUS_FOR: Final[Mapping[GuardOutcome, int]] = {
    GuardOutcome.ALLOW: 200,
    GuardOutcome.DENY_UNAUTHENTICATED: 401,
    GuardOutcome.DENY_FORBIDDEN: 403,
    GuardOutcome.ERROR: 500,
}


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class RequestGuardInvariantError(RuntimeError):
    """Raised when a guard composition or lifecycle invariant is violated."""


# ---------------------------------------------------------------------------
# Structural protocols for forward-cited catalog types.
#
# The catalog Protocol names `RequestContext` and `CurrentPrincipal`; the
# actual modules are adjacent primitives. We duck-type the bits we need so
# the guard module is runnable in isolation (a `tlc`-only or `mypy-only` run
# does not require those siblings on sys.path).
# ---------------------------------------------------------------------------
class _PrincipalLike(Protocol):
    """Subset of CurrentPrincipal this primitive reads."""

    subject_id: str
    tenant_id: str | None
    roles: frozenset[str]
    claims: Mapping[str, str]
    is_anonymous: bool


class _RequestContextLike(Protocol):
    """Subset of MutableRequestContext this primitive reads."""

    request_id: str
    headers: Mapping[str, str]
    assigns: dict[str, Any]


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class RequestGuard(Protocol):
    """Predicate invoked before a handler to allow or deny a request.

    Implementations return True (allow) or False (deny); raising propagates as
    RG-INV-05 and the composite marks TERMINAL_ERROR. The Protocol matches
    the catalog api_signature byte-for-byte: a single async method `allow`.
    """

    async def allow(
        self,
        ctx: _RequestContextLike,
        principal: _PrincipalLike,
    ) -> bool: ...


# ---------------------------------------------------------------------------
# Reference guards
# ---------------------------------------------------------------------------
class RoleGuard:
    """Admit the principal iff it carries every role in `required`."""

    def __init__(self, *required: str) -> None:
        if not required:
            raise RequestGuardInvariantError(
                "RG-INV-03: RoleGuard requires at least one role; an empty "
                "requirement would silently admit everyone."
            )
        for r in required:
            if not isinstance(r, str) or r == "":
                raise RequestGuardInvariantError(
                    "RG-INV-03: every required role MUST be a non-empty str; "
                    f"got {r!r}."
                )
        self._required: frozenset[str] = frozenset(required)

    @property
    def required(self) -> frozenset[str]:
        return self._required

    async def allow(
        self,
        ctx: _RequestContextLike,
        principal: _PrincipalLike,
    ) -> bool:
        # RG-INV-04: anonymous principals CANNOT satisfy any role requirement.
        if principal.is_anonymous:
            return False
        return self._required.issubset(principal.roles)


class TenantGuard:
    """Admit the principal iff its tenant_id matches the required tenant."""

    def __init__(self, tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or tenant_id == "":
            raise RequestGuardInvariantError(
                "RG-INV-03: TenantGuard requires a non-empty tenant_id."
            )
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    async def allow(
        self,
        ctx: _RequestContextLike,
        principal: _PrincipalLike,
    ) -> bool:
        if principal.is_anonymous:
            return False
        return principal.tenant_id == self._tenant_id


class AuthenticatedGuard:
    """Admit any non-anonymous principal; deny an anonymous principal."""

    async def allow(
        self,
        ctx: _RequestContextLike,
        principal: _PrincipalLike,
    ) -> bool:
        return not principal.is_anonymous


# ---------------------------------------------------------------------------
# Snapshot helpers (RG-INV-02 runtime payload-integrity check)
# ---------------------------------------------------------------------------
def _snapshot(
    ctx: _RequestContextLike,
    principal: _PrincipalLike,
) -> tuple[
    str,
    tuple[tuple[str, str], ...],
    tuple[tuple[str, object], ...],
    str,
    tuple[str, ...],
    str | None,
    tuple[tuple[str, str], ...],
    bool,
]:
    """Return a hashable fingerprint of the (ctx, principal) payload.

    A guard that mutates any visible field will produce a divergent snapshot
    on the post-call comparison, which the checker raises as
    `RequestGuardInvariantError`.
    """
    assigns_items: tuple[tuple[str, object], ...] = tuple(sorted(
        (str(k), copy.deepcopy(v)) for k, v in ctx.assigns.items()
    ))
    headers_items: tuple[tuple[str, str], ...] = tuple(sorted(ctx.headers.items()))
    return (
        ctx.request_id,
        headers_items,
        assigns_items,
        principal.subject_id,
        tuple(sorted(principal.roles)),
        principal.tenant_id,
        tuple(sorted(principal.claims.items())),
        principal.is_anonymous,
    )


def _has_required_shape(obj: object, fields: Sequence[str]) -> bool:
    return all(hasattr(obj, f) for f in fields)


# ---------------------------------------------------------------------------
# CompositeGuard (stateful AND-composer)
# ---------------------------------------------------------------------------
class CompositeGuard:
    """AND-compose ≥1 RequestGuard implementations with short-circuit + lifecycle.

    The composite is stateful: evaluation transitions OPEN → EVALUATING →
    one of {TERMINAL_ALLOW, TERMINAL_DENY, TERMINAL_ERROR}. A terminal
    composite CANNOT be re-evaluated; a fresh instance MUST be opened for the
    next request (RG-INV-04).
    """

    def __init__(self, guards: Sequence[RequestGuard]) -> None:
        materialised = tuple(guards)
        if not materialised:
            raise RequestGuardInvariantError(
                "RG-INV-03: CompositeGuard requires ≥1 guard; an empty "
                "composition would silently admit everyone."
            )
        for g in materialised:
            if not hasattr(g, "allow"):
                raise RequestGuardInvariantError(
                    "RG-INV-03: every guard MUST expose an `allow` coroutine; "
                    f"got {type(g).__name__}."
                )
            if not inspect.iscoroutinefunction(g.allow):
                raise RequestGuardInvariantError(
                    "RG-INV-03: RequestGuard.allow MUST be an async def; "
                    f"{type(g).__name__}.allow is not a coroutine function."
                )
        self._guards: tuple[RequestGuard, ...] = materialised
        self._state: GuardState = GuardState.OPEN
        self._lock = threading.Lock()
        self._evaluated_count: int = 0
        self._outcome: GuardOutcome | None = None
        self._denying_guard_index: int | None = None
        self._error: BaseException | None = None

    # ---- introspection ----------------------------------------------------
    @property
    def state(self) -> GuardState:
        return self._state

    @property
    def outcome(self) -> GuardOutcome | None:
        return self._outcome

    @property
    def evaluated_count(self) -> int:
        """Number of guards that were actually invoked (0..len(guards)).

        When a guard denies, remaining guards MUST be skipped — this counter
        exposes the short-circuit (RG-INV-03).
        """
        return self._evaluated_count

    @property
    def denying_guard_index(self) -> int | None:
        return self._denying_guard_index

    @property
    def guards(self) -> tuple[RequestGuard, ...]:
        return self._guards

    # ---- evaluation -------------------------------------------------------
    async def evaluate(  # noqa: C901 — RG-INV-01/02/03/04/05: five invariants per call, each branch serves a distinct one.
        self,
        ctx: _RequestContextLike,
        principal: _PrincipalLike,
    ) -> GuardOutcome:
        """Run every guard in order; return the composed outcome.

        On deny, remaining guards are SKIPPED (RG-INV-03). On raise, the
        composite transitions to TERMINAL_ERROR and re-raises after recording
        the exception (RG-INV-05).
        """
        if not _has_required_shape(principal, ("is_anonymous", "roles", "subject_id", "claims")):
            # RG-INV-04: evaluation requires a bound principal.
            raise RequestGuardInvariantError(
                "RG-INV-04: CompositeGuard.evaluate requires a principal "
                "with is_anonymous/roles/subject_id/claims fields; "
                f"got {type(principal).__name__}."
            )
        if not _has_required_shape(ctx, ("request_id", "headers", "assigns")):
            raise RequestGuardInvariantError(
                "RG-INV-04: CompositeGuard.evaluate requires a request "
                "context with request_id/headers/assigns fields; "
                f"got {type(ctx).__name__}."
            )

        with self._lock:
            if self._state in TERMINAL_STATES:
                raise RequestGuardInvariantError(
                    f"RG-INV-04: CompositeGuard is {self._state.value}; a fresh "
                    "composite MUST be opened for the next request."
                )
            if self._state is GuardState.EVALUATING:
                raise RequestGuardInvariantError(
                    "RG-INV-04: CompositeGuard.evaluate is not re-entrant; "
                    "one evaluation at a time."
                )
            self._state = GuardState.EVALUATING

        # RG-INV-02: snapshot the payload to detect mutation post-evaluation.
        before = _snapshot(ctx, principal)

        for idx, guard in enumerate(self._guards):
            try:
                verdict = await guard.allow(ctx, principal)
            except BaseException as exc:
                # RG-INV-05: exceptions NEVER become silent allows.
                self._error = exc
                self._outcome = GuardOutcome.ERROR
                self._state = GuardState.TERMINAL_ERROR
                self._evaluated_count = idx + 1
                raise
            # RG-INV-02: re-check the snapshot after every guard call.
            after = _snapshot(ctx, principal)
            if after != before:
                self._outcome = GuardOutcome.ERROR
                self._state = GuardState.TERMINAL_ERROR
                self._evaluated_count = idx + 1
                raise RequestGuardInvariantError(
                    f"RG-INV-02: guard at index {idx} "
                    f"({type(guard).__name__}) mutated the request "
                    "payload (ctx.assigns or principal); guards MUST be "
                    "pure accept/reject predicates."
                )

            self._evaluated_count = idx + 1
            if verdict is True:
                continue
            if verdict is False:
                # RG-INV-01 / RG-INV-03: short-circuit on first deny.
                self._denying_guard_index = idx
                if principal.is_anonymous:
                    self._outcome = GuardOutcome.DENY_UNAUTHENTICATED
                else:
                    self._outcome = GuardOutcome.DENY_FORBIDDEN
                self._state = GuardState.TERMINAL_DENY
                return self._outcome
            # RG-INV-05: a non-bool return is a contract violation — map to ERROR.
            self._outcome = GuardOutcome.ERROR
            self._state = GuardState.TERMINAL_ERROR
            raise RequestGuardInvariantError(
                f"RG-INV-05: guard at index {idx} ({type(guard).__name__}) "
                f"returned a non-bool value {verdict!r}; guards MUST return "
                "True or False."
            )

        # All guards allowed.
        self._outcome = GuardOutcome.ALLOW
        self._state = GuardState.TERMINAL_ALLOW
        return self._outcome


# ---------------------------------------------------------------------------
# Supporting result types (frozen, tiny containers).
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GuardDecision:
    """A recorded decision from `HandlerDispatch.dispatch`.

    Fields are all primitives so the object can be logged verbatim without
    leaking principal claims.
    """

    outcome: GuardOutcome
    http_status: int
    handler_invoked: bool
    denying_guard_index: int | None
    error_type: str | None


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """Return shape of `HandlerDispatch.dispatch`."""

    decision: GuardDecision
    handler_output: object | None


# ---------------------------------------------------------------------------
# Handler type alias (duck-typed to keep imports cheap).
# ---------------------------------------------------------------------------
class HandlerFn(Protocol):
    def __call__(
        self,
        ctx: _RequestContextLike,
        principal: _PrincipalLike,
    ) -> Awaitable[object]: ...


# ---------------------------------------------------------------------------
# Handler dispatcher — proves RG-INV-01 at the pipeline boundary
# ---------------------------------------------------------------------------
class HandlerDispatch:
    """Dispatches a handler only when the CompositeGuard returns ALLOW.

    Records every decision so the pipeline can audit guard rejections. This is
    the integration point that makes RG-INV-01 observable: a False verdict
    SHALL NOT produce a handler invocation.
    """

    def __init__(self) -> None:
        self._decisions: list[GuardDecision] = []

    @property
    def decisions(self) -> tuple[GuardDecision, ...]:
        return tuple(self._decisions)

    async def dispatch(
        self,
        composite: CompositeGuard,
        ctx: _RequestContextLike,
        principal: _PrincipalLike,
        handler: HandlerFn,
    ) -> HandlerResult:
        """Evaluate `composite`; call `handler` iff every guard allowed."""
        try:
            outcome = await composite.evaluate(ctx, principal)
        except BaseException as exc:  # noqa: BLE001 — RG-INV-05: a guard exception MUST be mapped to ERROR; swallowing here would violate the "never silently allow" rule by letting the raise propagate to the handler frame.
            decision = GuardDecision(
                outcome=GuardOutcome.ERROR,
                http_status=HTTP_STATUS_FOR[GuardOutcome.ERROR],
                handler_invoked=False,
                denying_guard_index=None,
                error_type=type(exc).__name__,
            )
            self._decisions.append(decision)
            return HandlerResult(decision=decision, handler_output=None)

        if outcome is not GuardOutcome.ALLOW:
            decision = GuardDecision(
                outcome=outcome,
                http_status=HTTP_STATUS_FOR[outcome],
                handler_invoked=False,
                denying_guard_index=composite.denying_guard_index,
                error_type=None,
            )
            self._decisions.append(decision)
            return HandlerResult(decision=decision, handler_output=None)

        output = await handler(ctx, principal)
        decision = GuardDecision(
            outcome=GuardOutcome.ALLOW,
            http_status=200,
            handler_invoked=True,
            denying_guard_index=None,
            error_type=None,
        )
        self._decisions.append(decision)
        return HandlerResult(decision=decision, handler_output=output)


# ---------------------------------------------------------------------------
# Convenience AND-factory
# ---------------------------------------------------------------------------
def and_guards(*guards: RequestGuard) -> CompositeGuard:
    """Build a CompositeGuard that AND-composes every `guards[i]` in order."""
    return CompositeGuard(list(guards))


# ---------------------------------------------------------------------------
# Fan-out helpers — tests / concurrency harness use these directly.
# ---------------------------------------------------------------------------
def run_sync(coro: Awaitable[object]) -> object:
    """Execute `coro` on a fresh asyncio loop. Test-ergonomic only."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _validate_registration(guards: Iterable[RequestGuard]) -> tuple[RequestGuard, ...]:
    """Validator reused by pipeline-level registries; guards are composed, not replaced."""
    materialised = tuple(guards)
    seen_ids: set[int] = set()
    for g in materialised:
        if id(g) in seen_ids:
            raise RequestGuardInvariantError(
                "RG-INV-03: the same guard instance was registered twice; "
                "composition is a set in intent — pass distinct instances."
            )
        seen_ids.add(id(g))
    return materialised


__all__ = [
    "HTTP_STATUS_FOR",
    "TERMINAL_STATES",
    "AuthenticatedGuard",
    "CompositeGuard",
    "GuardDecision",
    "GuardOutcome",
    "GuardState",
    "HandlerDispatch",
    "HandlerFn",
    "HandlerResult",
    "RequestGuard",
    "RequestGuardInvariantError",
    "RoleGuard",
    "TenantGuard",
    "and_guards",
    "run_sync",
]
