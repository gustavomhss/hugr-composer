"""Behavioral end-to-end scenarios for RequestGuard — proves invariants at runtime."""

from __future__ import annotations

from typing import Any

import pytest

from CurrentPrincipal import anonymous, authenticated
from RequestContext import MutableRequestContext
from RequestGuard import (
    AuthenticatedGuard,
    GuardOutcome,
    GuardState,
    HandlerDispatch,
    RequestGuardInvariantError,
    RoleGuard,
    TenantGuard,
    and_guards,
    run_sync,
)


def _ctx() -> MutableRequestContext:
    return MutableRequestContext("req-bhv12345", {"x-app": "test"}, assigns={})


async def _handler(ctx: MutableRequestContext, principal: Any) -> dict[str, str]:
    return {"subject": principal.subject_id}


# ---------------------------------------------------------------------------
def test_scenario_admin_route_allows_admin_and_blocks_user() -> None:
    dispatch = HandlerDispatch()
    # Separate composites per request: RG-INV-04 forbids reuse.
    comp_admin = and_guards(AuthenticatedGuard(), RoleGuard("admin"))
    comp_user = and_guards(AuthenticatedGuard(), RoleGuard("admin"))

    admin = authenticated("alice", roles=["admin"])
    user = authenticated("bob", roles=["user"])

    r1 = run_sync(dispatch.dispatch(comp_admin, _ctx(), admin, _handler))
    assert r1.decision.handler_invoked is True
    assert r1.decision.outcome is GuardOutcome.ALLOW
    assert r1.handler_output == {"subject": "alice"}

    r2 = run_sync(dispatch.dispatch(comp_user, _ctx(), user, _handler))
    assert r2.decision.handler_invoked is False
    assert r2.decision.http_status == 403


def test_scenario_anonymous_gets_401_not_403() -> None:
    dispatch = HandlerDispatch()
    comp = and_guards(AuthenticatedGuard())
    r = run_sync(dispatch.dispatch(comp, _ctx(), anonymous(), _handler))
    assert r.decision.outcome is GuardOutcome.DENY_UNAUTHENTICATED
    assert r.decision.http_status == 401


def test_scenario_tenant_guard_blocks_cross_tenant() -> None:
    dispatch = HandlerDispatch()
    comp = and_guards(TenantGuard("acme"))
    p = authenticated("alice", tenant_id="globex", roles=["admin"])
    r = run_sync(dispatch.dispatch(comp, _ctx(), p, _handler))
    assert r.decision.outcome is GuardOutcome.DENY_FORBIDDEN


def test_scenario_and_chain_short_circuits_on_first_deny() -> None:
    trace: list[int] = []

    class Instrumented:
        def __init__(self, verdict: bool, tag: int) -> None:
            self.verdict = verdict
            self.tag = tag

        async def allow(self, ctx: Any, principal: Any) -> bool:
            trace.append(self.tag)
            return self.verdict

    comp = and_guards(
        Instrumented(True, 1),
        Instrumented(False, 2),
        Instrumented(True, 3),
    )
    run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert trace == [1, 2]  # guard 3 SHALL NOT run


def test_scenario_mutation_is_caught_before_handler() -> None:
    class Mutator:
        async def allow(self, ctx: MutableRequestContext, principal: Any) -> bool:
            ctx.assigns["sneaky"] = "value"
            return True

    handler_ran: list[int] = []

    async def handler(ctx: Any, principal: Any) -> str:
        handler_ran.append(1)
        return "ran"

    dispatch = HandlerDispatch()
    comp = and_guards(Mutator())
    r = run_sync(dispatch.dispatch(comp, _ctx(), authenticated("u"), handler))
    assert r.decision.outcome is GuardOutcome.ERROR
    assert handler_ran == []
    assert r.decision.http_status == 500


def test_scenario_exception_maps_to_500_and_records_type() -> None:
    class Raising:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            raise KeyError("missing-policy")

    dispatch = HandlerDispatch()
    comp = and_guards(Raising())
    r = run_sync(dispatch.dispatch(comp, _ctx(), authenticated("u"), _handler))
    assert r.decision.outcome is GuardOutcome.ERROR
    assert r.decision.http_status == 500
    assert r.decision.error_type == "KeyError"
    assert r.decision.handler_invoked is False


def test_scenario_reuse_after_terminal_is_forbidden() -> None:
    comp = and_guards(AuthenticatedGuard())
    run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.state is GuardState.TERMINAL_ALLOW
    # A second evaluate MUST raise (fresh composite required per request).
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))


def test_scenario_composite_aggregates_three_independent_checks() -> None:
    dispatch = HandlerDispatch()
    comp = and_guards(AuthenticatedGuard(), RoleGuard("billing"), TenantGuard("acme"))
    p = authenticated("alice", tenant_id="acme", roles=["admin", "billing"])
    r = run_sync(dispatch.dispatch(comp, _ctx(), p, _handler))
    assert r.decision.outcome is GuardOutcome.ALLOW
    assert r.handler_output == {"subject": "alice"}
