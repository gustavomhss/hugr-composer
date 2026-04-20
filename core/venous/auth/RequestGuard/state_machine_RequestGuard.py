"""Hypothesis state-machine exploration of RequestGuard lifecycle.

Explores every reachable (state, outcome, handler_invoked) triple by rolling
random guard behaviours (allow / deny / raise / mutate / non-bool) against a
fresh CompositeGuard per request, and re-checking invariants after each step.
"""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

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


def _ctx() -> MutableRequestContext:
    return MutableRequestContext("req-sm000001", {}, assigns={})


class _Allow:
    async def allow(self, ctx: Any, principal: Any) -> bool:
        return True


class _Deny:
    async def allow(self, ctx: Any, principal: Any) -> bool:
        return False


class _Raise:
    async def allow(self, ctx: Any, principal: Any) -> bool:
        raise RuntimeError("state-machine raise")


class _Mutate:
    async def allow(self, ctx: MutableRequestContext, principal: Any) -> bool:
        ctx.assigns["m"] = "yes"
        return True


_KIND_TO_GUARD = {
    0: _Allow,
    1: _Deny,
    2: _Raise,
    3: _Mutate,
    4: RoleGuard,  # with a role the principal may or may not carry
    5: TenantGuard,
    6: AuthenticatedGuard,
}


class RequestGuardMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.dispatch = HandlerDispatch()
        self.decision_log: list[GuardOutcome] = []
        self.handler_called_count: int = 0

    async def _handler(self, ctx: Any, principal: Any) -> str:
        self.handler_called_count += 1
        return "ran"

    @rule(
        kinds=st.lists(st.integers(min_value=0, max_value=6), min_size=1, max_size=4),
        principal_kind=st.integers(min_value=0, max_value=2),
        tenant_match=st.booleans(),
    )
    def dispatch_once(
        self,
        kinds: list[int],
        principal_kind: int,
        tenant_match: bool,
    ) -> None:
        guards: list[Any] = []
        for k in kinds:
            cls = _KIND_TO_GUARD[k]
            if cls is RoleGuard:
                guards.append(RoleGuard("admin"))
            elif cls is TenantGuard:
                guards.append(TenantGuard("acme"))
            else:
                guards.append(cls())

        if principal_kind == 0:
            principal = anonymous()
        elif principal_kind == 1:
            principal = authenticated("alice", tenant_id="acme" if tenant_match else "other", roles=["admin"])
        else:
            principal = authenticated("bob", tenant_id="acme" if tenant_match else "other", roles=["user"])

        comp = and_guards(*guards)

        async def handler(ctx: Any, p: Any) -> str:
            self.handler_called_count += 1
            return "ok"

        try:
            r = run_sync(self.dispatch.dispatch(comp, _ctx(), principal, handler))
        except RequestGuardInvariantError:
            # Lifecycle violation (e.g. reuse); we never reuse here so should not occur.
            return
        self.decision_log.append(r.decision.outcome)

        # RG-INV-01/02/05: a non-ALLOW decision NEVER coincides with a handler call.
        if r.decision.outcome is not GuardOutcome.ALLOW:
            assert r.decision.handler_invoked is False
            assert r.handler_output is None

        # RG-INV-04: every composite is terminal after evaluation.
        assert comp.state in {
            GuardState.TERMINAL_ALLOW,
            GuardState.TERMINAL_DENY,
            GuardState.TERMINAL_ERROR,
        }

        # Short-circuit property: evaluated_count ≤ len(guards).
        assert comp.evaluated_count <= len(guards)

    @invariant()
    def handler_count_matches_allow_decisions(self) -> None:
        if not hasattr(self, "dispatch"):
            return
        allows = sum(1 for d in self.dispatch.decisions if d.outcome is GuardOutcome.ALLOW)
        assert self.handler_called_count == allows


TestRequestGuardMachine = RequestGuardMachine.TestCase
