"""Behavioral end-to-end scenarios for IdempotentConsumer — proves invariants at runtime."""

from __future__ import annotations

import pytest

from IdempotentConsumer import (
    BaseIdempotentConsumer,
    EchoConsumer,
    EchoMessage,
    IdempotentConsumerInvariantError,
    build_echo_consumer,
)


def test_scenario_at_least_once_transport_yields_exactly_once_effect() -> None:
    """The classic Richardson/Kleppmann scenario: broker redelivers 5× and
    the business effect applies EXACTLY once."""
    c, inbox, outbox = build_echo_consumer()
    msg = EchoMessage(id="order-42", payload={"amount": 100, "sku": "A1"})
    for _ in range(5):
        c.handle(msg)
    assert c.effect_runs == 1
    assert c.duplicate_calls == 4
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1


def test_scenario_distinct_keys_each_run_once() -> None:
    c, inbox, outbox = build_echo_consumer()
    for i in range(10):
        c.handle(EchoMessage(id=f"order-{i}", payload={"v": i}))
    assert c.effect_runs == 10
    assert c.duplicate_calls == 0
    assert len(inbox.store_snapshot) == 10
    assert len(outbox.store_snapshot) == 10


def test_scenario_mixed_first_and_duplicate_deliveries_interleaved() -> None:
    c, _, outbox = build_echo_consumer()
    deliveries = ["a", "b", "a", "c", "b", "a", "d"]
    for k in deliveries:
        c.handle(EchoMessage(id=k))
    # Four unique keys → four effects; three duplicates.
    assert c.effect_runs == 4
    assert c.duplicate_calls == 3
    assert len(outbox.store_snapshot) == 4


def test_scenario_handler_failure_does_not_leak_dedupe_record() -> None:
    _, inbox, outbox = build_echo_consumer()

    class Exploding(EchoConsumer):
        def _do_handle(self, message, enqueue):  # type: ignore[no-untyped-def]  # override loose-typed to match catalog Any surface
            raise RuntimeError("kaboom")

    c = Exploding(inbox=inbox, outbox=outbox, consumer_name="exploder")
    with pytest.raises(RuntimeError):
        c.handle(EchoMessage(id="bad"))
    # No dedupe record, no outbox row — the next attempt can retry cleanly.
    assert inbox.store_snapshot == ()
    assert outbox.store_snapshot == ()


def test_scenario_on_duplicate_is_steady_state_silent() -> None:
    # Massive flood of duplicates — MUST NOT raise and MUST NOT leak any state.
    c, inbox, outbox = build_echo_consumer()
    msg = EchoMessage(id="flood")
    c.handle(msg)
    for _ in range(500):
        c.handle(msg)
    assert c.effect_runs == 1
    assert c.duplicate_calls == 500
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1


def test_scenario_downstream_receives_dedupe_friendly_keys() -> None:
    """Downstream consumers of the outbox get keyed messages they can
    themselves dedupe by (key, sequence)."""
    c, _, outbox = build_echo_consumer()
    c.handle(EchoMessage(id="o-1", payload={"v": "hello"}))
    pending = outbox.store_snapshot
    assert len(pending) == 1
    assert pending[0]["key"] == "o-1:0"
    assert pending[0]["destination"] == "orders.out"


def test_scenario_missing_override_refuses_to_apply_effect() -> None:
    """IDC-INV-02 + defensive programming: a subclass that forgot to
    override _do_handle MUST raise rather than silently no-op."""
    _, inbox, outbox = build_echo_consumer()

    class Incomplete(BaseIdempotentConsumer[object, object]):
        pass

    c = Incomplete(inbox=inbox, outbox=outbox, consumer_name="incomplete")
    with pytest.raises(IdempotentConsumerInvariantError):
        c.handle(EchoMessage(id="m"))
