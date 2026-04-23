"""Unit tests for QueryBus (QB_INV_01..04)."""
from __future__ import annotations

import asyncio

import pytest

from QueryBus import QueryBus


def test_inv_register_confirms() -> None:
    """QB_INV_01 register-then-query: handler runs with the query."""
    bus = QueryBus()

    seen: list[object] = []

    async def handler(q: object) -> dict[str, str]:
        seen.append(q)
        return {"status": "ok"}

    class GetItem:
        def __init__(self, item_id: str) -> None:
            self.item_id = item_id

    bus.register("GetItem", handler)
    q = GetItem("42")
    result = asyncio.run(bus.query(q))
    assert result == {"status": "ok"}
    assert seen == [q]


def test_query_forwards_kwargs_to_handler() -> None:
    """Kwargs on `query(...)` reach the handler verbatim."""
    bus = QueryBus()

    captured: dict[str, object] = {}

    async def handler(q: object, **kwargs: object) -> None:
        captured.update(kwargs)

    class CheckAvail:
        pass

    bus.register("CheckAvail", handler)
    asyncio.run(bus.query(CheckAvail(), principal="alice", tenant="t1"))
    assert captured == {"principal": "alice", "tenant": "t1"}


def test_inv_register_prevents() -> None:
    """QB_INV_02 last-registrant-wins: re-register replaces handler."""
    bus = QueryBus()

    async def h1(q: object) -> str:
        return "h1"

    async def h2(q: object) -> str:
        return "h2"

    class X:
        pass

    bus.register("X", h1)
    bus.register("X", h2)
    assert asyncio.run(bus.query(X())) == "h2"


def test_inv_register_under_failure() -> None:
    """QB_INV_03 unknown-name: KeyError on unregistered queries."""
    bus = QueryBus()

    class GhostQuery:
        pass

    with pytest.raises(KeyError, match="GhostQuery"):
        asyncio.run(bus.query(GhostQuery()))


def test_handler_errors_propagate_unchanged() -> None:
    """QB_INV_04 implicit: read-errors surface to caller (no wrapping)."""
    bus = QueryBus()

    async def failing(q: object) -> None:
        raise ValueError("storage unavailable")

    class Read:
        pass

    bus.register("Read", failing)
    with pytest.raises(ValueError, match="storage unavailable"):
        asyncio.run(bus.query(Read()))


def test_slots_prevent_accidental_state() -> None:
    """__slots__ contract — no stray attributes allowed."""
    bus = QueryBus()
    with pytest.raises(AttributeError):
        bus.extra = 1  # type: ignore[attr-defined]
