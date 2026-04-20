"""Metamorphic + differential tests for VirtualActor."""

from __future__ import annotations

import asyncio

from VirtualActor import ActorId, InMemoryVirtualActor


async def _echo(p: bytes) -> bytes:
    return p


async def _count(p: bytes) -> bytes:
    return str(len(p)).encode()


def test_metamorphic_invocation_count_monotone() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"m": _echo})
    aid = ActorId(actor_type="X", key="1")
    before = va.invocations_for(aid)
    for _ in range(5):
        asyncio.run(va.invoke(aid, "m", b""))
    assert va.invocations_for(aid) == before + 5


def test_metamorphic_echo_is_identity() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"echo": _echo})
    aid = ActorId(actor_type="X", key="1")
    for payload in (b"", b"a", b"\x00\xff", b"abcd" * 100):
        out = asyncio.run(va.invoke(aid, "echo", payload))
        assert out == payload


def test_metamorphic_reminder_set_then_cancel_is_noop() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"m": _echo})
    aid = ActorId(actor_type="X", key="1")
    before = va.reminder_count()
    asyncio.run(va.set_reminder(aid, "r", period_s=5))
    asyncio.run(va.cancel_reminder(aid, "r"))
    assert va.reminder_count() == before


def test_differential_two_actors_independent() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"m": _echo})
    va.register("X", "2", {"m": _count})
    a = ActorId(actor_type="X", key="1")
    b = ActorId(actor_type="X", key="2")
    assert asyncio.run(va.invoke(a, "m", b"abcd")) == b"abcd"
    assert asyncio.run(va.invoke(b, "m", b"abcd")) == b"4"


def test_metamorphic_reactivation_preserves_identity() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"m": _echo})
    aid = ActorId(actor_type="X", key="1")
    out_before = asyncio.run(va.invoke(aid, "m", b"same"))
    va.deactivate_all()
    va.reinstate("X", "1", {"m": _echo})
    out_after = asyncio.run(va.invoke(aid, "m", b"same"))
    assert out_before == out_after == b"same"
