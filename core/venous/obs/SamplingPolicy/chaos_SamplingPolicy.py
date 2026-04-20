"""Chaos tests for SamplingPolicy."""

from __future__ import annotations

import threading

import pytest

from SamplingPolicy import ParentBasedHeadSampler, SamplingInvariantError


def test_chaos_invalid_rate_rejected() -> None:
    with pytest.raises(SamplingInvariantError):
        ParentBasedHeadSampler(head_ratio=-1.0)
    with pytest.raises(SamplingInvariantError):
        ParentBasedHeadSampler(head_ratio=1.5)


def test_chaos_concurrent_decisions_stable() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)
    trace = "f" * 32
    results: list[bool] = []

    def worker() -> None:
        for _ in range(100):
            d = s.should_sample(
                parent_context=None, trace_id=trace, name="n", kind="I",
                attributes={}, links=(),
            )
            results.append(d.sampled)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All 400 results must agree (same trace_id → same decision).
    assert len(set(results)) == 1


def test_chaos_broken_parent_never_raises() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)

    class Broken:
        def get(self, key):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    d = s.should_sample(
        parent_context=Broken(), trace_id="a" * 32, name="n", kind="I",
        attributes={}, links=(),
    )
    assert d.sampled is False


def test_chaos_empty_trace_id_fallback_deny() -> None:
    s = ParentBasedHeadSampler(head_ratio=1.0)
    d = s.should_sample(
        parent_context=None, trace_id="", name="n", kind="I",
        attributes={}, links=(),
    )
    # Empty trace_id → bucket=1.0 >= ratio 1.0 → not sampled.
    assert d.sampled is False


def test_chaos_malformed_trace_id_does_not_crash() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)
    for bad in ("", "x", "zzzzzzzz", "<>!"):
        d = s.should_sample(
            parent_context=None, trace_id=bad, name="n", kind="I",
            attributes={}, links=(),
        )
        # never raises; decision is well-formed.
        assert d.sampled in (True, False)


def test_chaos_description_never_includes_state() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.25)
    # Even after many decisions, description remains stable (not a log of events).
    for _ in range(10):
        s.should_sample(parent_context=None, trace_id="a"*32, name="n", kind="I",
                        attributes={}, links=())
    desc = s.description()
    assert "sampled" not in desc.lower()
