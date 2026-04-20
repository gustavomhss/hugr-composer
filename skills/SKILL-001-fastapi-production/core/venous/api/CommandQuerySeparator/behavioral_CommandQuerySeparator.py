"""Behavioral end-to-end scenarios for CommandQuerySeparator.

Each scenario drives the primitive through a realistic workflow and asserts
a named invariant outcome.
"""

from __future__ import annotations

import pytest

from CommandQuerySeparator import (
    CommandAck,
    CQSInvariantError,
    InMemoryCQS,
    ReadModel,
)


class _PlaceOrder:
    def __init__(self, order_id: str, cents: int) -> None:
        self.order_id = order_id
        self.cents = cents


class _CancelOrder:
    def __init__(self, order_id: str) -> None:
        self.order_id = order_id


class _GetOrderView:
    def __init__(self, order_id: str) -> None:
        self.order_id = order_id


def _wire_order_service() -> tuple[InMemoryCQS, ReadModel]:
    cqs = InMemoryCQS()
    rm = ReadModel(name="orders")
    cqs.register_read_model(rm)

    def place(cmd: object) -> CommandAck:
        assert isinstance(cmd, _PlaceOrder)
        evt = cqs.emit_event("OrderPlaced", {"order_id": cmd.order_id, "cents": cmd.cents})
        return CommandAck(ack=True, status="accepted", ids=(cmd.order_id,), event_offset=evt.offset)

    def cancel(cmd: object) -> CommandAck:
        assert isinstance(cmd, _CancelOrder)
        evt = cqs.emit_event("OrderCancelled", {"order_id": cmd.order_id})
        return CommandAck(ack=True, status="accepted", ids=(cmd.order_id,), event_offset=evt.offset)

    def view(query: object) -> dict[str, object]:
        assert isinstance(query, _GetOrderView)
        # Read-only traversal of the projection — MUST NOT mutate.
        for payload in rm.state.values():
            assert isinstance(payload, dict)
            if payload.get("order_id") == query.order_id:
                return dict(payload)
        return {}

    cqs.register_command_handler(_PlaceOrder, place)
    cqs.register_command_handler(_CancelOrder, cancel)
    cqs.register_query_handler(_GetOrderView, view)
    return cqs, rm


def test_scenario_place_then_query_roundtrip() -> None:
    cqs, _ = _wire_order_service()
    ack = cqs.dispatch_command(_PlaceOrder("o-1", 9900))
    assert isinstance(ack, CommandAck)
    view = cqs.answer_query(_GetOrderView("o-1"))
    assert isinstance(view, dict)
    assert view.get("order_id") == "o-1"


def test_scenario_command_ack_never_leaks_projection() -> None:
    cqs, _ = _wire_order_service()
    ack = cqs.dispatch_command(_PlaceOrder("o-2", 100))
    assert isinstance(ack, CommandAck)
    # The CommandAck carries ONLY ack metadata; no pricing/customer leak.
    as_dict = ack.as_dict()
    assert set(as_dict) == {"ack", "status", "ids", "event_offset"}


def test_scenario_multiple_read_models_receive_same_events() -> None:
    cqs, rm_primary = _wire_order_service()
    rm_secondary = ReadModel(name="orders_search")
    cqs.register_read_model(rm_secondary)
    cqs.dispatch_command(_PlaceOrder("o-3", 500))
    # Both projections saw the event via the shared stream (CQS-INV-04).
    assert len(rm_primary.state) == 1
    assert len(rm_secondary.state) == 1


def test_scenario_duplicate_command_registration_blocked() -> None:
    cqs = InMemoryCQS()

    def h(cmd: object) -> CommandAck:
        return CommandAck(ack=True, status="accepted")

    cqs.register_command_handler(_PlaceOrder, h)
    with pytest.raises(CQSInvariantError, match="CQS-INV-03"):
        cqs.register_command_handler(_PlaceOrder, h)


def test_scenario_query_replacement_is_permitted() -> None:
    cqs = InMemoryCQS()

    def v1(_q: object) -> dict[str, object]:
        return {"version": 1}

    def v2(_q: object) -> dict[str, object]:
        return {"version": 2}

    cqs.register_query_handler(_GetOrderView, v1)
    cqs.register_query_handler(_GetOrderView, v2)
    out = cqs.answer_query(_GetOrderView("o-1"))
    assert out == {"version": 2}


def test_scenario_query_attempting_write_is_rejected() -> None:
    cqs, _ = _wire_order_service()

    def bad(_q: object) -> dict[str, object]:
        cqs.emit_event("SneakyWrite", {"leak": True})
        return {"ok": True}

    cqs.register_query_handler(_CancelOrder, bad)  # misuse: registering a query on a command-shaped type still subject to INV-02
    with pytest.raises(CQSInvariantError, match="CQS-INV-02"):
        cqs.answer_query(_CancelOrder("o-x"))


def test_scenario_read_model_rejects_in_band_write() -> None:
    _, rm = _wire_order_service()
    with pytest.raises(CQSInvariantError, match="CQS-INV-04"):
        rm.direct_write("order-forged", {"status": "forged"})
