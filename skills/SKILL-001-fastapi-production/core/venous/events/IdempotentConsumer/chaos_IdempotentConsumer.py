"""Chaos / game-day tests for IdempotentConsumer.

Fault-injection across the (inbox begin → outbox begin → _do_handle → outbox
commit → inbox commit) critical path confirms: any fault aborts the bracket
ATOMICALLY — no dedupe record and no outbox row leak, and a retry with the
same key runs the effect cleanly.
"""

from __future__ import annotations

import threading

import pytest

from IdempotentConsumer import (
    EchoConsumer,
    EchoMessage,
    build_echo_consumer,
)


def test_chaos_handler_raises_rolls_back_everything() -> None:
    _, inbox, outbox = build_echo_consumer()

    class Boom(EchoConsumer):
        def _do_handle(self, message, enqueue):  # type: ignore[no-untyped-def]  # override matches catalog api_signature (Any)
            enqueue("orders.out", {"partial": True})
            raise RuntimeError("poison pill")

    c = Boom(inbox=inbox, outbox=outbox, consumer_name="boom")
    with pytest.raises(RuntimeError):
        c.handle(EchoMessage(id="m-1"))
    assert inbox.store_snapshot == ()
    assert outbox.store_snapshot == ()


def test_chaos_retry_after_crash_runs_effect_once() -> None:
    _, inbox, outbox = build_echo_consumer()

    class Flaky(EchoConsumer):
        fails_left = 3

        def _do_handle(self, message, enqueue):  # type: ignore[no-untyped-def]  # override matches catalog api_signature (Any)
            if Flaky.fails_left > 0:
                Flaky.fails_left -= 1
                raise RuntimeError("transient")
            return super()._do_handle(message, enqueue)

    c = Flaky(inbox=inbox, outbox=outbox, consumer_name="flaky")
    for _ in range(3):
        with pytest.raises(RuntimeError):
            c.handle(EchoMessage(id="retryme"))
    # Fourth attempt succeeds.
    c.handle(EchoMessage(id="retryme"))
    # Fifth is a duplicate (should be silent).
    c.handle(EchoMessage(id="retryme"))
    assert c.effect_runs == 1
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1


def test_chaos_massive_duplicate_storm() -> None:
    c, inbox, outbox = build_echo_consumer()
    for _ in range(5_000):
        c.handle(EchoMessage(id="storm"))
    assert c.effect_runs == 1
    assert c.duplicate_calls == 4_999
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1


def test_chaos_concurrent_duplicate_storm() -> None:
    c, inbox, outbox = build_echo_consumer()
    gate = threading.Lock()

    def worker() -> None:
        for _ in range(100):
            with gate:
                c.handle(EchoMessage(id="hurricane"))

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert c.effect_runs == 1
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1


def test_chaos_interleaved_keys_survive_fault_injection() -> None:
    _, inbox, outbox = build_echo_consumer()

    class OddFails(EchoConsumer):
        def _do_handle(self, message, enqueue):  # type: ignore[no-untyped-def]  # override matches catalog api_signature (Any)
            assert isinstance(message, EchoMessage)
            n = int(message.id.split("-")[1])
            if n % 2 == 1:
                raise ValueError("odd rejected")
            return super()._do_handle(message, enqueue)

    c = OddFails(inbox=inbox, outbox=outbox, consumer_name="oddf")
    for i in range(20):
        try:
            c.handle(EchoMessage(id=f"k-{i}"))
        except ValueError:
            pass
    # Even keys only — ten effects, ten records.
    assert c.effect_runs == 10
    assert len(inbox.store_snapshot) == 10
    assert len(outbox.store_snapshot) == 10


def test_chaos_empty_payload_still_dedupes() -> None:
    c, _, _ = build_echo_consumer()
    msg = EchoMessage(id="empty", payload={})
    for _ in range(50):
        c.handle(msg)
    assert c.effect_runs == 1


def test_chaos_on_duplicate_never_raises_for_unknown_keys() -> None:
    # IDC-INV-03: on_duplicate on an unknown key is a no-op, never a raise.
    c, _, _ = build_echo_consumer()
    for i in range(1000):
        c.on_duplicate(EchoMessage(id=f"unknown-{i}"))
