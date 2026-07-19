"""Unit tests for SamplingPolicy."""

from __future__ import annotations

import pytest
from SamplingPolicy import (
    MAX_DESCRIPTION_LEN,
    AlwaysOffSampler,
    AlwaysOnSampler,
    ParentBasedHeadSampler,
    SamplingDecision,
    SamplingInvariantError,
)


def _call(sampler: object, **overrides: object) -> SamplingDecision:
    kwargs: dict = {
        "parent_context": None,
        "trace_id": "a" * 32,
        "name": "op",
        "kind": "INTERNAL",
        "attributes": {},
        "links": (),
    }
    kwargs.update(overrides)
    return sampler.should_sample(**kwargs)  # type: ignore[attr-defined]


# SAMP_INV_01 — parent inheritance
def test_inv_parent_inheritance_confirms() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.0)
    d = _call(sampler, parent_context={"sampled": True})
    assert d.sampled is True
    assert d.attributes["sampler.reason"] == "parent"


def test_inv_parent_inheritance_prevents() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.0, parent_override=True)
    d = _call(sampler, parent_context={"sampled": True})
    # parent_override=True → DOES NOT inherit parent sampled flag.
    assert d.sampled is False


def test_inv_parent_inheritance_under_failure() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.0)
    d = _call(sampler, parent_context={"broken": "no-sampled-key"})
    # Missing 'sampled' key → treated as not sampled.
    assert d.sampled is False


# SAMP_INV_02 — deterministic per trace_id
def test_inv_deterministic_decision_confirms() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    trace = "abcdef1234567890" * 2
    first = _call(sampler, trace_id=trace).sampled
    for _ in range(20):
        assert _call(sampler, trace_id=trace).sampled == first


def test_inv_deterministic_decision_prevents() -> None:
    import secrets

    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    # Random trace_ids are expected to produce both decisions.
    decisions = {_call(sampler, trace_id=secrets.token_hex(16)).sampled for _ in range(200)}
    assert decisions == {True, False}


def test_inv_deterministic_decision_under_failure() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    # Even with invalid trace_id, the sampler returns SOMETHING (never raises).
    for bad in ("", "x", "NOTHEX", None):
        try:
            d = sampler.should_sample(
                parent_context=None, trace_id=bad, name="o", kind="I",  # type: ignore[arg-type]
                attributes={}, links=(),
            )
            assert isinstance(d, SamplingDecision)
        except Exception:
            pytest.fail("sampler MUST NOT raise")


# SAMP_INV_03 — trace_id hash, not per-span
def test_inv_trace_id_hash_confirms() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    trace = "00" * 16
    d1 = _call(sampler, trace_id=trace, name="a")
    d2 = _call(sampler, trace_id=trace, name="b")
    # Same trace → same sampling decision across different span names.
    assert d1.sampled == d2.sampled


def test_inv_trace_id_hash_prevents() -> None:
    import secrets

    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    traces = [secrets.token_hex(16) for _ in range(200)]
    sampled = [_call(sampler, trace_id=t).sampled for t in traces]
    assert True in sampled and False in sampled


def test_inv_trace_id_hash_under_failure() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    # Edge trace_ids all produce stable results.
    for tid in ("0" * 32, "f" * 32, "deadbeef" * 4):
        assert _call(sampler, trace_id=tid).sampled == _call(sampler, trace_id=tid).sampled


# SAMP_INV_04 — never raise; fallback deny + counter
def test_inv_never_raises_confirms() -> None:
    with pytest.raises(SamplingInvariantError):
        ParentBasedHeadSampler(head_ratio=-0.1)
    with pytest.raises(SamplingInvariantError):
        ParentBasedHeadSampler(head_ratio=2.0)


def test_inv_never_raises_prevents() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    # Pass in an object that raises on attribute access.
    class Broken:
        def get(self, key):  # type: ignore[no-untyped-def]
            raise RuntimeError("sabotage")
    d = sampler.should_sample(
        parent_context=Broken(), trace_id="a"*32, name="n", kind="INTERNAL",
        attributes={}, links=(),
    )
    assert d.sampled is False


def test_inv_never_raises_under_failure() -> None:
    sampler = ParentBasedHeadSampler(head_ratio=0.5)
    # Fallback counter increments on broken context.
    class Broken:
        def get(self, key):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")
    before = sampler.fallback_count
    for _ in range(5):
        sampler.should_sample(
            parent_context=Broken(), trace_id="a"*32, name="n", kind="I",
            attributes={}, links=(),
        )
    assert sampler.fallback_count == before + 5


# SAMP_INV_05 — tail-based does not modify exported spans
def test_inv_tail_before_export_confirms() -> None:
    # Protocol-level: AlwaysOnSampler does not retroactively change decisions.
    s = AlwaysOnSampler()
    d = _call(s)
    assert d.sampled
    # A follow-up call with the same inputs yields the same decision.
    assert _call(s).sampled


def test_inv_tail_before_export_prevents() -> None:
    s = AlwaysOffSampler()
    # OFF sampler never retroactively sets True.
    for _ in range(10):
        assert _call(s).sampled is False


def test_inv_tail_before_export_under_failure() -> None:
    s = AlwaysOnSampler()
    # Sampler decision is a pure function; running twice doesn't change.
    d1 = _call(s)
    d2 = _call(s)
    assert d1.sampled == d2.sampled


# SAMP_INV_06 — description safe + bounded
def test_inv_description_safe_confirms() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.25)
    desc = s.description()
    assert "ratio" in desc
    assert len(desc) <= MAX_DESCRIPTION_LEN


def test_inv_description_safe_prevents() -> None:
    s = ParentBasedHeadSampler(head_ratio=0.5)
    desc = s.description()
    # Does not contain obvious secrets.
    for forbidden in ("password", "api_key", "Bearer "):
        assert forbidden not in desc


def test_inv_description_safe_under_failure() -> None:
    s = AlwaysOnSampler()
    # AlwaysOnSampler description is short and stable.
    assert s.description() == "always_on"
