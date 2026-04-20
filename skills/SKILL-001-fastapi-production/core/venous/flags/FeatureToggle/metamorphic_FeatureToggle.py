"""Metamorphic + differential tests."""

from __future__ import annotations

from FeatureToggle import (
    FeatureToggleRegistry,
    ToggleContext,
    validate_key,
)


class StaticToggle:
    def __init__(self, key: str, value: bool) -> None:
        self.key = key
        self._value = value

    def is_active(self, ctx: ToggleContext) -> bool:
        return self._value


def test_metamorphic_identity_repeated_eval_stable() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("stable_feature", True))
    ctx = ToggleContext(principal_id="u", tenant_id="t", environment="prod")
    decisions = [reg.is_active("stable_feature", ctx) for _ in range(25)]
    assert all(d is True for d in decisions)


def test_metamorphic_audit_monotonic_growth() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("counted_feature", False))
    ctx = ToggleContext(principal_id=None, tenant_id=None, environment="dev")
    prev = 0
    for _ in range(10):
        reg.is_active("counted_feature", ctx)
        now = len(reg.audit)
        assert now == prev + 1
        prev = now


def test_differential_known_vs_unknown_key() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("truthy_toggle", True))
    ctx = ToggleContext(principal_id=None, tenant_id=None, environment="prod")
    # Known → True; unknown → False. Differential contract.
    assert reg.is_active("truthy_toggle", ctx) is True
    assert reg.is_active("unknown_flag", ctx) is False


def test_metamorphic_stale_does_not_change_evaluation() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("reachable_flag", True))
    ctx = ToggleContext(principal_id=None, tenant_id=None, environment="prod")
    before = reg.is_active("reachable_flag", ctx)
    reg.mark_stale("reachable_flag")
    after = reg.is_active("reachable_flag", ctx)
    assert before == after == True  # noqa: E712 — intentional identity assertion on bool


def test_differential_key_shape_rules() -> None:
    # Valid shapes.
    for k in ("abc", "ab_c", "a1", "a_1_b_2", "abc_def_ghi", "plain_name"):
        if len(k) >= 3 and len(k) <= 64:
            try:
                validate_key(k)
            except Exception:
                raise AssertionError(f"expected {k!r} to be valid")  # noqa: B904 — short re-raise in test
    # Invalid shapes.
    for k in ("", "A", "1abc", "ABCDEF", "ab-c", "ab.c", "a" * 200, " leading"):
        try:
            validate_key(k)
        except Exception:
            continue
        else:
            raise AssertionError(f"expected {k!r} to be rejected")


def test_metamorphic_audit_contains_ctx_triplet() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("traced_flag", True))
    for env in ("dev", "staging", "prod"):
        reg.is_active(
            "traced_flag",
            ToggleContext(principal_id="x", tenant_id="y", environment=env),
        )
    envs = [e.ctx_environment for e in reg.audit]
    assert envs == ["dev", "staging", "prod"]
