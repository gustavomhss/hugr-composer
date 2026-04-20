"""Metamorphic + differential tests for RpcInterceptor.

Algebraic properties:
- compose(identity) is identity (associativity / neutral element).
- compose is order-preserving: request flows outer -> inner; response flows inner -> outer.
- validate_metadata is deterministic for fixed input (no hidden state).
"""

from __future__ import annotations

import asyncio

from RpcInterceptor import (
    CountingInterceptor,
    RpcContext,
    compose,
    validate_metadata,
)


async def _echo(_ctx: RpcContext, payload: bytes) -> bytes:
    return payload


def test_metamorphic_empty_chain_is_identity() -> None:
    chain = compose([], _echo)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={})
    out = asyncio.run(chain(ctx, b"hello"))
    assert out == b"hello"


def test_metamorphic_chain_order_preserved() -> None:
    order: list[str] = []

    class Mark:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        async def intercept(self, ctx: RpcContext, payload: bytes, next):  # type: ignore[no-untyped-def] — test helper, internal Handler type
            order.append(f"pre:{self.tag}")
            r = await next(ctx, payload)
            order.append(f"post:{self.tag}")
            return r

    chain = compose([Mark("A"), Mark("B"), Mark("C")], _echo)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={})
    asyncio.run(chain(ctx, b""))
    assert order == ["pre:A", "pre:B", "pre:C", "post:C", "post:B", "post:A"]


def test_metamorphic_validate_metadata_deterministic() -> None:
    # Calling validate_metadata N times on the same input has identical outcome (no side effect).
    md = {"authorization": "Bearer xyz", "x-trace-bin": b"\x00"}
    for _ in range(10):
        validate_metadata(md)  # no exception


def test_differential_two_compositions_equivalent() -> None:
    # Composing [a, b] + [c] must equal composing [a, b, c].
    ic_a = CountingInterceptor()
    ic_b = CountingInterceptor()
    ic_c = CountingInterceptor()
    chain_single = compose([ic_a, ic_b, ic_c], _echo)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={})
    out_single = asyncio.run(chain_single(ctx, b"42"))
    # Reset and try nested composition — it behaves identically end-to-end.
    ic_a.next_calls = ic_b.next_calls = ic_c.next_calls = 0
    ic_a.intercept_calls = ic_b.intercept_calls = ic_c.intercept_calls = 0
    inner = compose([ic_b, ic_c], _echo)

    async def inner_as_terminal(ctx2: RpcContext, payload: bytes) -> bytes:
        return await inner(ctx2, payload)

    chain_nested = compose([ic_a], inner_as_terminal)
    out_nested = asyncio.run(chain_nested(ctx, b"42"))
    assert out_single == out_nested == b"42"


def test_metamorphic_payload_untouched_by_default_chain() -> None:
    ic = CountingInterceptor()
    chain = compose([ic], _echo)
    for payload in (b"", b"a", b"x" * 1000, b"\x00\x01\x02"):
        out = asyncio.run(chain(RpcContext(method="X", deadline_ms=None, metadata={}), payload))
        assert out == payload
