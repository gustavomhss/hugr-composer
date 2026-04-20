"""Behavioral scenarios for SamplingPolicy."""

from __future__ import annotations

from SamplingPolicy import (
    AlwaysOffSampler,
    AlwaysOnSampler,
    ParentBasedHeadSampler,
    SamplingDecision,
)


def _go(sampler: object, trace: str = "a" * 32, parent: object | None = None) -> SamplingDecision:
    return sampler.should_sample(  # type: ignore[attr-defined]
        parent_context=parent, trace_id=trace, name="op", kind="INTERNAL",
        attributes={}, links=(),
    )


def test_scenario_parent_sampled_child_follows() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.0)
    d = _go(s, parent={"sampled": True})
    assert d.sampled


def test_scenario_no_parent_probabilistic() -> None:
    s = ParentBasedHeadSampler(head_ratio=1.0)
    d = _go(s)
    assert d.sampled


def test_scenario_always_off_drops_everything() -> None:
    s = AlwaysOffSampler()
    for _ in range(10):
        assert _go(s).sampled is False


def test_scenario_always_on_keeps_everything() -> None:
    s = AlwaysOnSampler()
    for _ in range(10):
        assert _go(s).sampled is True


def test_scenario_deterministic_across_siblings() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)
    trace = "deadbeef" * 4
    names = ["a", "b", "c", "d"]
    decisions = {_go(s, trace=trace).sampled for _ in names}
    assert len(decisions) == 1


def test_scenario_description_is_compact() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.1)
    assert len(s.description()) < 200
