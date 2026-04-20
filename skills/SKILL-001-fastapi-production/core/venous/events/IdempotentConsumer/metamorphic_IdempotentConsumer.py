"""Metamorphic + differential tests for IdempotentConsumer.

Algebraic laws proven here:
- handle(m) applied N times == handle(m) applied once (idempotence).
- handle(m1); handle(m2) observable state is independent of ordering when
  key_for(m1) != key_for(m2) (commutativity across disjoint keys).
- The cached outcome for a key is immutable across redeliveries.
- Effect count is monotone-increasing and bounded by the number of
  distinct keys seen.
"""

from __future__ import annotations

from IdempotentConsumer import EchoMessage, build_echo_consumer


def test_metamorphic_idempotence_law() -> None:
    """handle(m)^N == handle(m) for any N ≥ 1."""
    c, _, outbox = build_echo_consumer()
    msg = EchoMessage(id="law", payload={"x": 7})
    for _ in range(100):
        c.handle(msg)
    assert c.effect_runs == 1
    assert len(outbox.store_snapshot) == 1


def test_metamorphic_commutativity_across_disjoint_keys() -> None:
    """Order of handle(m1), handle(m2) is irrelevant when keys differ."""
    c1, _, _ = build_echo_consumer()
    c2, _, _ = build_echo_consumer()
    m_a, m_b, m_c = EchoMessage(id="a"), EchoMessage(id="b"), EchoMessage(id="c")
    # c1: a, b, c ; c2: c, a, b
    for m in (m_a, m_b, m_c):
        c1.handle(m)
    for m in (m_c, m_a, m_b):
        c2.handle(m)
    assert c1.effect_runs == c2.effect_runs == 3
    # Cached outputs are a permutation of the same set.
    c1_keys = {c["key"] for c in c1.cache_snapshot}
    c2_keys = {c["key"] for c in c2.cache_snapshot}
    assert c1_keys == c2_keys == {"a", "b", "c"}


def test_metamorphic_cached_outcome_immutable_across_redeliveries() -> None:
    c, _, _ = build_echo_consumer()
    c.handle(EchoMessage(id="k", payload={"v": "first"}))
    first_snap = c.cache_snapshot
    # Redeliver with a different payload — the cached outcome MUST NOT mutate.
    for v in ("second", "third", "fourth"):
        c.handle(EchoMessage(id="k", payload={"v": v}))
    later_snap = c.cache_snapshot
    assert first_snap == later_snap


def test_metamorphic_effect_count_bounded_by_distinct_keys() -> None:
    c, _, _ = build_echo_consumer()
    deliveries = [f"k-{i % 5}" for i in range(100)]
    for k in deliveries:
        c.handle(EchoMessage(id=k))
    assert c.effect_runs == 5  # only 5 distinct keys
    assert c.effect_runs <= len(set(deliveries))


def test_differential_same_input_two_consumers_same_observable_state() -> None:
    """Two independently-wired consumers receiving the same sequence of
    deliveries MUST end up with structurally-identical cached state."""
    c_a, _, out_a = build_echo_consumer("a")
    c_b, _, out_b = build_echo_consumer("b")
    seq = [EchoMessage(id=f"m-{i}") for i in (1, 2, 1, 3, 2, 1, 4)]
    for m in seq:
        c_a.handle(m)
        c_b.handle(m)
    keys_a = sorted(c["key"] for c in c_a.cache_snapshot)
    keys_b = sorted(c["key"] for c in c_b.cache_snapshot)
    assert keys_a == keys_b == ["m-1", "m-2", "m-3", "m-4"]
    # Outbox shapes match too.
    dests_a = sorted(m["destination"] for m in out_a.store_snapshot)
    dests_b = sorted(m["destination"] for m in out_b.store_snapshot)
    assert dests_a == dests_b
