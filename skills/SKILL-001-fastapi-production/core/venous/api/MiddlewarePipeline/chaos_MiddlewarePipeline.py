"""Chaos / fault-injection for MiddlewarePipeline.

Game-day scenarios: raising middlewares, filters that themselves raise,
concurrent re-entrant runs, late-registration attempts, filter ordering
under crashes. The primitive MUST preserve the five invariants under each.
"""

from __future__ import annotations

import asyncio

import pytest

from MiddlewarePipeline import (
    FALLBACK_STATUS,
    InMemoryMiddlewarePipeline,
    MWPInvariantError,
    Next,
    RequestContext,
)


def _run(coro: object) -> None:
    assert asyncio.iscoroutine(coro)
    asyncio.run(coro)


def test_chaos_raising_middleware_propagates_after_filters() -> None:
    pipe = InMemoryMiddlewarePipeline()
    saw: list[str] = []

    async def boom(ctx: RequestContext, call_next: Next) -> None:
        raise RuntimeError("explode")

    async def probe(ctx: RequestContext, exc: BaseException) -> None:
        saw.append(type(exc).__name__)  # observes but does not resolve

    boom.__name__ = "boom"
    pipe.use(boom)
    pipe.use_error_filter(probe)
    ctx = RequestContext()
    with pytest.raises(RuntimeError, match="explode"):
        _run(pipe.run(ctx))
    assert saw == ["RuntimeError"]
    assert ctx.status == FALLBACK_STATUS  # MWP-INV-05: 500 stamped even on re-raise.


def test_chaos_filter_that_raises_does_not_mask_recovery() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def boom(ctx: RequestContext, call_next: Next) -> None:
        raise RuntimeError("primary")

    async def bad(ctx: RequestContext, exc: BaseException) -> None:
        raise RuntimeError("filter-crash")

    async def recover(ctx: RequestContext, exc: BaseException) -> None:
        ctx.write_response(503, {"error": "degraded"})

    boom.__name__ = "boom"
    pipe.use(boom)
    pipe.use_error_filter(bad)
    pipe.use_error_filter(recover)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.status == 503
    errs = ctx.get("mwp.filter_errors")
    assert isinstance(errs, list) and len(errs) == 1


def test_chaos_concurrent_reentrancy_does_not_interleave_state() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def tag(ctx: RequestContext, call_next: Next) -> None:
        ctx.put("tag", ctx.path)
        await asyncio.sleep(0)  # force interleaving
        await call_next()

    async def handler(ctx: RequestContext, call_next: Next) -> None:
        await asyncio.sleep(0)
        ctx.write_response(200, {"tag": ctx.get("tag"), "path": ctx.path})

    tag.__name__ = "tag"
    handler.__name__ = "handler"
    pipe.use(tag).use(handler)

    async def driver() -> list[RequestContext]:
        ctxs = [RequestContext(path=f"/p/{i}") for i in range(32)]
        await asyncio.gather(*(pipe.run(c) for c in ctxs))
        return ctxs

    ctxs = asyncio.run(driver())
    for c in ctxs:
        assert isinstance(c.body, dict)
        assert c.body["tag"] == c.path  # no cross-request leakage


def test_chaos_late_registration_after_run_refused() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def a(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    async def late(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    a.__name__ = "a"
    late.__name__ = "late"
    pipe.use(a)
    _run(pipe.run(RequestContext()))
    for op in (
        lambda: pipe.use(late, name="late"),
        lambda: pipe.insert_after("a", late, name="late"),
        lambda: pipe.swap("a", "late"),
        lambda: pipe.remove("a"),
        lambda: pipe.use_error_filter(lambda c, e: asyncio.sleep(0)),  # type: ignore[arg-type,return-value]  # MWP-INV-04: deliberately malformed to prove freeze-refusal.
    ):
        with pytest.raises(MWPInvariantError):
            op()


def test_chaos_storm_of_requests_preserves_ordering() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def tick(ctx: RequestContext, call_next: Next) -> None:
        ctx.put("tick", True)
        await call_next()

    async def handler(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    tick.__name__ = "tick"
    handler.__name__ = "handler"
    pipe.use(tick).use(handler)

    async def driver() -> None:
        await asyncio.gather(*(pipe.run(RequestContext()) for _ in range(256)))

    asyncio.run(driver())
    assert pipe.names == ("tick", "handler")  # chain unchanged under load


def test_chaos_unknown_anchor_raises_loudly() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def m(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    with pytest.raises(MWPInvariantError, match="MWP-INV-01"):
        pipe.insert_before("nope", m, name="x")
    with pytest.raises(MWPInvariantError, match="MWP-INV-01"):
        pipe.remove("nope")


def test_chaos_duplicate_name_registration_refused() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def m(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    pipe.use(m, name="auth")
    with pytest.raises(MWPInvariantError, match="MWP-INV-01"):
        pipe.use(m, name="auth")
