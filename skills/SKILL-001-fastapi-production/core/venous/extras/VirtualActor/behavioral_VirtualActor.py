"""Behavioral end-to-end scenarios for VirtualActor."""

from __future__ import annotations

import asyncio

import pytest

from VirtualActor import (
    ActorId,
    InMemoryVirtualActor,
    VirtualActorError,
)


def test_scenario_bank_account_credits_serialize() -> None:
    va = InMemoryVirtualActor()
    balance = {"v": 0}

    async def credit(payload: bytes) -> bytes:
        amount = int(payload.decode())
        cur = balance["v"]
        await asyncio.sleep(0)  # yield to scheduler
        balance["v"] = cur + amount
        return str(balance["v"]).encode()

    va.register("Account", "alice", {"credit": credit})
    aid = ActorId(actor_type="Account", key="alice")

    async def many() -> None:
        await asyncio.gather(*(va.invoke(aid, "credit", str(i).encode()) for i in range(1, 11)))

    asyncio.run(many())
    assert balance["v"] == sum(range(1, 11))


def test_scenario_actors_with_distinct_keys_run_in_parallel() -> None:
    va = InMemoryVirtualActor()
    started: list[str] = []

    async def h(payload: bytes) -> bytes:
        started.append(payload.decode())
        await asyncio.sleep(0.02)
        return b""

    for key in ("a", "b", "c", "d"):
        va.register("W", key, {"go": h})

    async def many() -> None:
        await asyncio.gather(*(
            va.invoke(ActorId(actor_type="W", key=k), "go", k.encode())
            for k in ("a", "b", "c", "d")
        ))

    asyncio.run(many())
    assert sorted(started) == ["a", "b", "c", "d"]


def test_scenario_reminder_survives_failover() -> None:
    va = InMemoryVirtualActor()
    va.register("Widget", "k", {"tick": lambda p: _echo(p)})
    aid = ActorId(actor_type="Widget", key="k")
    asyncio.run(va.set_reminder(aid, "poll", period_s=30))
    va.deactivate_all()
    va.reinstate("Widget", "k", {"tick": lambda p: _echo(p)})
    assert va.has_reminder(aid, "poll")


def test_scenario_method_not_found_rejected() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"known": lambda p: _echo(p)})
    aid = ActorId(actor_type="X", key="1")
    with pytest.raises(VirtualActorError):
        asyncio.run(va.invoke(aid, "unknown", b""))


def test_scenario_payload_must_be_bytes() -> None:
    va = InMemoryVirtualActor()
    va.register("X", "1", {"m": lambda p: _echo(p)})
    aid = ActorId(actor_type="X", key="1")
    with pytest.raises(VirtualActorError):
        asyncio.run(va.invoke(aid, "m", "not-bytes"))  # type: ignore[arg-type]


async def _echo(payload: bytes) -> bytes:
    return payload
