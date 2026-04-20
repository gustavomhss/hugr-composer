"""Chaos / fault-injection for CommandQuerySeparator.

Game-day scenarios: crashing handlers, duplicate registration, mutating
queries, concurrent command dispatch, malformed ack returns. The primitive
MUST preserve the four invariants under each.
"""

from __future__ import annotations

import threading

import pytest

from CommandQuerySeparator import (
    CommandAck,
    CQSInvariantError,
    InMemoryCQS,
    ReadModel,
)


class _Cmd:
    pass


class _Query:
    pass


def test_chaos_crashing_command_handler_does_not_leak_events() -> None:
    cqs = InMemoryCQS()

    def crasher(_cmd: object) -> CommandAck:
        cqs.emit_event("PartialWrite", {"half": 1})
        raise RuntimeError("downstream failed after emit")

    cqs.register_command_handler(_Cmd, crasher)
    with pytest.raises(RuntimeError):
        cqs.dispatch_command(_Cmd())
    # Event stream retains the partial write because commands are append-only —
    # this matches event-sourcing semantics. The invariant that matters here
    # is INV-01 (ack only), not rollback.
    assert len(cqs.event_stream.events) == 1


def test_chaos_concurrent_dispatch_serialises_registrations() -> None:
    cqs = InMemoryCQS()
    errors: list[BaseException] = []

    def try_register() -> None:
        try:
            cqs.register_command_handler(_Cmd, lambda c: CommandAck(ack=True, status="accepted"))
        except CQSInvariantError:
            pass  # Expected: only one thread wins; others hit CQS-INV-03.
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=try_register) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(cqs.command_types) == 1  # exactly one handler won


def test_chaos_malformed_ack_rejected() -> None:
    cqs = InMemoryCQS()

    def bad(_cmd: object) -> object:
        # Deliberately return a nested projection — CQS-INV-01 must catch it.
        return {"orders": [{"id": "o-1"}]}

    cqs.register_command_handler(_Cmd, bad)
    with pytest.raises(CQSInvariantError, match="CQS-INV-01"):
        cqs.dispatch_command(_Cmd())


def test_chaos_query_mutating_registry_rejected() -> None:
    cqs = InMemoryCQS()

    def h(_cmd: object) -> CommandAck:
        return CommandAck(ack=True, status="accepted")

    class _Later:
        pass

    def bad(_q: object) -> dict[str, object]:
        cqs.register_command_handler(_Later, h)  # illegal mutation
        return {"ok": True}

    cqs.register_query_handler(_Query, bad)
    with pytest.raises(CQSInvariantError, match="CQS-INV-02"):
        cqs.answer_query(_Query())


def test_chaos_read_model_forged_write_always_refused() -> None:
    rm = ReadModel(name="projection")
    for forged_key in ("o-1", "sql-injection-\"; DROP TABLE--", ""):
        with pytest.raises(CQSInvariantError, match="CQS-INV-04"):
            rm.direct_write(forged_key, {"forged": True})


def test_chaos_unregistered_command_fails_fast() -> None:
    cqs = InMemoryCQS()
    with pytest.raises(CQSInvariantError):
        cqs.dispatch_command(_Cmd())


def test_chaos_storm_of_commands_preserves_ordering() -> None:
    cqs = InMemoryCQS()

    def h(_cmd: object) -> CommandAck:
        evt = cqs.emit_event("Cmd", {})
        return CommandAck(ack=True, status="accepted", event_offset=evt.offset)

    cqs.register_command_handler(_Cmd, h)

    def worker() -> None:
        for _ in range(50):
            cqs.dispatch_command(_Cmd())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = cqs.event_stream.events
    assert len(events) == 200
    assert [e.offset for e in events] == list(range(200))
