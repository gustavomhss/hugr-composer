"""Chaos / fault-injection for CorrelationContext."""

from __future__ import annotations

import asyncio
import threading

import pytest

from CorrelationContext import (
    CorrelationInvariantError,
    InMemoryCorrelationContext,
    validate_request_id,
)


def test_chaos_concurrent_activations_do_not_cross() -> None:
    ctxs = [InMemoryCorrelationContext() for _ in range(8)]
    observed: list[tuple[int, str]] = []

    def worker(i: int) -> None:
        with ctxs[i].activate():
            observed.append((i, InMemoryCorrelationContext.current().request_id))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i, rid in observed:
        assert rid == ctxs[i].request_id


def test_chaos_malformed_headers_never_crash() -> None:
    for bad in (
        {"traceparent": "gibberish"},
        {"baggage": "notapair"},
        {"baggage": "authorization=leak"},
        {"x-request-id": "short"},
        {},
    ):
        ctx = InMemoryCorrelationContext.from_headers(bad)
        assert ctx.request_id


def test_chaos_repeated_invalid_request_id_rejected_directly() -> None:
    for bad in ("", "short", "NOTHEX_________", "!!!@@@###"):
        with pytest.raises(CorrelationInvariantError):
            validate_request_id(bad)


def test_chaos_baggage_injection_of_forbidden_key_stripped_each_time() -> None:
    for _ in range(10):
        ctx = InMemoryCorrelationContext(baggage={"authorization": "x", "ok": "y"})
        assert "authorization" not in ctx.baggage()


def test_chaos_async_exception_restores_context() -> None:
    ctx = InMemoryCorrelationContext()

    async def child() -> None:
        raise RuntimeError("boom")

    async def main() -> None:
        with ctx.activate():
            try:
                await child()
            except RuntimeError:
                pass

    asyncio.run(main())
    assert InMemoryCorrelationContext.current().request_id != ctx.request_id


def test_chaos_many_sequential_contexts_dont_leak() -> None:
    seen: set[str] = set()
    for _ in range(200):
        c = InMemoryCorrelationContext()
        with c.activate():
            seen.add(InMemoryCorrelationContext.current().request_id)
    assert len(seen) == 200


def test_chaos_large_baggage_value_dropped_single_entry() -> None:
    ctx = InMemoryCorrelationContext.from_headers({
        "baggage": "k1=ok,k2=" + ("x" * 10000) + ",k3=fine",
    })
    b = ctx.baggage()
    assert "k1" in b and "k3" in b
    assert "k2" not in b
