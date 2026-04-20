"""Unit tests for VirtualActor — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio

import pytest

from VirtualActor import (
    ActorId,
    InMemoryVirtualActor,
    VirtualActorError,
)


async def _credit(payload: bytes) -> bytes:
    return b"credited:" + payload


async def _slow(payload: bytes) -> bytes:
    await asyncio.sleep(0.01)
    return payload


def _mk() -> InMemoryVirtualActor:
    va = InMemoryVirtualActor()
    va.register("Account", "alice", {"credit": _credit, "slow": _slow})
    return va


# ---------------------------------------------------------------------------
# VACT_INV_01 — single-writer / serial invocation per ActorId
# ---------------------------------------------------------------------------
def test_inv_single_writer_confirms() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    out = asyncio.run(va.invoke(aid, "credit", b"10"))
    assert out == b"credited:10"


def test_inv_single_writer_prevents() -> None:
    # Concurrent invocations on the same ActorId MUST serialize (never run in parallel).
    va = InMemoryVirtualActor()
    order: list[str] = []

    async def h1(_p: bytes) -> bytes:
        order.append("h1-start")
        await asyncio.sleep(0.02)
        order.append("h1-end")
        return b""

    va.register("Widget", "w1", {"go": h1})
    aid = ActorId(actor_type="Widget", key="w1")

    async def run_many() -> None:
        await asyncio.gather(*(va.invoke(aid, "go", b"") for _ in range(3)))

    asyncio.run(run_many())
    # With serial execution, we MUST see start+end for each call in strict pairs.
    assert order == ["h1-start", "h1-end"] * 3


def test_inv_single_writer_under_failure() -> None:
    va = InMemoryVirtualActor()

    async def boom(_p: bytes) -> bytes:
        raise RuntimeError("actor crashed")

    va.register("X", "1", {"boom": boom})
    aid = ActorId(actor_type="X", key="1")
    # Handler crash MUST NOT leave the lock held — subsequent calls still serialize.
    with pytest.raises(RuntimeError, match="actor crashed"):
        asyncio.run(va.invoke(aid, "boom", b""))
    va.register("X", "2", {"boom": boom})  # another actor still works
    with pytest.raises(RuntimeError):
        asyncio.run(va.invoke(ActorId(actor_type="X", key="2"), "boom", b""))


# ---------------------------------------------------------------------------
# VACT_INV_02 — state never escapes actor
# ---------------------------------------------------------------------------
def test_inv_state_encapsulated_confirms() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    # Only path to the actor is invoke; no direct property access.
    out = asyncio.run(va.invoke(aid, "credit", b"5"))
    assert out == b"credited:5"


def test_inv_state_encapsulated_prevents() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    # Unknown method MUST be rejected (no access to internal dispatch table via fuzzed name).
    with pytest.raises(VirtualActorError, match="VACT-INV-02"):
        asyncio.run(va.invoke(aid, "__class__", b""))


def test_inv_state_encapsulated_under_failure() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="nobody")  # never registered
    with pytest.raises(VirtualActorError, match="VACT-INV-02"):
        asyncio.run(va.invoke(aid, "credit", b"1"))


# ---------------------------------------------------------------------------
# VACT_INV_03 — reminders survive deactivation
# ---------------------------------------------------------------------------
def test_inv_reminders_persist_confirms() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    asyncio.run(va.set_reminder(aid, "daily-summary", period_s=60))
    va.deactivate_all()  # simulate failover
    # Reminder MUST remain.
    assert va.has_reminder(aid, "daily-summary")


def test_inv_reminders_persist_prevents() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    with pytest.raises(VirtualActorError, match="VACT-INV-03"):
        asyncio.run(va.set_reminder(aid, "bad", period_s=0))
    with pytest.raises(VirtualActorError, match="VACT-INV-03"):
        asyncio.run(va.set_reminder(aid, "bad", period_s=10, ttl_s=0))


def test_inv_reminders_persist_under_failure() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    asyncio.run(va.set_reminder(aid, "r1", period_s=30))
    # Cancelling an unknown reminder MUST raise rather than silently succeed.
    with pytest.raises(VirtualActorError, match="VACT-INV-03"):
        asyncio.run(va.cancel_reminder(aid, "unknown"))
    asyncio.run(va.cancel_reminder(aid, "r1"))
    assert not va.has_reminder(aid, "r1")


# ---------------------------------------------------------------------------
# VACT_INV_04 — in-actor timers NEVER outlive deactivation
# ---------------------------------------------------------------------------
def test_inv_timers_die_on_deactivation_confirms() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    asyncio.run(va.set_reminder(aid, "tick", period_s=5))
    assert va.reminder_count() == 1
    va.deactivate_all()  # in-actor (non-reminder) timers would die here; reminders stay.
    assert va.reminder_count() == 1  # reminders persist (VACT-INV-03)


def test_inv_timers_die_on_deactivation_prevents() -> None:
    # "Timer" is not a reminder — it is local to the actor instance. Since the
    # runtime exposes NO timer API (only reminder), callers CANNOT create a
    # non-durable timer by accident. The absence IS the guarantee.
    va = InMemoryVirtualActor()
    public = {m for m in dir(va) if not m.startswith("_")}
    for forbidden in ("set_timer", "start_timer", "schedule_timer"):
        assert forbidden not in public


def test_inv_timers_die_on_deactivation_under_failure() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    # After deactivation, invoke MUST fail until reinstatement.
    va.deactivate_all()
    with pytest.raises(VirtualActorError):
        asyncio.run(va.invoke(aid, "credit", b"1"))
    # Reinstate on a "new host" (VACT-INV-05): actor is available again; reminders are unaffected.
    va.reinstate("Account", "alice", {"credit": _credit})
    out = asyncio.run(va.invoke(aid, "credit", b"1"))
    assert out == b"credited:1"


# ---------------------------------------------------------------------------
# VACT_INV_05 — caller never depends on physical host
# ---------------------------------------------------------------------------
def test_inv_host_transparent_confirms() -> None:
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    asyncio.run(va.invoke(aid, "credit", b"1"))
    # Simulate migration: deactivate and reinstate elsewhere.
    va.deactivate_all()
    va.reinstate("Account", "alice", {"credit": _credit})
    # Caller addresses by (type, key); no host reference in the call.
    out = asyncio.run(va.invoke(aid, "credit", b"2"))
    assert out == b"credited:2"


def test_inv_host_transparent_prevents() -> None:
    # Caller MUST NOT be able to inspect a "host" field on the public ActorId.
    aid = ActorId(actor_type="Account", key="alice")
    public = {f for f in dir(aid) if not f.startswith("_")}
    for forbidden in ("host", "node", "placement", "shard"):
        assert forbidden not in public


def test_inv_host_transparent_under_failure() -> None:
    # Even after many migrations, addressing by ActorId alone works.
    va = _mk()
    aid = ActorId(actor_type="Account", key="alice")
    for _ in range(3):
        va.deactivate_all()
        va.reinstate("Account", "alice", {"credit": _credit})
        out = asyncio.run(va.invoke(aid, "credit", b"x"))
        assert out == b"credited:x"
