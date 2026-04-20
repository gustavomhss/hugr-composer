"""Behavioral end-to-end scenarios for MiddlewarePipeline.

Each scenario drives the primitive through a realistic cross-cutting-concern
workflow (auth + logging + rate-limit + timing + error shaping) and asserts
invariant outcomes at runtime.
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


def test_scenario_auth_logging_handler_chain() -> None:
    calls: list[str] = []
    pipe = InMemoryMiddlewarePipeline()

    async def logging_mw(ctx: RequestContext, call_next: Next) -> None:
        calls.append("log:in")
        await call_next()
        calls.append(f"log:out:{ctx.status}")

    async def auth_mw(ctx: RequestContext, call_next: Next) -> None:
        calls.append("auth")
        if ctx.headers.get("Authorization") != "Bearer OK":
            ctx.write_response(401, {"error": "unauth"})
            return
        await call_next()

    async def handler(ctx: RequestContext, call_next: Next) -> None:
        calls.append("handler")
        ctx.write_response(200, {"hello": "world"})

    logging_mw.__name__ = "logging"
    auth_mw.__name__ = "auth"
    handler.__name__ = "handler"
    pipe.use(logging_mw).use(auth_mw).use(handler)

    # Authorized: full chain runs.
    ctx_ok = RequestContext(headers={"Authorization": "Bearer OK"})
    _run(pipe.run(ctx_ok))
    assert ctx_ok.status == 200
    assert calls == ["log:in", "auth", "handler", "log:out:200"]


def test_scenario_auth_short_circuit_stops_handler() -> None:
    pipe = InMemoryMiddlewarePipeline()
    visited: list[str] = []

    async def auth(ctx: RequestContext, call_next: Next) -> None:
        visited.append("auth")
        ctx.write_response(401, {"error": "no-token"})
        # Intentional: does NOT await call_next — short-circuit.

    async def handler(ctx: RequestContext, call_next: Next) -> None:
        visited.append("handler")  # MUST NOT run
        ctx.write_response(200)

    auth.__name__ = "auth"
    handler.__name__ = "handler"
    pipe.use(auth).use(handler)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert visited == ["auth"]
    assert ctx.status == 401
    assert ctx.halted_by == "auth"


def test_scenario_error_filter_shapes_5xx_response() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def breaking_handler(ctx: RequestContext, call_next: Next) -> None:
        raise RuntimeError("downstream-db-offline")

    async def error_shape(ctx: RequestContext, exc: BaseException) -> None:
        ctx.write_response(503, {"error": "ServiceUnavailable", "cause": str(exc)})

    breaking_handler.__name__ = "handler"
    pipe.use(breaking_handler)
    pipe.use_error_filter(error_shape)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.status == 503
    assert isinstance(ctx.body, dict) and ctx.body.get("cause") == "downstream-db-offline"


def test_scenario_rate_limit_middleware_halts_with_429() -> None:
    pipe = InMemoryMiddlewarePipeline()
    remaining = {"tokens": 0}

    async def rate_limit(ctx: RequestContext, call_next: Next) -> None:
        if remaining["tokens"] <= 0:
            ctx.write_response(429, {"error": "too-many-requests"})
            return
        remaining["tokens"] -= 1
        await call_next()

    async def handler(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    rate_limit.__name__ = "rate_limit"
    handler.__name__ = "handler"
    pipe.use(rate_limit).use(handler)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.status == 429
    assert ctx.halted_by == "rate_limit"


def test_scenario_frozen_pipeline_rejects_late_registration() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def h(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    async def late(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    h.__name__ = "h"
    late.__name__ = "late"
    pipe.use(h)
    _run(pipe.run(RequestContext()))
    with pytest.raises(MWPInvariantError, match="MWP-INV-04"):
        pipe.use(late)


def test_scenario_reentrancy_concurrent_requests_isolated() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def counter_mw(ctx: RequestContext, call_next: Next) -> None:
        prev = ctx.get("n", 0)
        assert isinstance(prev, int)
        ctx.put("n", prev + 1)
        await call_next()

    async def handler(ctx: RequestContext, call_next: Next) -> None:
        await asyncio.sleep(0)  # yield to other tasks
        ctx.write_response(200, {"n": ctx.get("n")})

    counter_mw.__name__ = "counter"
    handler.__name__ = "handler"
    pipe.use(counter_mw).use(handler)

    async def driver() -> list[RequestContext]:
        ctxs = [RequestContext() for _ in range(8)]
        await asyncio.gather(*(pipe.run(c) for c in ctxs))
        return ctxs

    ctxs = asyncio.run(driver())
    # Each context has its own state — re-entrant safe even though the chain
    # is shared; MWP-INV-01 ordering preserved for every request.
    for c in ctxs:
        assert c.status == 200
        assert c.get("n") == 1


def test_scenario_unhandled_halt_yields_500() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def buggy(ctx: RequestContext, call_next: Next) -> None:
        # Halts without awaiting call_next AND without writing a response.
        # Classic production bug; MWP-INV-05 demands a 500.
        return

    async def tail(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)  # MUST NOT run

    buggy.__name__ = "buggy"
    tail.__name__ = "tail"
    pipe.use(buggy).use(tail)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.status == FALLBACK_STATUS
    assert isinstance(ctx.body, dict) and ctx.body.get("halted_by") == "buggy"
