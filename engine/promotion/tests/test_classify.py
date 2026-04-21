"""Verdict logic tests — each of the 8 decision rules exercised."""
from __future__ import annotations

from engine.promotion.classify import _classify_single
from engine.promotion.schemas import (
    Signal,
    SignalKind,
    StateFlags,
    Verdict,
)


def _s(**overrides) -> StateFlags:
    base = dict(
        name="X",
        namespace="api",
        is_quarantined=False,
        replace_me_count=0,
        has_tla=False,
        has_concurrency=False,
        has_mutable_class_state=False,
        loc=20,
        test_file_present=True,
        invariants_stubbed=False,
    )
    base.update(overrides)
    return StateFlags(**base)


def _sig(kind: SignalKind = SignalKind.TOOL_IMPORT) -> Signal:
    return Signal(kind=kind, source="adapt/tool.py", detail="x")


def test_rule1_duplicate_of_registered_deletes():
    state = _s(duplicate_of_registered="Bulkhead")
    verdict, tier, _, _, delete_reason = _classify_single(state, [])
    assert verdict == Verdict.DELETE
    assert tier == "none"
    assert delete_reason is not None
    assert "Bulkhead" in delete_reason


def test_rule2_quarantined_framework_coupled_deletes():
    state = _s(
        is_quarantined=True,
        forbidden_modules=["starlette.middleware.base"],
        quarantine_reason="domain_coupled",
    )
    verdict, _, _, _, delete_reason = _classify_single(state, [])
    assert verdict == Verdict.DELETE
    assert delete_reason is not None
    assert "starlette" in delete_reason


def test_rule3_quarantined_other_keep_staged():
    state = _s(is_quarantined=True, quarantine_reason="too_small")
    verdict, _, _, staging_reason, _ = _classify_single(state, [])
    assert verdict == Verdict.KEEP_STAGED
    assert staging_reason is not None


def test_rule4_no_signal_keep_staged():
    state = _s(origin_tool="some/tool.py")
    verdict, _, _, staging_reason, _ = _classify_single(state, [])
    assert verdict == Verdict.KEEP_STAGED
    assert staging_reason is not None
    assert "§A12" in staging_reason or "benchmark" in staging_reason.lower()


def test_rule5_signal_but_shell_incomplete_needs_review():
    state = _s(replace_me_count=5, invariants_stubbed=True)
    verdict, _, _, _, _ = _classify_single(state, [_sig()])
    assert verdict == Verdict.NEEDS_REVIEW


def test_rule6_signal_clean_concurrent_promotes_full():
    state = _s(has_concurrency=True)
    verdict, tier, _, _, _ = _classify_single(state, [_sig()])
    assert verdict == Verdict.PROMOTE_FULL
    assert tier == "full"


def test_rule7_signal_clean_stateless_promotes_lite():
    state = _s()  # all defaults: stateless, no concurrency, clean shell
    verdict, tier, _, _, _ = _classify_single(state, [_sig()])
    assert verdict == Verdict.PROMOTE_LITE
    assert tier == "lite"


def test_weak_signal_kind_does_not_count_as_strong():
    # Only GENERATOR_REF signal present — should be treated as no-signal.
    state = _s()
    weak = Signal(kind=SignalKind.GENERATOR_REF, source="adapt/tool.py", detail="")
    verdict, _, _, staging_reason, _ = _classify_single(state, [weak])
    assert verdict == Verdict.KEEP_STAGED
    assert staging_reason is not None
