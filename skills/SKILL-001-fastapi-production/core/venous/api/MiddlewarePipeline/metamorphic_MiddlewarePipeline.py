"""Metamorphic + differential tests for MiddlewarePipeline.

Algebraic properties:
- identity middleware composition: `pipe([id, mw, id])` ≡ `pipe([mw])`.
- associativity of append: `use(a).use(b).use(c)` invokes in the same order
  regardless of bracketing.
- insert_after + remove round-trip leaves the chain byte-identical.
- short-circuit locality: middleware order upstream of a halt has no bearing
  on whether downstream runs.
- swap is an involution: `swap(a,b).swap(a,b)` is the identity.
"""

from __future__ import annotations

import asyncio

from MiddlewarePipeline import (
    InMemoryMiddlewarePipeline,
    Next,
    RequestContext,
)


def _run(coro: object) -> None:
    assert asyncio.iscoroutine(coro)
    asyncio.run(coro)


def _record(label: str, log: list[str]) -> object:
    async def mw(ctx: RequestContext, call_next: Next) -> None:
        log.append(label)
        await call_next()

    mw.__name__ = label
    return mw


def test_metamorphic_identity_middleware_is_neutral() -> None:
    base_log: list[str] = []
    id_log: list[str] = []

    async def terminator(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    terminator.__name__ = "term"

    base = InMemoryMiddlewarePipeline().use(_record("a", base_log)).use(terminator)
    _run(base.run(RequestContext()))

    idp = (
        InMemoryMiddlewarePipeline()
        .use(_record("pre", id_log), name="pre")
        .use(_record("a", id_log))
        .use(_record("post", id_log), name="post")
        .use(terminator)
    )
    _run(idp.run(RequestContext()))
    # Removing the identity stages from the id_log recovers the base order.
    filtered = [x for x in id_log if x == "a"]
    assert filtered == base_log


def test_metamorphic_append_associativity() -> None:
    async def terminator(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200)

    terminator.__name__ = "term"

    log_a: list[str] = []
    p_a = InMemoryMiddlewarePipeline()
    p_a.use(_record("x", log_a)).use(_record("y", log_a)).use(_record("z", log_a)).use(terminator)
    _run(p_a.run(RequestContext()))

    log_b: list[str] = []
    p_b = InMemoryMiddlewarePipeline()
    p_b.use(_record("x", log_b))
    p_b.use(_record("y", log_b))
    p_b.use(_record("z", log_b))
    p_b.use(terminator)
    _run(p_b.run(RequestContext()))

    assert log_a == log_b == ["x", "y", "z"]


def test_metamorphic_insert_and_remove_roundtrip() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def m(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    m.__name__ = "m"

    pipe.use(m, name="a").use(m, name="b").use(m, name="c")
    before = pipe.names
    pipe.insert_after("b", m, name="tmp")
    pipe.remove("tmp")
    after = pipe.names
    assert before == after == ("a", "b", "c")


def test_metamorphic_swap_involution() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def m(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    m.__name__ = "m"
    pipe.use(m, name="a").use(m, name="b").use(m, name="c")
    pipe.swap("a", "c").swap("a", "c")
    assert pipe.names == ("a", "b", "c")


def test_differential_short_circuit_locality() -> None:
    # The set of middlewares that DO run downstream of a short-circuit is
    # empty regardless of what sits upstream.
    async def noop(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    async def halt(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(418, {"msg": "I'm a teapot"})

    seen: list[str] = []

    async def downstream(ctx: RequestContext, call_next: Next) -> None:
        seen.append("downstream")
        await call_next()

    noop.__name__ = "noop"
    halt.__name__ = "halt"
    downstream.__name__ = "downstream"

    for n_upstream in (0, 1, 5):
        seen.clear()
        pipe = InMemoryMiddlewarePipeline()
        for i in range(n_upstream):
            pipe.use(noop, name=f"up-{i}")
        pipe.use(halt).use(downstream)
        ctx = RequestContext()
        _run(pipe.run(ctx))
        assert seen == []
        assert ctx.status == 418
