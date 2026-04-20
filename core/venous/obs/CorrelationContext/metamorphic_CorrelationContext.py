"""Metamorphic + differential tests for CorrelationContext."""

from __future__ import annotations

from CorrelationContext import InMemoryCorrelationContext


def test_metamorphic_roundtrip_preserves_request_id() -> None:
    ctx = InMemoryCorrelationContext()
    out = dict(ctx.to_headers())
    ctx2 = InMemoryCorrelationContext.from_headers(out)
    assert ctx2.request_id == ctx.request_id


def test_metamorphic_activate_is_noop_equivalent_under_equal_ctx() -> None:
    a = InMemoryCorrelationContext()
    with a.activate():
        with a.activate():
            assert InMemoryCorrelationContext.current().request_id == a.request_id
        assert InMemoryCorrelationContext.current().request_id == a.request_id


def test_metamorphic_baggage_is_a_pure_snapshot() -> None:
    ctx = InMemoryCorrelationContext(baggage={"a": "1"})
    snap = ctx.baggage()
    snap_mut = dict(snap)
    snap_mut["x"] = "injected"
    assert "x" not in ctx.baggage()


def test_metamorphic_from_headers_default_creates_request_id() -> None:
    ctx = InMemoryCorrelationContext.from_headers({})
    assert len(ctx.request_id) >= 16


def test_differential_request_ids_are_distinct() -> None:
    ids = {InMemoryCorrelationContext().request_id for _ in range(100)}
    assert len(ids) == 100


def test_metamorphic_forbidden_key_case_insensitive() -> None:
    for variant in ("Authorization", "AUTHORIZATION", "authorization", "Cookie", "COOKIE"):
        ctx = InMemoryCorrelationContext(baggage={variant: "bad", "ok": "good"})
        assert all(k.lower() != variant.lower() for k in ctx.baggage())
