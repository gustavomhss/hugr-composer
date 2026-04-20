"""Chaos / fault-injection for RpcInterceptor.

Game-day scenarios: oversized metadata, homogeneity breaks, handler crashes,
concurrent intercept calls. RpcInterceptor MUST remain correct under each.
"""

from __future__ import annotations

import asyncio

import pytest

from RpcInterceptor import (
    CancellationAwareInterceptor,
    CountingInterceptor,
    DeadlineEnforcingInterceptor,
    RpcCancelledError,
    RpcContext,
    RpcInterceptorError,
    compose,
    validate_metadata,
)


async def _echo(_ctx: RpcContext, payload: bytes) -> bytes:
    return payload


def test_chaos_oversized_metadata_still_validated() -> None:
    # 1000 legal keys — no crash, no memory blow-up.
    metadata = {f"key-{i}": str(i) for i in range(1000)}
    validate_metadata(metadata)


def test_chaos_handler_exception_propagates() -> None:
    async def boom(_ctx: RpcContext, _payload: bytes) -> bytes:
        raise ValueError("downstream boom")

    ic = CountingInterceptor()
    chain = compose([ic], boom)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={})
    with pytest.raises(ValueError, match="downstream boom"):
        asyncio.run(chain(ctx, b""))


def test_chaos_concurrent_intercept_safe() -> None:
    ic = CountingInterceptor()
    chain = compose([ic], _echo)

    async def fire() -> None:
        ctx = RpcContext(method="X", deadline_ms=None, metadata={})
        await chain(ctx, b"a")

    async def run_many() -> None:
        await asyncio.gather(*(fire() for _ in range(100)))

    asyncio.run(run_many())
    assert ic.intercept_calls == 100
    assert ic.next_calls == 100


def test_chaos_malformed_bin_value_rejected() -> None:
    ic = CountingInterceptor()
    chain = compose([ic], _echo)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={"trace-bin": "wrong-type"})
    with pytest.raises(RpcInterceptorError):
        asyncio.run(chain(ctx, b""))


def test_chaos_deadline_clock_skew_backwards_ignored() -> None:
    # If caller passes negative/zero deadline, interceptor shortens toward zero but never extends.
    ic = DeadlineEnforcingInterceptor(shorten_by_ms=999_999)
    chain = compose([ic], _echo)
    ctx = RpcContext(method="X", deadline_ms=10, metadata={})
    asyncio.run(chain(ctx, b""))  # clamped to 0, not extended.


def test_chaos_cancel_across_many_interceptors() -> None:
    outer = [CountingInterceptor() for _ in range(5)]
    cancel = CancellationAwareInterceptor(cancelled=True)
    chain = compose([*outer, cancel], _echo)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={})
    with pytest.raises(RpcCancelledError):
        asyncio.run(chain(ctx, b""))
    # Each outer interceptor reached the cancel layer — each called next exactly once.
    for ic in outer:
        assert ic.next_calls == 1


def test_chaos_payload_bytes_untouched_under_load() -> None:
    ic = CountingInterceptor()
    chain = compose([ic], _echo)
    payload = bytes(range(256))
    for _ in range(200):
        out = asyncio.run(chain(RpcContext(method="X", deadline_ms=None, metadata={}), payload))
        assert out == payload
