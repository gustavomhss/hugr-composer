"""Verdict logic tests — each decision rule exercised."""

from __future__ import annotations

from engine.promotion.classify import (
    _classify_single,
    _motor_is_registered,
    _motor_name,
)
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


def _unpack(result):
    """Adapter for 6-tuple return."""
    return result[0], result[1], result[2], result[3], result[4], result[5]


def test_rule1_duplicate_is_redundant():
    state = _s(duplicate_of_registered="Bulkhead")
    v, _, rat, _, delete_reason, _ = _unpack(_classify_single(state, []))
    assert v == Verdict.REDUNDANT
    assert "Bulkhead" in rat
    assert delete_reason is not None


def test_rule2_framework_coupled_motor_and_adapter_both_registered_is_redundant(
    monkeypatch,
):
    """When both motor and adapter exist, staged item is redundant."""
    import engine.promotion.classify as m

    monkeypatch.setattr(m, "_adapter_exists", lambda _: True)
    state = _s(name="BulkheadMiddleware", framework_imports=["starlette"])
    v, _, rat, _, delete_reason, _ = _unpack(
        _classify_single(state, [], registered_names={"Bulkhead"})
    )
    assert v == Verdict.REDUNDANT
    assert "Bulkhead" in rat
    assert delete_reason is not None


def test_rule3_framework_coupled_motor_registered_adapter_missing_promotes_as_adapter(
    monkeypatch,
):
    """Motor registered but adapter missing → promote staged as adapter."""
    import engine.promotion.classify as m

    monkeypatch.setattr(m, "_adapter_exists", lambda _: False)
    state = _s(name="BulkheadMiddleware", framework_imports=["starlette"])
    v, tier, rat, _, _, target = _unpack(_classify_single(state, [], registered_names={"Bulkhead"}))
    assert v == Verdict.PROMOTE_AS_ADAPTER
    assert tier == "adapter"
    assert target == "core/venous/_adapters/fastapi/BulkheadAdapter.py"
    assert "BulkheadAdapter" in rat


def test_rule4_framework_coupled_no_motor_registers_extract_motor_pair():
    state = _s(name="CORSConfigMiddleware", framework_imports=["starlette"])
    v, _, rat, _, _, _ = _unpack(_classify_single(state, [], registered_names={"Bulkhead"}))
    assert v == Verdict.EXTRACT_MOTOR_PAIR
    assert "CORSConfig" in rat or "motor" in rat.lower()


def test_rule4_no_suffix_extract_motor_pair_still_valid():
    state = _s(name="FooBar", framework_imports=["fastapi"])
    v, _, rat, _, _, _ = _unpack(_classify_single(state, [], registered_names=set()))
    assert v == Verdict.EXTRACT_MOTOR_PAIR
    assert "manually" in rat or "No common framework suffix" in rat


def test_rule5_quarantined_non_framework_needs_review():
    state = _s(is_quarantined=True, quarantine_reason="too_small")
    v, _, _, staging_reason, _, _ = _unpack(_classify_single(state, []))
    assert v == Verdict.NEEDS_REVIEW
    assert staging_reason is not None


def test_rule6_no_signal_needs_caller():
    state = _s(origin_tool="some/tool.py")
    v, _, _, staging_reason, _, _ = _unpack(_classify_single(state, []))
    assert v == Verdict.NEEDS_CALLER
    assert staging_reason is not None
    assert "§A12" in staging_reason or "caller" in staging_reason.lower()


def test_rule7_signal_but_shell_incomplete_fill_and_promote():
    state = _s(replace_me_count=5, invariants_stubbed=True)
    v, _, rat, _, _, _ = _unpack(_classify_single(state, [_sig()]))
    assert v == Verdict.FILL_AND_PROMOTE
    assert "REPLACE_ME" in rat or "shell" in rat.lower()


def test_rule8_signal_clean_concurrent_promotes_primitive_full():
    state = _s(has_concurrency=True, namespace="resiliency", name="Foo")
    v, tier, _, _, _, target = _unpack(_classify_single(state, [_sig()]))
    assert v == Verdict.PROMOTE_AS_PRIMITIVE
    assert tier == "full"
    assert target == "core/venous/resiliency/Foo/"


def test_rule9_signal_clean_stateless_promotes_primitive_lite():
    state = _s(namespace="api", name="Bar")
    v, tier, _, _, _, target = _unpack(_classify_single(state, [_sig()]))
    assert v == Verdict.PROMOTE_AS_PRIMITIVE
    assert tier == "lite"
    assert target == "core/venous/api/Bar/"


def test_motor_name_strips_known_suffixes():
    assert _motor_name("BulkheadMiddleware") == "Bulkhead"
    assert _motor_name("AdminAuthBackend") == "AdminAuth"
    assert _motor_name("FooAdapter") == "Foo"
    assert _motor_name("WebhookDispatcher") == "Webhook"
    assert _motor_name("SomeHandler") == "Some"


def test_motor_name_returns_none_on_no_match():
    assert _motor_name("Bulkhead") is None
    assert _motor_name("Middleware") is None
    assert _motor_name("X") is None
    assert _motor_name("Foo") is None


def test_motor_is_registered_hits():
    reg = {"Bulkhead", "Webhook"}
    assert _motor_is_registered("BulkheadMiddleware", reg) == "Bulkhead"
    assert _motor_is_registered("WebhookDispatcher", reg) == "Webhook"


def test_motor_is_registered_misses():
    reg = {"Bulkhead"}
    assert _motor_is_registered("FooAdapter", reg) is None
    assert _motor_is_registered("NoSuffix", reg) is None


def test_weak_signal_kind_does_not_count_as_strong():
    state = _s()
    weak = Signal(kind=SignalKind.GENERATOR_REF, source="adapt/tool.py", detail="")
    v, _, _, staging_reason, _, _ = _unpack(_classify_single(state, [weak]))
    assert v == Verdict.NEEDS_CALLER
    assert staging_reason is not None
