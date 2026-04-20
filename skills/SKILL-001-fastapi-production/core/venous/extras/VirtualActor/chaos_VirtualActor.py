"""Chaos / fault-injection for VirtualActor."""

from __future__ import annotations

import asyncio

import pytest

from VirtualActor import ActorId, InMemoryVirtualActor, VirtualActorError


async def _echo(p: bytes) -> bytes:
    return p


def test_chaos_handler_raises_lock_released() -> None:
    va = InMemoryVirtualActor()
    calls = {"n": 0}

    async def flaky(_p: bytes) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("one-time blip")
        return b"ok"

    va.register("X", "1", {"m": flaky})
    aid = ActorId(actor_type="X", key="1")
    with pytest.raises(RuntimeError):
        asyncio.run(va.invoke(aid, "m", b""))
    # Lock released on exception — second call can proceed.
    out = asyncio.run(va.invoke(aid, "m", b""))
    assert out == b"ok"


def test_chaos_many_distinct_actors() -> None:
    va = InMemoryVirtualActor()
    for i in range(100):
        va.register("W", str(i), {"m": _echo})
    results: list[bytes] = []

    async def run_all() -> None:
        results.extend(await asyncio.gather(*(
            va.invoke(ActorId(actor_type="W", key=str(i)), "m", str(i).encode())
            for i in range(100)
        )))

    asyncio.run(run_all())
    assert len(results) == 100


def test_chaos_reminder_cancel_twice_second_fails() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"m": _echo})
    aid = ActorId(actor_type="X", key="1")
    asyncio.run(va.set_reminder(aid, "r", period_s=10))
    asyncio.run(va.cancel_reminder(aid, "r"))
    with pytest.raises(VirtualActorError):
        asyncio.run(va.cancel_reminder(aid, "r"))


def test_chaos_actor_id_with_empty_strings_rejected() -> None:
    with pytest.raises(VirtualActorError):
        ActorId(actor_type="", key="alice")
    with pytest.raises(VirtualActorError):
        ActorId(actor_type="X", key="")


def test_chaos_rapid_migration_cycles() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"m": _echo})
    aid = ActorId(actor_type="X", key="1")
    asyncio.run(va.set_reminder(aid, "r", period_s=10))
    for _ in range(20):
        va.deactivate_all()
        va.reinstate("X", "1", {"m": _echo})
        out = asyncio.run(va.invoke(aid, "m", b"hello"))
        assert out == b"hello"
    # Reminder survived every migration.
    assert va.has_reminder(aid, "r")


def test_chaos_concurrent_credits_no_lost_updates() -> None:
    va = InMemoryVirtualActor()
    balance = {"v": 0}

    async def credit(payload: bytes) -> bytes:
        cur = balance["v"]
        await asyncio.sleep(0)
        balance["v"] = cur + int(payload.decode())
        return b""

    va.register("Bank", "main", {"credit": credit})
    aid = ActorId(actor_type="Bank", key="main")

    async def run_many() -> None:
        await asyncio.gather(*(va.invoke(aid, "credit", b"1") for _ in range(500)))

    asyncio.run(run_many())
    assert balance["v"] == 500
