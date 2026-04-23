"""Unit tests for CommandBus.

Covers the three named invariants declared in ``CommandBus.py``:
CB_INV_01 register-then-dispatch, CB_INV_02 last-registrant-wins,
CB_INV_03 unknown-name rejection.
"""
from __future__ import annotations

import asyncio

import pytest

from CommandBus import CommandBus


# ---------------------------------------------------------------------------
# CB_INV_01 — register + dispatch
# ---------------------------------------------------------------------------
def test_inv_register_confirms() -> None:
    """Registered handler is invoked for its command class name."""
    bus = CommandBus()

    seen: list[object] = []

    async def handler(cmd: object, **kwargs: object) -> str:
        seen.append(cmd)
        return "handled"

    class CreateItem:
        def __init__(self, title: str) -> None:
            self.title = title

    bus.register("CreateItem", handler)
    cmd = CreateItem("first")
    result = asyncio.run(bus.dispatch(cmd))

    assert result == "handled"
    assert seen == [cmd]


def test_dispatch_forwards_kwargs() -> None:
    """Extra kwargs on dispatch reach the handler verbatim."""
    bus = CommandBus()

    captured: dict[str, object] = {}

    async def handler(cmd: object, **kwargs: object) -> None:
        captured.update(kwargs)

    class Ping:
        pass

    bus.register("Ping", handler)
    asyncio.run(bus.dispatch(Ping(), correlation_id="c-1", principal="alice"))
    assert captured == {"correlation_id": "c-1", "principal": "alice"}


# ---------------------------------------------------------------------------
# CB_INV_02 — last-registrant-wins
# ---------------------------------------------------------------------------
def test_inv_register_prevents() -> None:
    """Re-registering the same command name replaces the previous handler."""
    bus = CommandBus()

    calls: list[str] = []

    async def h1(cmd: object) -> str:
        calls.append("h1")
        return "h1"

    async def h2(cmd: object) -> str:
        calls.append("h2")
        return "h2"

    class X:
        pass

    bus.register("X", h1)
    bus.register("X", h2)  # replaces h1
    result = asyncio.run(bus.dispatch(X()))
    assert result == "h2"
    assert calls == ["h2"]


# ---------------------------------------------------------------------------
# CB_INV_03 — unknown name rejection + failure propagation
# ---------------------------------------------------------------------------
def test_inv_register_under_failure() -> None:
    """Unknown command raises KeyError; handler errors propagate as-is."""
    bus = CommandBus()

    class GhostCommand:
        pass

    with pytest.raises(KeyError, match="GhostCommand"):
        asyncio.run(bus.dispatch(GhostCommand()))

    # Registered handler that raises: the error surfaces to the caller
    # unchanged (no silent retry, no wrapping).
    async def failing(cmd: object) -> None:
        raise RuntimeError("domain error")

    class Work:
        pass

    bus.register("Work", failing)
    with pytest.raises(RuntimeError, match="domain error"):
        asyncio.run(bus.dispatch(Work()))


def test_slots_prevent_accidental_state() -> None:
    """__slots__ is part of the contract — no stray attributes allowed."""
    bus = CommandBus()
    with pytest.raises(AttributeError):
        bus.extra = 1  # type: ignore[attr-defined]
