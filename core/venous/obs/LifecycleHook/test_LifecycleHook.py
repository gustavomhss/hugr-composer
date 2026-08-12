"""Unit tests — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio

import pytest
from LifecycleHook import (
    LifecycleHook,
    LifecycleInvariantError,
    LifecyclePhase,
    LifecycleRegistry,
)


def _run(coro):  # type: ignore[no-untyped-def]  # async test helper; signature varies by coroutine
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# LIFE_INV_01 — READY exactly once, after STARTING success
# ---------------------------------------------------------------------------
def test_inv_ready_once_confirms() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        fired: list[str] = []

        async def s() -> None:
            fired.append("start")

        async def r() -> None:
            fired.append("ready")

        reg.register(LifecycleHook(LifecyclePhase.STARTING, s))
        reg.register(LifecycleHook(LifecyclePhase.READY, r))
        await reg.run_starting()
        await reg.run_ready()
        assert fired == ["start", "ready"]
        assert reg.ready_fired

    asyncio.run(run())


def test_inv_ready_once_prevents() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()

        async def r() -> None:
            pass

        reg.register(LifecycleHook(LifecyclePhase.READY, r))
        await reg.run_starting()
        await reg.run_ready()
        with pytest.raises(LifecycleInvariantError):
            await reg.run_ready()

    asyncio.run(run())


def test_inv_ready_once_under_failure() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()

        async def boom() -> None:
            raise RuntimeError("bad startup")

        async def r() -> None:
            pass

        reg.register(LifecycleHook(LifecyclePhase.STARTING, boom))
        reg.register(LifecycleHook(LifecyclePhase.READY, r))
        with pytest.raises(RuntimeError):
            await reg.run_starting()
        assert reg.starting_failed
        with pytest.raises(LifecycleInvariantError):
            await reg.run_ready()
        assert not reg.ready_fired

    asyncio.run(run())


# ---------------------------------------------------------------------------
# LIFE_INV_02 — STOPPING LIFO
# ---------------------------------------------------------------------------
def test_inv_stopping_lifo_confirms() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        order: list[str] = []

        async def mk(label: str):  # type: ignore[no-untyped-def]  # factory for async closure returning coroutine
            async def inner() -> None:
                order.append(label)
            return inner

        for label in ("a", "b", "c"):
            cb = await mk(label)
            reg.register(LifecycleHook(LifecyclePhase.STOPPING, cb))
        await reg.run_stopping()
        assert order == ["c", "b", "a"]

    asyncio.run(run())


def test_inv_stopping_lifo_prevents() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()

        async def noop() -> None:
            pass

        reg.register(LifecycleHook(LifecyclePhase.STOPPING, noop))
        await reg.run_stopping()
        with pytest.raises(LifecycleInvariantError):
            await reg.run_stopping()

    asyncio.run(run())


def test_inv_stopping_lifo_under_failure() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        order: list[str] = []

        async def ok() -> None:
            order.append("ok")

        async def bad() -> None:
            order.append("bad-entered")
            raise RuntimeError("drain boom")

        reg.register(LifecycleHook(LifecyclePhase.STOPPING, ok))
        reg.register(LifecycleHook(LifecyclePhase.STOPPING, bad))
        # LIFO: bad fires first, raises, ok still drains.
        await reg.run_stopping()
        assert order == ["bad-entered", "ok"]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# LIFE_INV_03 — failing STARTING prevents READY
# ---------------------------------------------------------------------------
def test_inv_failing_start_blocks_ready_confirms() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()

        async def fail() -> None:
            raise RuntimeError("nope")

        async def ready() -> None:
            pass

        reg.register(LifecycleHook(LifecyclePhase.STARTING, fail))
        reg.register(LifecycleHook(LifecyclePhase.READY, ready))
        with pytest.raises(RuntimeError):
            await reg.run_starting()
        with pytest.raises(LifecycleInvariantError):
            await reg.run_ready()

    asyncio.run(run())


def test_inv_failing_start_blocks_ready_prevents() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()

        async def fail() -> None:
            raise RuntimeError("nope")

        reg.register(LifecycleHook(LifecyclePhase.STARTING, fail))
        with pytest.raises(RuntimeError):
            await reg.run_starting()
        # After a failure, subsequent run_starting() is also refused.
        with pytest.raises(LifecycleInvariantError):
            await reg.run_starting()

    asyncio.run(run())


def test_inv_failing_start_blocks_ready_under_failure() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        ran_ready: list[bool] = []

        async def fail() -> None:
            raise ValueError("startup")

        async def ready() -> None:
            ran_ready.append(True)

        reg.register(LifecycleHook(LifecyclePhase.STARTING, fail))
        reg.register(LifecycleHook(LifecyclePhase.READY, ready))
        with pytest.raises(ValueError):
            await reg.run_starting()
        # Stopping path still runs even if starting failed.
        await reg.run_stopping()
        assert ran_ready == []

    asyncio.run(run())


# ---------------------------------------------------------------------------
# LIFE_INV_04 — timeout enforced
# ---------------------------------------------------------------------------
def test_inv_timeout_enforced_confirms() -> None:
    async def run() -> None:
        reg = LifecycleRegistry(default_timeout_s=0.05)

        async def quick() -> None:
            await asyncio.sleep(0.001)

        reg.register(LifecycleHook(LifecyclePhase.STARTING, quick))
        await reg.run_starting()

    asyncio.run(run())


def test_inv_timeout_enforced_prevents() -> None:
    async def run() -> None:
        reg = LifecycleRegistry(default_timeout_s=0.05)

        async def slow() -> None:
            await asyncio.sleep(5.0)

        reg.register(LifecycleHook(LifecyclePhase.STARTING, slow))
        with pytest.raises(LifecycleInvariantError):
            await reg.run_starting()

    asyncio.run(run())


def test_inv_timeout_enforced_under_failure() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        # Zero / negative timeouts rejected at registration.
        async def x() -> None:
            pass
        h = LifecycleHook(LifecyclePhase.STARTING, x)
        with pytest.raises(LifecycleInvariantError):
            reg.register(h, timeout_s=0.0)
        with pytest.raises(LifecycleInvariantError):
            reg.register(h, timeout_s=-1.0)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# LIFE_INV_05 — no re-registration within same phase
# ---------------------------------------------------------------------------
def test_inv_no_reentry_confirms() -> None:
    async def noop() -> None:
        pass

    reg = LifecycleRegistry()
    h1 = LifecycleHook(LifecyclePhase.STARTING, noop)
    h2 = LifecycleHook(LifecyclePhase.STARTING, noop)
    reg.register(h1)
    # Same callback object re-registered within STARTING MUST raise.
    with pytest.raises(LifecycleInvariantError):
        reg.register(h2)


def test_inv_no_reentry_prevents() -> None:
    reg = LifecycleRegistry()
    with pytest.raises(LifecycleInvariantError):
        reg.register("not a hook")  # type: ignore[arg-type]


def test_inv_no_reentry_under_failure() -> None:
    async def noop() -> None:
        pass

    reg = LifecycleRegistry()
    # Same callback in two different phases is allowed.
    h1 = LifecycleHook(LifecyclePhase.STARTING, noop)
    h2 = LifecycleHook(LifecyclePhase.STOPPING, noop)
    reg.register(h1)
    reg.register(h2)
    assert len(reg.hooks_for(LifecyclePhase.STARTING)) == 1
    assert len(reg.hooks_for(LifecyclePhase.STOPPING)) == 1
