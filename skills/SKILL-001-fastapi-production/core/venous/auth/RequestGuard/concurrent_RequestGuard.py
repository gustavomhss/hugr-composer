"""Concurrency / linearizability harness for RequestGuard.

Confirms that concurrent dispatches on DISTINCT composites never leak state
across requests, and that re-entering the same terminal composite from any
thread is rejected.
"""

from __future__ import annotations

import threading
from typing import Any

from CurrentPrincipal import authenticated
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
    return MutableRequestContext("req-conc0001", {}, assigns={})


async def _allow_handler(ctx: Any, principal: Any) -> str:
    return "ok"


def test_concurrent_independent_composites_preserve_lifecycle() -> None:
    # 32 threads, each owning its own CompositeGuard, all end in a terminal state.
    dispatch = HandlerDispatch()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            comp = and_guards(AuthenticatedGuard(), RoleGuard("admin"))
            p = authenticated("u", roles=["admin"])
            r = run_sync(dispatch.dispatch(comp, _ctx(), p, _allow_handler))
            assert r.decision.outcome is GuardOutcome.ALLOW
            assert comp.state is GuardState.TERMINAL_ALLOW
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert len(dispatch.decisions) == 32
    assert all(d.outcome is GuardOutcome.ALLOW for d in dispatch.decisions)


def test_concurrent_reuse_of_terminal_composite_is_rejected() -> None:
    # One composite, first caller lands it in TERMINAL_ALLOW; N subsequent
    # callers all get lifecycle rejection — no silent allow leak.
    comp = and_guards(AuthenticatedGuard())
    run_sync(comp.evaluate(_ctx(), authenticated("u")))
    assert comp.state is GuardState.TERMINAL_ALLOW

    rejections: list[int] = []
    successes: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            run_sync(comp.evaluate(_ctx(), authenticated("u")))
            with lock:
                successes.append(1)
        except RequestGuardInvariantError:
            with lock:
                rejections.append(1)

    ts = [threading.Thread(target=worker) for _ in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert successes == []
    assert len(rejections) == 16


def test_concurrent_mix_allow_and_deny_decisions_are_linearizable() -> None:
    dispatch = HandlerDispatch()
    errors: list[BaseException] = []
    handler_calls: list[int] = []
    lock = threading.Lock()

    async def counting_handler(ctx: Any, principal: Any) -> str:
        with lock:
            handler_calls.append(1)
        return "ok"

    def worker(i: int) -> None:
        try:
            comp = and_guards(RoleGuard("admin"))
            p = authenticated("u", roles=["admin"]) if i % 2 == 0 else authenticated("u", roles=["viewer"])
            run_sync(dispatch.dispatch(comp, _ctx(), p, counting_handler))
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    allows = [d for d in dispatch.decisions if d.outcome is GuardOutcome.ALLOW]
    denies = [d for d in dispatch.decisions if d.outcome is GuardOutcome.DENY_FORBIDDEN]
    # 12 allow + 12 deny across 24 requests.
    assert len(allows) == 12
    assert len(denies) == 12
    # Handler MUST have run exactly once per allow.
    assert len(handler_calls) == 12


def test_concurrent_empty_composite_rejected_from_any_thread() -> None:
    errors: list[BaseException] = []
    rejected: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            CompositeGuard([])
            with lock:
                errors.append(RuntimeError("empty composite accepted"))
        except RequestGuardInvariantError:
            with lock:
                rejected.append(1)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert len(rejected) == 8
