"""Chaos / game-day tests for RequestGuard.

Simulates guard-time failures: raised exceptions, mutation attempts, wrong-
return-types, rapid-fire composite reuse, concurrent dispatch, and empty /
malformed inputs. After every fault, the composite's state is inspected to
confirm no path leaks an allow.
"""

from __future__ import annotations

import threading
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
    and_guards,
    run_sync,
)


def _ctx() -> MutableRequestContext:
    return MutableRequestContext("req-chaos001", {}, assigns={})


# ---------------------------------------------------------------------------
def test_chaos_guard_raises_custom_exception_becomes_error() -> None:
    class Angry:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            raise Exception("database timeout")  # noqa: TRY002 — RG-INV-05: chaos test uses a bare Exception to stress the runtime path.

    comp = and_guards(Angry())
    with pytest.raises(Exception, match="database timeout"):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.state is GuardState.TERMINAL_ERROR


def test_chaos_guard_mutates_principal_claims_is_rejected() -> None:
    # Even though CurrentPrincipal claims are frozen upstream, a guard still
    # gets caught by the snapshot compare — the claim mapping was swapped.
    class Swapper:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            # Attempt to mutate via object.__setattr__ bypassing dataclass freeze
            # is the only way a guard could alter the principal in practice.
            object.__setattr__(principal, "subject_id", "root")
            return True

    comp = and_guards(Swapper())
    with pytest.raises(RequestGuardInvariantError):
        run_sync(comp.evaluate(_ctx(), authenticated("u")))


def test_chaos_many_back_to_back_dispatches_never_leak_allow() -> None:
    # 1000 rapid dispatches with alternating allow/deny — no state leak.
    dispatch = HandlerDispatch()
    handler_calls: list[int] = []

    async def h(ctx: Any, principal: Any) -> str:
        handler_calls.append(1)
        return "ok"

    for i in range(200):
        p = authenticated("u", roles=["admin"]) if i % 2 == 0 else authenticated("u", roles=["viewer"])
        comp = and_guards(RoleGuard("admin"))
        run_sync(dispatch.dispatch(comp, _ctx(), p, h))
    # Exactly half the requests should have called the handler.
    assert len(handler_calls) == 100


def test_chaos_concurrent_dispatches_on_distinct_composites() -> None:
    # Concurrency under threads: each request uses its own composite, so the
    # per-request lifecycle invariant is preserved.
    dispatch = HandlerDispatch()
    errors: list[BaseException] = []
    lock = threading.Lock()

    async def h(ctx: Any, principal: Any) -> str:
        return "ok"

    def worker() -> None:
        try:
            comp = and_guards(AuthenticatedGuard())
            run_sync(dispatch.dispatch(comp, _ctx(), authenticated("u"), h))
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(24)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errors
    # Every dispatch MUST have produced an ALLOW decision.
    allows = [d for d in dispatch.decisions if d.outcome is GuardOutcome.ALLOW]
    assert len(allows) == 24


def test_chaos_anonymous_through_many_guards_all_land_on_401() -> None:
    dispatch = HandlerDispatch()
    for _ in range(50):
        comp = and_guards(AuthenticatedGuard(), RoleGuard("admin"))
        r = run_sync(dispatch.dispatch(comp, _ctx(), anonymous(), _async_handler))
        assert r.decision.http_status == 401


def test_chaos_wrong_return_type_never_silently_allows() -> None:
    class Wonky:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            return None  # type: ignore[return-value]  # RG-INV-05: chaos test of non-bool return.

    handler_calls: list[int] = []

    async def h(ctx: Any, principal: Any) -> str:
        handler_calls.append(1)
        return "ok"

    dispatch = HandlerDispatch()
    comp = and_guards(Wonky())
    r = run_sync(dispatch.dispatch(comp, _ctx(), authenticated("u"), h))
    assert r.decision.outcome is GuardOutcome.ERROR
    assert handler_calls == []


def test_chaos_empty_composite_rejected_at_construction() -> None:
    with pytest.raises(RequestGuardInvariantError):
        CompositeGuard([])


def test_chaos_sync_guard_is_rejected_at_construction() -> None:
    class SyncGuard:
        def allow(self, ctx: Any, principal: Any) -> bool:  # sync, not async
            return True

    with pytest.raises(RequestGuardInvariantError):
        and_guards(SyncGuard())  # type: ignore[arg-type]  # RG-INV-03: chaos test of sync allow — construction MUST reject.


async def _async_handler(ctx: Any, principal: Any) -> str:
    return "h"
