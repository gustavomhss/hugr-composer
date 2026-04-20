"""Metamorphic + differential tests for RequestGuard.

Algebraic laws checked here:
- AND is commutative w.r.t. outcome (order changes short-circuit trace, not verdict).
- Adding a guard that always allows NEVER changes the composed verdict.
- Adding a guard that always denies ALWAYS produces DENY (absorbing element).
- Single-guard composite matches the underlying guard's verdict exactly.
- Anonymous → any non-AuthenticatedGuard composition that denies SHALL map to 401.
"""

from __future__ import annotations

from typing import Any

from CurrentPrincipal import anonymous, authenticated
from RequestContext import MutableRequestContext
from RequestGuard import (
    AuthenticatedGuard,
    GuardOutcome,
    RoleGuard,
    TenantGuard,
    and_guards,
    run_sync,
)


def _ctx() -> MutableRequestContext:
    return MutableRequestContext("req-meta0001", {}, assigns={})


class _AlwaysAllow:
    async def allow(self, ctx: Any, principal: Any) -> bool:
        return True


class _AlwaysDeny:
    async def allow(self, ctx: Any, principal: Any) -> bool:
        return False


# ---------------------------------------------------------------------------
def test_metamorphic_and_is_commutative_in_verdict() -> None:
    p = authenticated("alice", tenant_id="acme", roles=["admin"])
    comp_ab = and_guards(RoleGuard("admin"), TenantGuard("acme"))
    comp_ba = and_guards(TenantGuard("acme"), RoleGuard("admin"))
    assert run_sync(comp_ab.evaluate(_ctx(), p)) is GuardOutcome.ALLOW
    assert run_sync(comp_ba.evaluate(_ctx(), p)) is GuardOutcome.ALLOW


def test_metamorphic_always_allow_is_identity() -> None:
    p = authenticated("alice", roles=["admin"])
    base = and_guards(RoleGuard("admin"))
    extended = and_guards(_AlwaysAllow(), RoleGuard("admin"), _AlwaysAllow())
    v1 = run_sync(base.evaluate(_ctx(), p))
    v2 = run_sync(extended.evaluate(_ctx(), p))
    assert v1 is v2


def test_metamorphic_always_deny_is_absorbing() -> None:
    # Adding AlwaysDeny anywhere in the chain forces DENY.
    p = authenticated("alice", roles=["admin"])
    comp_a = and_guards(_AlwaysDeny(), RoleGuard("admin"))
    comp_b = and_guards(RoleGuard("admin"), _AlwaysDeny())
    assert run_sync(comp_a.evaluate(_ctx(), p)) is GuardOutcome.DENY_FORBIDDEN
    assert run_sync(comp_b.evaluate(_ctx(), p)) is GuardOutcome.DENY_FORBIDDEN


def test_metamorphic_single_guard_matches_underlying() -> None:
    # CompositeGuard([g]) verdict equals g.allow's bool (allow vs deny only).
    p_ok = authenticated("alice", roles=["admin"])
    p_no = authenticated("bob", roles=["user"])
    assert run_sync(and_guards(RoleGuard("admin")).evaluate(_ctx(), p_ok)) is GuardOutcome.ALLOW
    assert run_sync(and_guards(RoleGuard("admin")).evaluate(_ctx(), p_no)) is GuardOutcome.DENY_FORBIDDEN


def test_differential_anonymous_denial_maps_to_401_across_any_guard() -> None:
    # Anonymous principal + any deny → 401 (DENY_UNAUTHENTICATED).
    for guard in (AuthenticatedGuard(), RoleGuard("admin"), TenantGuard("acme")):
        outcome = run_sync(and_guards(guard).evaluate(_ctx(), anonymous()))
        assert outcome is GuardOutcome.DENY_UNAUTHENTICATED


def test_differential_authenticated_denial_maps_to_403() -> None:
    # Authenticated principal that fails → 403 (DENY_FORBIDDEN).
    p = authenticated("bob", roles=["user"])
    outcome = run_sync(and_guards(RoleGuard("admin")).evaluate(_ctx(), p))
    assert outcome is GuardOutcome.DENY_FORBIDDEN


def test_metamorphic_evaluated_count_equals_prefix_length_before_first_deny() -> None:
    # Short-circuit property: number of invoked guards equals index-of-first-deny + 1.
    comp = and_guards(_AlwaysAllow(), _AlwaysAllow(), _AlwaysDeny(), _AlwaysAllow())
    run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.evaluated_count == 3
    assert comp.denying_guard_index == 2
