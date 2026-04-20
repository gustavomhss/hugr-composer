"""Unit tests for RequestGuard — 3 per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from typing import Any

import pytest

from CurrentPrincipal import anonymous, authenticated
from RequestContext import MutableRequestContext
from RequestGuard import (
    AuthenticatedGuard,
    CompositeGuard,
    GuardOutcome,
    GuardState,
    HandlerDispatch,
    RequestGuardInvariantError,
    RoleGuard,
    TenantGuard,
    and_guards,
    run_sync,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _ctx(**assigns: Any) -> MutableRequestContext:
    return MutableRequestContext("req-" + "a" * 8, {}, assigns=dict(assigns))


async def _noop_handler(
    ctx: MutableRequestContext,
    principal: Any,
) -> str:
    return "handler-ran"


# ---------------------------------------------------------------------------
# RG_INV_01 — deny blocks the handler; outcome 401/403
# ---------------------------------------------------------------------------
def test_inv_deny_blocks_handler_confirms() -> None:
    dispatch = HandlerDispatch()
    comp = and_guards(RoleGuard("admin"))
    p = authenticated("bob", roles=["user"])

    result = run_sync(dispatch.dispatch(comp, _ctx(), p, _noop_handler))
    assert result.decision.handler_invoked is False
    assert result.decision.outcome is GuardOutcome.DENY_FORBIDDEN
    assert result.decision.http_status == 403
    assert result.handler_output is None


def test_inv_deny_blocks_handler_prevents() -> None:
    # An anonymous request is denied with 401 (DENY_UNAUTHENTICATED).
    dispatch = HandlerDispatch()
    comp = and_guards(AuthenticatedGuard())
    result = run_sync(dispatch.dispatch(comp, _ctx(), anonymous(), _noop_handler))
    assert result.decision.outcome is GuardOutcome.DENY_UNAUTHENTICATED
    assert result.decision.http_status == 401
    assert result.decision.handler_invoked is False


def test_inv_deny_blocks_handler_under_failure() -> None:
    # Even if an inner guard later would allow, first-deny SHALL short-circuit
    # and prevent the handler from ever running.
    handler_calls: list[int] = []

    async def recording_handler(ctx: MutableRequestContext, principal: Any) -> str:
        handler_calls.append(1)
        return "ran"

    dispatch = HandlerDispatch()
    comp = and_guards(RoleGuard("admin"), AuthenticatedGuard())
    p = authenticated("u", roles=["user"])
    for _ in range(5):
        fresh = and_guards(*comp.guards)  # new composite per request (RG-INV-04)
        run_sync(dispatch.dispatch(fresh, _ctx(), p, recording_handler))
    assert handler_calls == []  # handler NEVER invoked under deny


# ---------------------------------------------------------------------------
# RG_INV_02 — guards MUST NOT mutate payload
# ---------------------------------------------------------------------------
def test_inv_no_mutation_confirms() -> None:
    # A well-behaved guard leaves ctx + principal untouched.
    comp = and_guards(RoleGuard("admin"))
    p = authenticated("alice", roles=["admin"])
    ctx = _ctx(x=1)
    before_assigns = dict(ctx.assigns)
    run_sync(comp.evaluate(ctx, p))
    assert ctx.assigns == before_assigns
    assert comp.state is GuardState.TERMINAL_ALLOW


def test_inv_no_mutation_prevents() -> None:
    # A bad guard that mutates ctx.assigns is detected and converted to ERROR.
    class BadGuard:
        async def allow(self, ctx: MutableRequestContext, principal: Any) -> bool:
            ctx.assigns["injected"] = "evil"
            return True

    comp = and_guards(BadGuard())
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.state is GuardState.TERMINAL_ERROR
    assert comp.outcome is GuardOutcome.ERROR


def test_inv_no_mutation_under_failure() -> None:
    # Even when the bad guard sits AFTER a passing guard, the mutation is
    # localised and flagged at the offending index.
    class MutatingGuard:
        async def allow(self, ctx: MutableRequestContext, principal: Any) -> bool:
            ctx.assigns["x"] = "y"
            return True

    comp = and_guards(AuthenticatedGuard(), MutatingGuard())
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.evaluated_count == 2
    assert comp.state is GuardState.TERMINAL_ERROR


# ---------------------------------------------------------------------------
# RG_INV_03 — AND composition, short-circuit on first deny
# ---------------------------------------------------------------------------
def test_inv_and_composition_confirms() -> None:
    # All three guards allow → outcome is ALLOW.
    comp = and_guards(AuthenticatedGuard(), RoleGuard("admin"), TenantGuard("acme"))
    p = authenticated("alice", tenant_id="acme", roles=["admin"])
    outcome = run_sync(comp.evaluate(_ctx(), p))
    assert outcome is GuardOutcome.ALLOW
    assert comp.evaluated_count == 3


def test_inv_and_composition_prevents() -> None:
    # Empty composition is REJECTED (would silently admit everyone).
    with pytest.raises(RequestGuardInvariantError):
        CompositeGuard([])


def test_inv_and_composition_under_failure() -> None:
    # First deny SHALL short-circuit: guards AFTER the denial are not invoked.
    trace: list[str] = []

    class RecordingAllow:
        def __init__(self, name: str) -> None:
            self.name = name

        async def allow(self, ctx: Any, principal: Any) -> bool:
            trace.append(self.name)
            return True

    class RecordingDeny:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            trace.append("deny")
            return False

    comp = and_guards(RecordingAllow("a"), RecordingDeny(), RecordingAllow("b"))
    outcome = run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert outcome is GuardOutcome.DENY_FORBIDDEN
    assert trace == ["a", "deny"]  # "b" NEVER ran
    assert comp.evaluated_count == 2
    assert comp.denying_guard_index == 1


# ---------------------------------------------------------------------------
# RG_INV_04 — lifecycle / no-reuse after terminal
# ---------------------------------------------------------------------------
def test_inv_lifecycle_confirms() -> None:
    # OPEN → EVALUATING → TERMINAL_ALLOW on the happy path.
    comp = and_guards(AuthenticatedGuard())
    assert comp.state is GuardState.OPEN
    run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.state is GuardState.TERMINAL_ALLOW


def test_inv_lifecycle_prevents() -> None:
    # A terminal composite MUST reject re-use.
    comp = and_guards(AuthenticatedGuard())
    run_sync(comp.evaluate(_ctx(), authenticated("u")))
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))


def test_inv_lifecycle_under_failure() -> None:
    # Evaluation with a wrong-shape principal raises; evaluation with a
    # wrong-shape ctx raises. Both are lifecycle / pre-condition violations.
    comp = and_guards(AuthenticatedGuard())
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp.evaluate(_ctx(), object()))  # type: ignore[arg-type]  # RG-INV-04: principal shape check.

    comp2 = and_guards(AuthenticatedGuard())
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp2.evaluate(object(), authenticated("u")))  # type: ignore[arg-type]  # RG-INV-04: ctx shape check.


# ---------------------------------------------------------------------------
# RG_INV_05 — exception NEVER becomes silent allow
# ---------------------------------------------------------------------------
def test_inv_raise_is_error_confirms() -> None:
    # A guard that raises transitions composite → TERMINAL_ERROR and raises.
    class Boom:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            raise RuntimeError("kaboom")

    comp = and_guards(Boom())
    with pytest.raises(RuntimeError, match="kaboom"):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.state is GuardState.TERMINAL_ERROR
    assert comp.outcome is GuardOutcome.ERROR


def test_inv_raise_is_error_prevents() -> None:
    # The HandlerDispatch integration maps raise → 500 and does NOT invoke the handler.
    class Boom:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            raise ValueError("bad")

    dispatch = HandlerDispatch()
    called: list[int] = []

    async def h(ctx: Any, principal: Any) -> str:
        called.append(1)
        return "x"

    result = run_sync(dispatch.dispatch(and_guards(Boom()), _ctx(), authenticated("u"), h))
    assert called == []
    assert result.decision.outcome is GuardOutcome.ERROR
    assert result.decision.http_status == 500
    assert result.decision.error_type == "ValueError"


def test_inv_raise_is_error_under_failure() -> None:
    # A guard returning a non-bool is treated as ERROR (not silent allow).
    class WrongReturn:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            return "yes"  # type: ignore[return-value]  # RG-INV-05: deliberate contract violation for the test.

    comp = and_guards(WrongReturn())
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.state is GuardState.TERMINAL_ERROR
