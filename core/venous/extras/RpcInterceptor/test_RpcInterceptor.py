"""Unit tests for RpcInterceptor — three per invariant (confirms / prevents / under_failure)."""

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
    shorten_deadline,
    validate_deadline,
    validate_metadata,
)


async def _terminal(_ctx: RpcContext, payload: bytes) -> bytes:
    return payload


# ---------------------------------------------------------------------------
# RPCI_INV_01 — next called exactly once unless short-circuiting
# ---------------------------------------------------------------------------
def test_inv_next_exactly_once_confirms() -> None:
    ic = CountingInterceptor()
    chain = compose([ic], _terminal)
    ctx = RpcContext(method="Foo", deadline_ms=None, metadata={})
    out = asyncio.run(chain(ctx, b"hello"))
    assert out == b"hello"
    assert ic.intercept_calls == 1
    assert ic.next_calls == 1


def test_inv_next_exactly_once_prevents() -> None:
    # Short-circuit: next MUST NOT be called.
    ic = CountingInterceptor(short_circuit_on="DenyMe", short_circuit_payload=b"denied")
    chain = compose([ic], _terminal)
    ctx = RpcContext(method="DenyMe", deadline_ms=None, metadata={})
    out = asyncio.run(chain(ctx, b"x"))
    assert out == b"denied"
    assert ic.intercept_calls == 1
    assert ic.next_calls == 0


def test_inv_next_exactly_once_under_failure() -> None:
    # Even if terminal raises, next is invoked exactly once.
    ic = CountingInterceptor()

    async def boom(_ctx: RpcContext, _payload: bytes) -> bytes:
        raise RuntimeError("downstream")

    chain = compose([ic], boom)
    ctx = RpcContext(method="Foo", deadline_ms=1000, metadata={})
    with pytest.raises(RuntimeError, match="downstream"):
        asyncio.run(chain(ctx, b"x"))
    assert ic.next_calls == 1


# ---------------------------------------------------------------------------
# RPCI_INV_02 — -bin suffix MUST carry bytes
# ---------------------------------------------------------------------------
def test_inv_bin_suffix_confirms() -> None:
    validate_metadata({"trace-id-bin": b"\x00\x01\x02"})
    validate_metadata({"authorization": "Bearer xyz"})


def test_inv_bin_suffix_prevents() -> None:
    with pytest.raises(RpcInterceptorError, match="RPCI-INV-02"):
        validate_metadata({"trace-id-bin": "not-bytes"})
    with pytest.raises(RpcInterceptorError, match="RPCI-INV-02"):
        validate_metadata({"authorization": b"bytes-not-str"})


def test_inv_bin_suffix_under_failure() -> None:
    # Even under batched validation, first offender surfaces.
    metadata = {
        "ok-key": "value",
        "bad-bin": "should be bytes",
        "also-ok": "x",
    }
    with pytest.raises(RpcInterceptorError, match="bad-bin"):
        validate_metadata(metadata)


# ---------------------------------------------------------------------------
# RPCI_INV_03 — grpc- prefix reserved
# ---------------------------------------------------------------------------
def test_inv_grpc_prefix_reserved_confirms() -> None:
    validate_metadata({"x-request-id": "r1"})
    validate_metadata({"my-custom-header": "ok"})


def test_inv_grpc_prefix_reserved_prevents() -> None:
    with pytest.raises(RpcInterceptorError, match="RPCI-INV-03"):
        validate_metadata({"grpc-accept-encoding": "gzip"})
    with pytest.raises(RpcInterceptorError, match="RPCI-INV-03"):
        validate_metadata({"GRPC-INTERNAL-X": "violation via casing"})


def test_inv_grpc_prefix_reserved_under_failure() -> None:
    ic = CountingInterceptor()
    chain = compose([ic], _terminal)
    ctx = RpcContext(method="Foo", deadline_ms=None, metadata={"grpc-reserved": "x"})
    with pytest.raises(RpcInterceptorError, match="RPCI-INV-03"):
        asyncio.run(chain(ctx, b""))


# ---------------------------------------------------------------------------
# RPCI_INV_04 — deadline only shortened, never extended
# ---------------------------------------------------------------------------
def test_inv_deadline_monotone_confirms() -> None:
    ctx = RpcContext(method="Foo", deadline_ms=1000, metadata={})
    shortened = shorten_deadline(ctx, 500)
    assert shortened.deadline_ms == 500


def test_inv_deadline_monotone_prevents() -> None:
    with pytest.raises(RpcInterceptorError, match="RPCI-INV-04"):
        validate_deadline(old_ms=1000, new_ms=2000)
    with pytest.raises(RpcInterceptorError, match="RPCI-INV-04"):
        validate_deadline(old_ms=100, new_ms=None)


def test_inv_deadline_monotone_under_failure() -> None:
    ic = DeadlineEnforcingInterceptor(shorten_by_ms=200)
    chain = compose([ic], _terminal)
    ctx = RpcContext(method="Foo", deadline_ms=1000, metadata={})
    asyncio.run(chain(ctx, b""))
    # Missing deadline stays missing — no extension attempt.
    ctx_none = RpcContext(method="Foo", deadline_ms=None, metadata={})
    asyncio.run(chain(ctx_none, b""))


# ---------------------------------------------------------------------------
# RPCI_INV_05 — cancellation MUST propagate or raise, NEVER silently swallowed
# ---------------------------------------------------------------------------
def test_inv_cancellation_propagates_confirms() -> None:
    ic = CancellationAwareInterceptor(cancelled=True)
    chain = compose([ic], _terminal)
    ctx = RpcContext(method="Foo", deadline_ms=None, metadata={})
    with pytest.raises(RpcCancelledError, match="RPCI-INV-05"):
        asyncio.run(chain(ctx, b""))


def test_inv_cancellation_propagates_prevents() -> None:
    # If downstream raises RpcCancelledError, the outer interceptor MUST re-raise.
    ic = CancellationAwareInterceptor(cancelled=False)

    async def downstream_cancel(_ctx: RpcContext, _payload: bytes) -> bytes:
        raise RpcCancelledError("downstream cancel")

    chain = compose([ic], downstream_cancel)
    ctx = RpcContext(method="Foo", deadline_ms=None, metadata={})
    with pytest.raises(RpcCancelledError):
        asyncio.run(chain(ctx, b""))


def test_inv_cancellation_propagates_under_failure() -> None:
    # Even nested inside a counting interceptor, cancellation propagates.
    outer = CountingInterceptor()
    inner = CancellationAwareInterceptor(cancelled=True)
    chain = compose([outer, inner], _terminal)
    ctx = RpcContext(method="Foo", deadline_ms=None, metadata={})
    with pytest.raises(RpcCancelledError):
        asyncio.run(chain(ctx, b""))
    # outer DID call next (which is inner); inner raised — that is honored.
    assert outer.next_calls == 1
