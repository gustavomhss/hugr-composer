"""Unit tests for MiddlewarePipeline — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio

import pytest
from MiddlewarePipeline import (
    FALLBACK_STATUS,
    InMemoryMiddlewarePipeline,
    MWPInvariantError,
    Next,
    RequestContext,
    ensure_response,
)


def _run(coro: object) -> None:
    assert asyncio.iscoroutine(coro)
    asyncio.run(coro)


# ---------------------------------------------------------------------------
# MWP_INV_01 — registration order is the execution order
# ---------------------------------------------------------------------------
def test_inv_order_preserved_confirms() -> None:
    log: list[str] = []
    pipe = InMemoryMiddlewarePipeline()

    def make(label: str) -> object:
        async def mw(ctx: RequestContext, call_next: Next) -> None:
            log.append(f"pre:{label}")
            await call_next()
            log.append(f"post:{label}")

        mw.__name__ = label
        return mw

    for label in ("a", "b", "c"):
        pipe.use(make(label))

    async def terminator(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200, {"ok": True})

    terminator.__name__ = "term"
    pipe.use(terminator)

    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert log == ["pre:a", "pre:b", "pre:c", "post:c", "post:b", "post:a"]


def test_inv_order_preserved_prevents() -> None:
    # Re-registering the same name is refused — MWP-INV-01 keeps the ordering
    # manipulations explicit.
    pipe = InMemoryMiddlewarePipeline()

    async def mw(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    mw.__name__ = "alpha"
    pipe.use(mw, name="alpha")
    with pytest.raises(MWPInvariantError, match="MWP-INV-01"):
        pipe.use(mw, name="alpha")


def test_inv_order_preserved_under_failure() -> None:
    # insert_before / swap on an unknown name MUST raise — explicit ordering only.
    pipe = InMemoryMiddlewarePipeline()

    async def mw(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    with pytest.raises(MWPInvariantError):
        pipe.insert_before("missing", mw, name="inj")
    with pytest.raises(MWPInvariantError):
        pipe.swap("a", "b")


# ---------------------------------------------------------------------------
# MWP_INV_02 — no-await-call_next short-circuits the rest
# ---------------------------------------------------------------------------
def test_inv_short_circuit_confirms() -> None:
    visited: list[str] = []
    pipe = InMemoryMiddlewarePipeline()

    async def gate(ctx: RequestContext, call_next: Next) -> None:
        visited.append("gate")
        # Intentionally does NOT await call_next — short-circuit.
        ctx.write_response(401, {"error": "unauthenticated"})

    async def downstream(ctx: RequestContext, call_next: Next) -> None:
        visited.append("downstream")  # MUST NOT execute
        await call_next()

    gate.__name__ = "gate"
    downstream.__name__ = "downstream"
    pipe.use(gate).use(downstream)

    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert visited == ["gate"]
    assert ctx.halted_by == "gate"
    assert ctx.status == 401


def test_inv_short_circuit_prevents() -> None:
    # A middleware that awaits call_next MUST reach downstream.
    visited: list[str] = []
    pipe = InMemoryMiddlewarePipeline()

    async def a(ctx: RequestContext, call_next: Next) -> None:
        visited.append("a")
        await call_next()

    async def b(ctx: RequestContext, call_next: Next) -> None:
        visited.append("b")
        ctx.write_response(200, {"ok": True})

    a.__name__ = "a"
    b.__name__ = "b"
    pipe.use(a).use(b)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert visited == ["a", "b"]
    assert ctx.halted_by is None


def test_inv_short_circuit_under_failure() -> None:
    # Halt that does NOT write a response, WITH downstream present, yields a 500
    # by contract (MWP-INV-02 + MWP-INV-05) and records the halt origin.
    pipe = InMemoryMiddlewarePipeline()

    async def silent_halt(ctx: RequestContext, call_next: Next) -> None:
        pass  # no call_next, no response → unhandled halt.

    async def downstream(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200, {"ok": True})  # MUST NOT run

    silent_halt.__name__ = "silent_halt"
    downstream.__name__ = "downstream"
    pipe.use(silent_halt).use(downstream)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.halted_by == "silent_halt"
    assert ctx.status == FALLBACK_STATUS
    assert ctx.response_written


# ---------------------------------------------------------------------------
# MWP_INV_03 — error filters ALWAYS run on exception
# ---------------------------------------------------------------------------
def test_inv_error_filter_runs_confirms() -> None:
    seen: list[str] = []
    pipe = InMemoryMiddlewarePipeline()

    async def boom(ctx: RequestContext, call_next: Next) -> None:
        raise RuntimeError("kaboom")

    async def flt(ctx: RequestContext, exc: BaseException) -> None:
        seen.append(type(exc).__name__)
        ctx.write_response(500, {"error": "caught"})

    boom.__name__ = "boom"
    pipe.use(boom)
    pipe.use_error_filter(flt)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert seen == ["RuntimeError"]
    assert ctx.status == 500
    assert ctx.response_written


def test_inv_error_filter_runs_prevents() -> None:
    # If NO filter writes a response, the exception still propagates — filters
    # cannot silently swallow errors, preserving fail-loud semantics.
    pipe = InMemoryMiddlewarePipeline()

    async def boom(ctx: RequestContext, call_next: Next) -> None:
        raise ValueError("payload-rejected")

    async def quiet_filter(ctx: RequestContext, exc: BaseException) -> None:
        # Observes but does NOT write a response.
        ctx.put("filter_saw", type(exc).__name__)

    boom.__name__ = "boom"
    pipe.use(boom)
    pipe.use_error_filter(quiet_filter)
    ctx = RequestContext()
    with pytest.raises(ValueError, match="payload-rejected"):
        _run(pipe.run(ctx))
    assert ctx.get("filter_saw") == "ValueError"
    # MWP-INV-05 still stamps a 500 body for observability.
    assert ctx.status == FALLBACK_STATUS


def test_inv_error_filter_runs_under_failure() -> None:
    # A filter that itself raises MUST NOT mask siblings; the chain keeps
    # walking so a later filter can still recover.
    pipe = InMemoryMiddlewarePipeline()

    async def boom(ctx: RequestContext, call_next: Next) -> None:
        raise RuntimeError("primary")

    async def bad_filter(ctx: RequestContext, exc: BaseException) -> None:
        raise RuntimeError("filter-internal")

    async def recovering_filter(ctx: RequestContext, exc: BaseException) -> None:
        ctx.write_response(503, {"error": "degraded"})

    boom.__name__ = "boom"
    pipe.use(boom)
    pipe.use_error_filter(bad_filter)
    pipe.use_error_filter(recovering_filter)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.status == 503
    errs = ctx.get("mwp.filter_errors")
    assert isinstance(errs, list) and len(errs) == 1


# ---------------------------------------------------------------------------
# MWP_INV_04 — frozen after first run()
# ---------------------------------------------------------------------------
def test_inv_frozen_after_run_confirms() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def a(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    a.__name__ = "a"
    pipe.use(a)
    assert not pipe.frozen
    _run(pipe.run(RequestContext()))
    assert pipe.frozen


def test_inv_frozen_after_run_prevents() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def a(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    async def late(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    a.__name__ = "a"
    late.__name__ = "late"
    pipe.use(a)
    _run(pipe.run(RequestContext()))
    with pytest.raises(MWPInvariantError, match="MWP-INV-04"):
        pipe.use(late)


def test_inv_frozen_after_run_under_failure() -> None:
    # ALL mutation operations are refused post-freeze, not just `use`.
    pipe = InMemoryMiddlewarePipeline()

    async def a(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    async def b(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    a.__name__ = "a"
    b.__name__ = "b"
    pipe.use(a).use(b)
    _run(pipe.run(RequestContext()))
    for op in (
        lambda: pipe.insert_before("a", b, name="z"),
        lambda: pipe.insert_after("a", b, name="z"),
        lambda: pipe.remove("a"),
        lambda: pipe.swap("a", "b"),
    ):
        with pytest.raises(MWPInvariantError, match="MWP-INV-04"):
            op()


# ---------------------------------------------------------------------------
# MWP_INV_05 — always produces a response; unhandled halt yields 500
# ---------------------------------------------------------------------------
def test_inv_always_responds_confirms() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def terminator(ctx: RequestContext, call_next: Next) -> None:
        await call_next()  # no downstream — falls through the empty tail.
        ctx.write_response(200, {"ok": True})

    terminator.__name__ = "term"
    pipe.use(terminator)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.response_written
    assert ctx.status == 200


def test_inv_always_responds_prevents() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def halt(ctx: RequestContext, call_next: Next) -> None:
        pass  # silent halt — no response written.

    async def tail(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)  # MUST NOT run

    halt.__name__ = "halt"
    tail.__name__ = "tail"
    pipe.use(halt).use(tail)
    ctx = RequestContext()
    _run(pipe.run(ctx))
    assert ctx.status == FALLBACK_STATUS
    assert ctx.response_written
    assert isinstance(ctx.body, dict) and ctx.body.get("error") == "UnhandledHalt"


def test_inv_always_responds_under_failure() -> None:
    # ensure_response() directly stamps a 500 on a bare unresponded context.
    ctx = RequestContext()
    assert not ctx.response_written
    ensure_response(ctx)
    assert ctx.status == FALLBACK_STATUS
    assert ctx.response_written
    # Idempotent: second call is a no-op.
    ctx.status = 201
    ensure_response(ctx)
    assert ctx.status == 201
