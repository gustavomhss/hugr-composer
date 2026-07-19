"""Unit tests — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import pytest
from FeatureToggle import (
    FeatureToggleInvariantError,
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


class CountingToggle:
    """Impure toggle used to prove FT-INV-01 about caller-visible purity."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.calls = 0

    def is_active(self, ctx: ToggleContext) -> bool:
        self.calls += 1
        return ctx.environment == "prod"


_CTX = ToggleContext(principal_id="u", tenant_id="t", environment="prod")


# ---------------------------------------------------------------------------
# FT_INV_01 — purity of is_active
# ---------------------------------------------------------------------------
def test_inv_pure_evaluation_confirms() -> None:
    reg = FeatureToggleRegistry()
    t = StaticToggle("hot_feature", True)
    reg.register(t)
    # Same (key, ctx) → same result.
    assert reg.is_active("hot_feature", _CTX) is True
    assert reg.is_active("hot_feature", _CTX) is True


def test_inv_pure_evaluation_prevents() -> None:
    reg = FeatureToggleRegistry()
    with pytest.raises(FeatureToggleInvariantError):
        reg.is_active("anything", "not-a-context")  # type: ignore[arg-type]


def test_inv_pure_evaluation_under_failure() -> None:
    class BrokenToggle:
        key = "broken_toggle"

        def is_active(self, ctx: ToggleContext) -> bool:
            raise RuntimeError("provider outage")

    reg = FeatureToggleRegistry()
    reg.register(BrokenToggle())
    # FT-INV-02: broken evaluation resolves to False, never raises out.
    assert reg.is_active("broken_toggle", _CTX) is False


# ---------------------------------------------------------------------------
# FT_INV_02 — off by default on unreachable store
# ---------------------------------------------------------------------------
def test_inv_off_by_default_confirms() -> None:
    reg = FeatureToggleRegistry()
    # Unknown key.
    assert reg.is_active("never_registered", _CTX) is False


def test_inv_off_by_default_prevents() -> None:
    # Cannot force on by monkey-wiring: registry never defaults True.
    reg = FeatureToggleRegistry()
    for key in ("x_a", "yet_another_key", "zzz_one"):
        assert reg.is_active(key, _CTX) is False


def test_inv_off_by_default_under_failure() -> None:
    class BrokenToggle:
        key = "broken2"

        def is_active(self, ctx: ToggleContext) -> bool:
            raise ValueError("provider down")

    reg = FeatureToggleRegistry()
    reg.register(BrokenToggle())
    for _ in range(100):
        assert reg.is_active("broken2", _CTX) is False


# ---------------------------------------------------------------------------
# FT_INV_03 — unique key + naming convention
# ---------------------------------------------------------------------------
def test_inv_key_uniqueness_confirms() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("good_key", True))
    with pytest.raises(FeatureToggleInvariantError):
        reg.register(StaticToggle("good_key", False))


def test_inv_key_uniqueness_prevents() -> None:
    # Bad key shapes rejected.
    for bad in ("", "X", "Has-Dash", "has.dot", "1starts_with_digit", "a" * 100, "ab"):
        with pytest.raises(FeatureToggleInvariantError):
            validate_key(bad)


def test_inv_key_uniqueness_under_failure() -> None:
    reg = FeatureToggleRegistry()
    # Registering with an invalid key fails even if the underlying object exists.
    with pytest.raises(FeatureToggleInvariantError):
        reg.register(StaticToggle("Bad-Key", True))
    # Registry remained empty.
    assert len(reg.known_keys()) == 0


# ---------------------------------------------------------------------------
# FT_INV_04 — every evaluation recorded
# ---------------------------------------------------------------------------
def test_inv_audit_recorded_confirms() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("traced_a", True))
    reg.register(StaticToggle("traced_b", False))
    for _ in range(3):
        reg.is_active("traced_a", _CTX)
        reg.is_active("traced_b", _CTX)
        reg.is_active("unknown_c", _CTX)
    assert len(reg.audit) == 9
    a_entries = [e for e in reg.audit if e.key == "traced_a"]
    assert all(e.decision is True for e in a_entries)


def test_inv_audit_recorded_prevents() -> None:
    # Every call, regardless of outcome, MUST be audited.
    reg = FeatureToggleRegistry()

    class BrokenToggle:
        key = "ledger_one"

        def is_active(self, ctx: ToggleContext) -> bool:
            raise RuntimeError("nope")

    reg.register(BrokenToggle())
    for _ in range(5):
        reg.is_active("ledger_one", _CTX)
    assert len(reg.audit) == 5
    assert all(e.decision is False for e in reg.audit)


def test_inv_audit_recorded_under_failure() -> None:
    reg = FeatureToggleRegistry()
    # Unknown-key calls still produce an audit entry.
    for i in range(10):
        reg.is_active(f"missing_{i:02d}", _CTX)
    assert len(reg.audit) == 10


# ---------------------------------------------------------------------------
# FT_INV_05 — two-step deprecation
# ---------------------------------------------------------------------------
def test_inv_two_step_delete_confirms() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("to_remove", True))
    reg.mark_stale("to_remove")
    assert reg.is_stale("to_remove")
    reg.delete("to_remove")
    assert "to_remove" not in reg.known_keys()


def test_inv_two_step_delete_prevents() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("abrupt_delete", True))
    # Deletion without prior stale flag is rejected.
    with pytest.raises(FeatureToggleInvariantError):
        reg.delete("abrupt_delete")
    # Stale a key that does not exist → error.
    with pytest.raises(FeatureToggleInvariantError):
        reg.mark_stale("ghost_key")


def test_inv_two_step_delete_under_failure() -> None:
    reg = FeatureToggleRegistry()
    reg.register(StaticToggle("partial_delete", False))
    reg.mark_stale("partial_delete")
    # Calling mark_stale twice is a no-op (idempotent).
    reg.mark_stale("partial_delete")
    # Double-delete rejected (second delete hits unknown-key branch).
    reg.delete("partial_delete")
    with pytest.raises(FeatureToggleInvariantError):
        reg.delete("partial_delete")
