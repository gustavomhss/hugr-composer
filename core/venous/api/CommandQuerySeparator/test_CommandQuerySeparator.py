"""Unit tests for CommandQuerySeparator — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import pytest
from CommandQuerySeparator import (
    CommandAck,
    CQSInvariantError,
    InMemoryCQS,
    ReadModel,
    validate_ack_payload,
)


# ---------------------------------------------------------------------------
# CQS_INV_01 — command handler returns ack-only (never a projection)
# ---------------------------------------------------------------------------
class _PlaceOrder:
    def __init__(self, order_id: str) -> None:
        self.order_id = order_id


class _BadProjectionCmd:
    pass


def test_inv_command_ack_only_confirms() -> None:
    cqs = InMemoryCQS()

    def handler(cmd: object) -> CommandAck:
        assert isinstance(cmd, _PlaceOrder)
        evt = cqs.emit_event("PlaceOrder", {"order_id": cmd.order_id})
        return CommandAck(ack=True, status="accepted", ids=(cmd.order_id,), event_offset=evt.offset)

    cqs.register_command_handler(_PlaceOrder, handler)
    result = cqs.dispatch_command(_PlaceOrder("o-1"))
    assert isinstance(result, CommandAck)
    assert result.status == "accepted"
    assert result.ids == ("o-1",)


def test_inv_command_ack_only_prevents() -> None:
    cqs = InMemoryCQS()

    def bad(cmd: object) -> dict[str, object]:
        # Returns a projection — MUST be rejected.
        return {"order_id": "o-1", "customer_name": "Alice", "total_cents": 9900}

    cqs.register_command_handler(_BadProjectionCmd, bad)
    with pytest.raises(CQSInvariantError, match="CQS-INV-01"):
        cqs.dispatch_command(_BadProjectionCmd())


def test_inv_command_ack_only_under_failure() -> None:
    # Direct payload validation: invalid shapes MUST raise loudly.
    with pytest.raises(CQSInvariantError):
        validate_ack_payload({"projection_field": "leak"})
    with pytest.raises(CQSInvariantError):
        validate_ack_payload(CommandAck(ack=True, status="weird-status"))
    with pytest.raises(CQSInvariantError):
        validate_ack_payload(object())
    # Valid shapes MUST NOT raise.
    validate_ack_payload(None)
    validate_ack_payload(CommandAck(ack=True, status="accepted"))
    validate_ack_payload({"ack": True, "status": "accepted", "ids": ["a"]})


# ---------------------------------------------------------------------------
# CQS_INV_02 — query handler is side-effect free
# ---------------------------------------------------------------------------
class _GetOrder:
    def __init__(self, order_id: str) -> None:
        self.order_id = order_id


class _BadMutatingQuery:
    pass


def test_inv_query_side_effect_free_confirms() -> None:
    cqs = InMemoryCQS()

    def qh(query: object) -> dict[str, object]:
        assert isinstance(query, _GetOrder)
        return {"order_id": query.order_id, "status": "accepted"}

    cqs.register_query_handler(_GetOrder, qh)
    pre = len(cqs.event_stream.events)
    out = cqs.answer_query(_GetOrder("o-1"))
    post = len(cqs.event_stream.events)
    assert out == {"order_id": "o-1", "status": "accepted"}
    assert pre == post  # no mutation


def test_inv_query_side_effect_free_prevents() -> None:
    cqs = InMemoryCQS()

    def bad_query(query: object) -> dict[str, object]:
        # Illegal: the query writes to the event stream.
        cqs.emit_event("LeakyQueryWrite", {"leak": True})
        return {"ok": True}

    cqs.register_query_handler(_BadMutatingQuery, bad_query)
    with pytest.raises(CQSInvariantError, match="CQS-INV-02"):
        cqs.answer_query(_BadMutatingQuery())


def test_inv_query_side_effect_free_under_failure() -> None:
    cqs = InMemoryCQS()

    def crasher(query: object) -> object:
        raise RuntimeError("downstream")

    cqs.register_query_handler(_GetOrder, crasher)
    pre = len(cqs.event_stream.events)
    with pytest.raises(RuntimeError):
        cqs.answer_query(_GetOrder("o-99"))
    # Even when the handler crashes, no event stream mutation leaked through.
    assert len(cqs.event_stream.events) == pre


# ---------------------------------------------------------------------------
# CQS_INV_03 — at most one handler per command type
# ---------------------------------------------------------------------------
class _CmdA:
    pass


class _CmdB:
    pass


def test_inv_single_command_handler_confirms() -> None:
    cqs = InMemoryCQS()

    def h_a(cmd: object) -> CommandAck:
        return CommandAck(ack=True, status="accepted")

    def h_b(cmd: object) -> CommandAck:
        return CommandAck(ack=True, status="accepted")

    cqs.register_command_handler(_CmdA, h_a)
    cqs.register_command_handler(_CmdB, h_b)
    assert set(cqs.command_types) == {_CmdA, _CmdB}


def test_inv_single_command_handler_prevents() -> None:
    cqs = InMemoryCQS()

    def h1(cmd: object) -> CommandAck:
        return CommandAck(ack=True, status="accepted")

    def h2(cmd: object) -> CommandAck:
        return CommandAck(ack=True, status="accepted")

    cqs.register_command_handler(_CmdA, h1)
    with pytest.raises(CQSInvariantError, match="CQS-INV-03"):
        cqs.register_command_handler(_CmdA, h2)


def test_inv_single_command_handler_under_failure() -> None:
    cqs = InMemoryCQS()

    # Non-class command_type and non-callable handler MUST be refused.
    with pytest.raises(CQSInvariantError):
        cqs.register_command_handler("not-a-class", lambda c: None)  # type: ignore[arg-type]  # CQS-INV-03 supporting: deliberately malformed to prove rejection.
    with pytest.raises(CQSInvariantError):
        cqs.register_command_handler(_CmdA, 42)  # type: ignore[arg-type]  # CQS-INV-03 supporting: non-callable handler MUST be rejected.


# ---------------------------------------------------------------------------
# CQS_INV_04 — read models fed ONLY via the event stream
# ---------------------------------------------------------------------------
class _EventingCmd:
    def __init__(self, customer_id: str) -> None:
        self.customer_id = customer_id


def test_inv_event_stream_only_confirms() -> None:
    cqs = InMemoryCQS()
    rm = ReadModel(name="orders_by_customer")
    cqs.register_read_model(rm)

    def handler(cmd: object) -> CommandAck:
        assert isinstance(cmd, _EventingCmd)
        evt = cqs.emit_event("CustomerRegistered", {"customer_id": cmd.customer_id})
        return CommandAck(ack=True, status="accepted", event_offset=evt.offset)

    cqs.register_command_handler(_EventingCmd, handler)
    cqs.dispatch_command(_EventingCmd("c-1"))
    # Read model populated via the event stream, not by an in-band write.
    assert len(rm.state) == 1


def test_inv_event_stream_only_prevents() -> None:
    rm = ReadModel(name="projection")
    with pytest.raises(CQSInvariantError, match="CQS-INV-04"):
        rm.direct_write("order-1", {"status": "leaked"})


def test_inv_event_stream_only_under_failure() -> None:
    cqs = InMemoryCQS()
    rm = ReadModel(name="projection")
    cqs.register_read_model(rm)
    # Replaying the same event MUST NOT double-apply (monotonic offsets).
    evt = cqs.emit_event("Noop", {"k": 1})
    rm.apply_event(evt)  # replay — should be ignored
    assert len(rm.state) == 1
