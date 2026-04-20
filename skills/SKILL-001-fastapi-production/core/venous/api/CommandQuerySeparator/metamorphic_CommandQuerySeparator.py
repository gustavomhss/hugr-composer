"""Metamorphic + differential tests for CommandQuerySeparator.

Algebraic properties:
- query idempotency: answer_query(q) == answer_query(q) (no state change).
- command append-only monotonicity of the event stream.
- register + dispatch order independence across distinct command types.
- read-model replay idempotency (same event applied twice == applied once).
"""

from __future__ import annotations

from CommandQuerySeparator import (
    CommandAck,
    InMemoryCQS,
    ReadModel,
)


class _Cmd:
    def __init__(self, k: str) -> None:
        self.k = k


class _Query:
    def __init__(self, k: str) -> None:
        self.k = k


def _mk() -> InMemoryCQS:
    cqs = InMemoryCQS()

    def h(cmd: object) -> CommandAck:
        assert isinstance(cmd, _Cmd)
        evt = cqs.emit_event("Cmd", {"k": cmd.k})
        return CommandAck(ack=True, status="accepted", ids=(cmd.k,), event_offset=evt.offset)

    def q(query: object) -> dict[str, object]:
        assert isinstance(query, _Query)
        return {"k": query.k, "events": len(cqs.event_stream.events)}

    cqs.register_command_handler(_Cmd, h)
    cqs.register_query_handler(_Query, q)
    return cqs


def test_metamorphic_query_is_pure() -> None:
    cqs = _mk()
    cqs.dispatch_command(_Cmd("a"))
    out1 = cqs.answer_query(_Query("x"))
    out2 = cqs.answer_query(_Query("x"))
    assert out1 == out2


def test_metamorphic_command_stream_is_monotonic() -> None:
    cqs = _mk()
    offsets: list[int] = []
    for i in range(10):
        ack = cqs.dispatch_command(_Cmd(f"c-{i}"))
        assert isinstance(ack, CommandAck)
        assert ack.event_offset is not None
        offsets.append(ack.event_offset)
    assert offsets == sorted(offsets)
    assert offsets == list(range(10))


def test_metamorphic_register_order_independence() -> None:
    class _C1:
        pass

    class _C2:
        pass

    cqs_a = InMemoryCQS()
    cqs_b = InMemoryCQS()

    def h(cmd: object) -> CommandAck:
        return CommandAck(ack=True, status="accepted")

    cqs_a.register_command_handler(_C1, h)
    cqs_a.register_command_handler(_C2, h)
    cqs_b.register_command_handler(_C2, h)
    cqs_b.register_command_handler(_C1, h)
    assert set(cqs_a.command_types) == set(cqs_b.command_types)


def test_metamorphic_read_model_replay_idempotent() -> None:
    cqs = _mk()
    rm = ReadModel(name="p")
    cqs.register_read_model(rm)
    cqs.dispatch_command(_Cmd("a"))
    snapshot = dict(rm.state)
    # Replay all events — should be a no-op thanks to monotonic offsets.
    for evt in cqs.event_stream.events:
        rm.apply_event(evt)
    assert rm.state == snapshot


def test_differential_query_ack_shape_disjoint() -> None:
    cqs = _mk()
    ack = cqs.dispatch_command(_Cmd("a"))
    view = cqs.answer_query(_Query("a"))
    assert isinstance(ack, CommandAck)
    assert isinstance(view, dict)
    # The ack and the view inhabit disjoint shapes — CQS-INV-01 end-to-end.
    assert set(ack.as_dict()) & set(view) == set()
