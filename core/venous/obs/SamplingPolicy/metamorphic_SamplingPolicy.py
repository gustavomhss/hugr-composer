"""Metamorphic + differential for SamplingPolicy."""

from __future__ import annotations

import secrets

from SamplingPolicy import (
    AlwaysOffSampler,
    AlwaysOnSampler,
    ParentBasedHeadSampler,
)


def _call(s: object, trace: str) -> bool:
    return s.should_sample(  # type: ignore[attr-defined]
        parent_context=None, trace_id=trace, name="n", kind="I",
        attributes={}, links=(),
    ).sampled


def test_metamorphic_determinism_across_calls() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)
    trace = secrets.token_hex(16)
    first = _call(s, trace)
    for _ in range(50):
        assert _call(s, trace) == first


def test_metamorphic_rate_0_never_samples() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.0)
    for _ in range(50):
        assert _call(s, secrets.token_hex(16)) is False


def test_metamorphic_rate_1_always_samples() -> None:
    s = ParentBasedHeadSampler(head_ratio=1.0)
    for _ in range(50):
        assert _call(s, secrets.token_hex(16)) is True


def test_metamorphic_rate_is_monotone() -> None:
    low = ParentBasedHeadSampler(head_ratio=0.1)
    high = ParentBasedHeadSampler(head_ratio=0.9)
    traces = [secrets.token_hex(16) for _ in range(500)]
    low_hits = sum(_call(low, t) for t in traces)
    high_hits = sum(_call(high, t) for t in traces)
    assert high_hits > low_hits


def test_differential_always_on_vs_always_off() -> None:
    on = AlwaysOnSampler()
    off = AlwaysOffSampler()
    for _ in range(10):
        t = secrets.token_hex(16)
        assert _call(on, t) is True
        assert _call(off, t) is False


def test_metamorphic_description_stable() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)
    first = s.description()
    for _ in range(5):
        assert s.description() == first
