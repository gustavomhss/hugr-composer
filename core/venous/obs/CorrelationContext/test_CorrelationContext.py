"""Unit tests for CorrelationContext."""

from __future__ import annotations

import asyncio

import pytest
from CorrelationContext import (
    CorrelationInvariantError,
    InMemoryCorrelationContext,
    validate_request_id,
)


# CORR_INV_01 — request_id shape + stability
def test_inv_request_id_stable_confirms() -> None:
    ctx = InMemoryCorrelationContext()
    first = ctx.request_id
    assert len(first) >= 16
    # Stable across reads.
    for _ in range(5):
        assert ctx.request_id == first


def test_inv_request_id_stable_prevents() -> None:
    with pytest.raises(CorrelationInvariantError):
        validate_request_id("short")
    with pytest.raises(CorrelationInvariantError):
        validate_request_id("NOTHEX-NOTHEX-NOT!")


def test_inv_request_id_stable_under_failure() -> None:
    # Even when from_headers receives garbage, result has a valid request_id.
    ctx = InMemoryCorrelationContext.from_headers({"x-request-id": "bad"})
    validate_request_id(ctx.request_id)  # does not raise


# CORR_INV_02 — baggage limits
def test_inv_baggage_limits_confirms() -> None:
    ctx = InMemoryCorrelationContext(baggage={"tenant": "acme"})
    assert ctx.baggage() == {"tenant": "acme"}


def test_inv_baggage_limits_prevents() -> None:
    with pytest.raises(CorrelationInvariantError):
        InMemoryCorrelationContext(baggage={"k": "é"})  # non-ASCII
    with pytest.raises(CorrelationInvariantError):
        InMemoryCorrelationContext(baggage={"k": "x" * 9000})


def test_inv_baggage_limits_under_failure() -> None:
    # from_headers drops invalid entries instead of crashing.
    ctx = InMemoryCorrelationContext.from_headers({"baggage": "ok=1,bad=é"})
    assert "ok" in ctx.baggage()


# CORR_INV_03 — activate restores prior ctx even under exception
def test_inv_activate_restores_confirms() -> None:
    outer = InMemoryCorrelationContext()
    inner = InMemoryCorrelationContext()
    with outer.activate():
        assert InMemoryCorrelationContext.current().request_id == outer.request_id
        with inner.activate():
            assert InMemoryCorrelationContext.current().request_id == inner.request_id
        assert InMemoryCorrelationContext.current().request_id == outer.request_id


def test_inv_activate_restores_prevents() -> None:
    outer = InMemoryCorrelationContext()
    inner = InMemoryCorrelationContext()
    try:
        with outer.activate(), inner.activate():
            raise ValueError("boom")
    except ValueError:
        pass
    # After exception both activations are unwound — current is detached again.
    current = InMemoryCorrelationContext.current()
    assert current.request_id != inner.request_id
    assert current.request_id != outer.request_id


def test_inv_activate_restores_under_failure() -> None:
    outer = InMemoryCorrelationContext()
    try:
        with outer.activate():
            raise RuntimeError("x")
    except RuntimeError:
        pass
    assert InMemoryCorrelationContext.current().request_id != outer.request_id


# CORR_INV_04 — invalid traceparent → new trace_id, never empty
def test_inv_invalid_traceparent_confirms() -> None:
    ctx = InMemoryCorrelationContext.from_headers({"traceparent": "garbage"})
    assert ctx.trace_id is not None
    assert len(ctx.trace_id) == 32


def test_inv_invalid_traceparent_prevents() -> None:
    ctx = InMemoryCorrelationContext.from_headers({"traceparent": ""})
    assert ctx.trace_id is not None


def test_inv_invalid_traceparent_under_failure() -> None:
    for junk in ("", "00", "00-x", "weird-value", "00-" + "z" * 32 + "-abcd-01"):
        ctx = InMemoryCorrelationContext.from_headers({"traceparent": junk})
        assert ctx.trace_id is not None


# CORR_INV_05 — forbidden baggage keys stripped
def test_inv_forbidden_keys_stripped_confirms() -> None:
    ctx = InMemoryCorrelationContext(baggage={
        "tenant": "acme",
        "authorization": "Bearer leak",
        "password": "plaintext",
    })
    assert "authorization" not in ctx.baggage()
    assert "password" not in ctx.baggage()
    assert "tenant" in ctx.baggage()


def test_inv_forbidden_keys_stripped_prevents() -> None:
    # Even via headers, forbidden keys must be stripped.
    ctx = InMemoryCorrelationContext.from_headers({"baggage": "cookie=x,ok=y"})
    assert "cookie" not in ctx.baggage()
    assert ctx.baggage().get("ok") == "y"


def test_inv_forbidden_keys_stripped_under_failure() -> None:
    # Case-insensitive forbidden check.
    ctx = InMemoryCorrelationContext.from_headers({"baggage": "Authorization=bad"})
    assert not any(k.lower() == "authorization" for k in ctx.baggage())


# CORR_INV_06 — contextvars isolation across async tasks
def test_inv_contextvars_isolation_confirms() -> None:
    ctx = InMemoryCorrelationContext()

    async def task() -> str:
        return InMemoryCorrelationContext.current().request_id

    async def run() -> str:
        with ctx.activate():
            return await asyncio.create_task(task())

    result = asyncio.run(run())
    assert result == ctx.request_id


def test_inv_contextvars_isolation_prevents() -> None:
    ctx_a = InMemoryCorrelationContext()
    ctx_b = InMemoryCorrelationContext()
    observed: list[str] = []

    async def child(ctx: InMemoryCorrelationContext) -> None:
        with ctx.activate():
            await asyncio.sleep(0)
            observed.append(InMemoryCorrelationContext.current().request_id)

    async def main() -> None:
        await asyncio.gather(child(ctx_a), child(ctx_b))

    asyncio.run(main())
    assert set(observed) == {ctx_a.request_id, ctx_b.request_id}


def test_inv_contextvars_isolation_under_failure() -> None:
    ctx_a = InMemoryCorrelationContext()

    async def child() -> None:
        raise RuntimeError("boom")

    async def main() -> None:
        with ctx_a.activate():
            try:
                await asyncio.gather(child(), return_exceptions=False)
            except RuntimeError:
                pass

    asyncio.run(main())
    # After exception, the outer ctx must be cleared.
    assert InMemoryCorrelationContext.current().request_id != ctx_a.request_id
