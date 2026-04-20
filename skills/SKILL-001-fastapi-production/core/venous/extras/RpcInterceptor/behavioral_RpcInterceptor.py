"""Behavioral end-to-end scenarios for RpcInterceptor — proves invariants at runtime."""

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
)


async def _echo(_ctx: RpcContext, payload: bytes) -> bytes:
    return payload


def test_scenario_auth_then_deadline_then_call() -> None:
    auth = CountingInterceptor()
    dl = DeadlineEnforcingInterceptor(shorten_by_ms=50)
    chain = compose([auth, dl], _echo)
    ctx = RpcContext(method="GetUser", deadline_ms=1000, metadata={"authorization": "Bearer token"})
    out = asyncio.run(chain(ctx, b"ping"))
    assert out == b"ping"
    assert auth.next_calls == 1


def test_scenario_short_circuit_skips_downstream() -> None:
    short = CountingInterceptor(short_circuit_on="Blocked", short_circuit_payload=b"nope")
    downstream = CountingInterceptor()
    chain = compose([short, downstream], _echo)
    ctx = RpcContext(method="Blocked", deadline_ms=None, metadata={})
    out = asyncio.run(chain(ctx, b""))
    assert out == b"nope"
    assert downstream.intercept_calls == 0


def test_scenario_cancellation_before_handler() -> None:
    ic = CancellationAwareInterceptor(cancelled=True)
    reached = CountingInterceptor()
    chain = compose([ic, reached], _echo)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={})
    with pytest.raises(RpcCancelledError):
        asyncio.run(chain(ctx, b""))
    assert reached.intercept_calls == 0


def test_scenario_metadata_validated_before_handler() -> None:
    v = CountingInterceptor()
    chain = compose([v], _echo)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={"grpc-internal": "reserved"})
    with pytest.raises(RpcInterceptorError):
        asyncio.run(chain(ctx, b""))
    # Handler not invoked because metadata validation fails in intercept.
    assert v.next_calls == 0


def test_scenario_deadline_propagates_through_multiple_interceptors() -> None:
    a = DeadlineEnforcingInterceptor(shorten_by_ms=100)
    b = DeadlineEnforcingInterceptor(shorten_by_ms=200)
    seen: list[int | None] = []

    async def terminal(ctx: RpcContext, payload: bytes) -> bytes:
        seen.append(ctx.deadline_ms)
        return payload

    chain = compose([a, b], terminal)
    ctx = RpcContext(method="X", deadline_ms=1000, metadata={})
    asyncio.run(chain(ctx, b""))
    assert seen == [700]  # 1000 - 100 - 200


def test_scenario_binary_metadata_roundtrip() -> None:
    seen: list[bytes] = []

    async def terminal(ctx: RpcContext, _payload: bytes) -> bytes:
        val = ctx.metadata["trace-id-bin"]
        assert isinstance(val, (bytes, bytearray, memoryview))
        seen.append(bytes(val))
        return b""

    v = CountingInterceptor()
    chain = compose([v], terminal)
    ctx = RpcContext(method="X", deadline_ms=None, metadata={"trace-id-bin": b"\xde\xad"})
    asyncio.run(chain(ctx, b""))
    assert seen == [b"\xde\xad"]
