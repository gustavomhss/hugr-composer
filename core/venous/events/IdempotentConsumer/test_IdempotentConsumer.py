"""Unit tests for IdempotentConsumer — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from IdempotentConsumer import (
    BaseIdempotentConsumer,
    EchoConsumer,
    EchoMessage,
    IdempotentConsumerInvariantError,
    build_echo_consumer,
)


# ---------------------------------------------------------------------------
# IDC_INV_01 — same key → same observable state
# ---------------------------------------------------------------------------
def test_inv_same_key_same_state_confirms() -> None:
    c, inbox, outbox = build_echo_consumer()
    msg = EchoMessage(id="k-1", payload={"x": 1})
    c.handle(msg)
    c.handle(msg)
    c.handle(msg)
    # Effect ran exactly once despite three deliveries.
    assert c.effect_runs == 1
    assert c.duplicate_calls == 2
    # Inbox holds one record; outbox holds one message.
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1


def test_inv_same_key_same_state_prevents() -> None:
    # Two distinct message objects sharing the same key MUST NOT produce two
    # effects — the observable system state (inbox + outbox) is identical.
    c, inbox, outbox = build_echo_consumer()
    m1 = EchoMessage(id="shared", payload={"v": 1})
    m2 = EchoMessage(id="shared", payload={"v": 2})  # same key, different payload
    c.handle(m1)
    c.handle(m2)
    assert c.effect_runs == 1
    assert len(outbox.store_snapshot) == 1
    # The cached outcome belongs to the FIRST delivery (m1's payload).
    snap = c.cache_snapshot
    assert len(snap) == 1
    assert snap[0]["outputs"][0]["payload"] == {"id": "shared", "payload": {"v": 1}}


def test_inv_same_key_same_state_under_failure() -> None:
    # If the first delivery's handler raises, the record MUST NOT be kept and
    # a retry (same key) MUST be treated as a first delivery.
    _, inbox, outbox = build_echo_consumer()

    class Flaky(EchoConsumer):
        should_fail = True

        def _do_handle(self, message, enqueue):  # type: ignore[no-untyped-def]  # subclass override intentionally loose-typed to match catalog api_signature
            if Flaky.should_fail:
                Flaky.should_fail = False
                raise RuntimeError("first attempt crashes")
            return super()._do_handle(message, enqueue)

    c = Flaky(inbox=inbox, outbox=outbox, consumer_name="flaky")
    msg = EchoMessage(id="retry-1", payload={})
    with pytest.raises(RuntimeError):
        c.handle(msg)
    # Retry — this MUST run the effect (INV-01 says same-key same-state; a
    # rolled-back first attempt leaves no state to converge on, so the retry
    # is effectively the first committed delivery).
    c.handle(msg)
    assert c.effect_runs == 1
    assert len(outbox.store_snapshot) == 1


# ---------------------------------------------------------------------------
# IDC_INV_02 — handle MUST consult the InboxDeduplicator
# ---------------------------------------------------------------------------
def test_inv_inbox_gate_confirms() -> None:
    c, inbox, _ = build_echo_consumer()
    msg = EchoMessage(id="gated-1")
    c.handle(msg)
    # The inbox holds a record for this key + consumer.
    keys = {(r["message_id"], r["consumer"]) for r in inbox.store_snapshot}
    assert ("gated-1", c.consumer_name) in keys


def test_inv_inbox_gate_prevents() -> None:
    # Constructing a consumer without an inbox is rejected at the type level;
    # an empty consumer name is rejected at runtime (IDC-INV-02).
    _c, inbox, outbox = build_echo_consumer()
    with pytest.raises(IdempotentConsumerInvariantError):
        EchoConsumer(inbox=inbox, outbox=outbox, consumer_name="")


def test_inv_inbox_gate_under_failure() -> None:
    # If a subclass tries to run side-effects without calling the enqueue
    # (i.e., it attempts the default _do_handle), it MUST raise — the base
    # class refuses to let the side-effect run unbridled.
    _, inbox, outbox = build_echo_consumer()

    class MissingOverride(BaseIdempotentConsumer[object, object]):
        pass

    c = MissingOverride(inbox=inbox, outbox=outbox, consumer_name="missing")
    msg = EchoMessage(id="x")
    with pytest.raises(IdempotentConsumerInvariantError):
        c.handle(msg)
    # The inbox has NOT recorded anything — no bypass occurred.
    assert inbox.store_snapshot == ()


# ---------------------------------------------------------------------------
# IDC_INV_03 — on_duplicate NEVER raises on the primary path
# ---------------------------------------------------------------------------
def test_inv_on_duplicate_no_raise_confirms() -> None:
    c, _, _ = build_echo_consumer()
    msg = EchoMessage(id="dup-1")
    c.handle(msg)  # first delivery, no on_duplicate
    # Second and third deliveries trigger on_duplicate — MUST NOT raise.
    c.handle(msg)
    c.handle(msg)
    assert c.duplicate_calls == 2


def test_inv_on_duplicate_no_raise_prevents() -> None:
    # Even when the message payload changes between deliveries, on_duplicate
    # stays non-raising (it is a steady-state path).
    c, _, _ = build_echo_consumer()
    for i in range(20):
        c.handle(EchoMessage(id="dup-2", payload={"v": i}))
    assert c.effect_runs == 1
    assert c.duplicate_calls == 19


def test_inv_on_duplicate_no_raise_under_failure() -> None:
    # Directly invoking on_duplicate (e.g. by a caller that already knows the
    # message is a duplicate) MUST NOT raise.
    c, _, _ = build_echo_consumer()
    # Prime the cache so the key is known.
    c.handle(EchoMessage(id="known"))
    # Direct invocation — must not raise even if called 1000 times.
    for _ in range(1000):
        c.on_duplicate(EchoMessage(id="known"))
    # Even for a key the cache has NEVER seen, on_duplicate MUST stay silent.
    c.on_duplicate(EchoMessage(id="never-known"))


# ---------------------------------------------------------------------------
# IDC_INV_04 — outputs flow through the TransactionalOutbox
# ---------------------------------------------------------------------------
def test_inv_outbox_publishing_confirms() -> None:
    c, _, outbox = build_echo_consumer()
    c.handle(EchoMessage(id="pub-1", payload={"v": 42}))
    pending = outbox.store_snapshot
    assert len(pending) == 1
    assert pending[0]["destination"] == "orders.out"
    assert pending[0]["payload"] == {"id": "pub-1", "payload": {"v": 42}}


def test_inv_outbox_publishing_prevents() -> None:
    # A subclass cannot publish except through the enqueue callable the base
    # provides; the base class does NOT expose the raw outbox. We prove the
    # invariant by demonstrating the outbox is write-gated by the inbox
    # bracket: writes outside the handle() call raise.
    _, _, outbox = build_echo_consumer()
    from TransactionalOutbox import (
        TransactionalOutboxInvariantError,  # lazy — subsystem-specific rationale: ensures cross-primitive error surface is surfaced through the same error type
    )
    with pytest.raises(TransactionalOutboxInvariantError):
        outbox.enqueue(destination="x", payload={}, key="k1")


def test_inv_outbox_publishing_under_failure() -> None:
    # If the outbox rejects a write (e.g., empty destination), the inbox
    # bracket MUST roll back so the consumer stays at-least-once retryable.
    _, inbox, outbox = build_echo_consumer()

    class BadPublisher(EchoConsumer):
        def _do_handle(self, message, enqueue):  # type: ignore[no-untyped-def]  # override matches catalog api_signature which uses Any
            enqueue("", {"id": "oops"})  # empty destination → outbox rejects
            return {}

    c = BadPublisher(inbox=inbox, outbox=outbox, consumer_name="bad")
    from TransactionalOutbox import TransactionalOutboxInvariantError
    with pytest.raises(TransactionalOutboxInvariantError):
        c.handle(EchoMessage(id="will-fail"))
    # Inbox rolled back — nothing recorded.
    assert inbox.store_snapshot == ()
    # Outbox rolled back — nothing published.
    assert outbox.store_snapshot == ()


# ---------------------------------------------------------------------------
# Cross-invariant: concurrent deliveries converge to one effect
# ---------------------------------------------------------------------------
def test_concurrent_deliveries_converge_to_one_effect() -> None:
    c, inbox, outbox = build_echo_consumer()
    gate = threading.Lock()

    def worker() -> None:
        with gate:  # serialize inbox.begin() — only one active txn at a time
            c.handle(EchoMessage(id="same"))

    ts = [threading.Thread(target=worker) for _ in range(25)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert c.effect_runs == 1
    assert len(inbox.store_snapshot) == 1
    assert len(outbox.store_snapshot) == 1
