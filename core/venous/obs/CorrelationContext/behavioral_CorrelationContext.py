"""Behavioral scenarios for CorrelationContext."""

from __future__ import annotations

import asyncio

from CorrelationContext import InMemoryCorrelationContext


def test_scenario_enqueue_job_roundtrip() -> None:
    ctx = InMemoryCorrelationContext()
    headers = dict(ctx.to_headers())
    headers["x-request-id"] = ctx.request_id
    rebuilt = InMemoryCorrelationContext.from_headers(headers)
    assert rebuilt.request_id == ctx.request_id


def test_scenario_forbidden_keys_never_cross_boundary() -> None:
    ctx = InMemoryCorrelationContext.from_headers({"baggage": "authorization=leak,tenant=ok"})
    out = dict(ctx.to_headers())
    assert "authorization" not in out.get("baggage", "")


def test_scenario_invalid_traceparent_self_heals() -> None:
    ctx = InMemoryCorrelationContext.from_headers({"traceparent": "corrupt"})
    assert ctx.trace_id is not None


def test_scenario_activation_nesting_preserves_outer() -> None:
    outer = InMemoryCorrelationContext()
    inner = InMemoryCorrelationContext()
    with outer.activate():
        assert InMemoryCorrelationContext.current().request_id == outer.request_id
        with inner.activate():
            pass
        assert InMemoryCorrelationContext.current().request_id == outer.request_id


def test_scenario_async_tasks_do_not_share_context() -> None:
    ctx_a = InMemoryCorrelationContext()
    ctx_b = InMemoryCorrelationContext()
    out: list[str] = []

    async def sink() -> None:
        out.append(InMemoryCorrelationContext.current().request_id)

    async def main() -> None:
        with ctx_a.activate():
            await asyncio.create_task(sink())
            with ctx_b.activate():
                await asyncio.create_task(sink())
            await asyncio.create_task(sink())

    asyncio.run(main())
    assert out[0] == ctx_a.request_id
    assert out[1] == ctx_b.request_id
    assert out[2] == ctx_a.request_id


def test_scenario_baggage_limit_enforced_on_ingest() -> None:
    ctx = InMemoryCorrelationContext.from_headers({
        "baggage": f"big={'x' * 9000},ok=small",
    })
    assert "big" not in ctx.baggage()
    assert ctx.baggage().get("ok") == "small"
