"""Behavioral end-to-end scenarios."""

from __future__ import annotations

import pytest

from FeatureToggle import (
    FeatureToggleInvariantError,
    FeatureToggleRegistry,
    ToggleContext,
)


class TenantToggle:
    def __init__(self, key: str, allowed_tenants: frozenset[str]) -> None:
        self.key = key
        self._allowed = allowed_tenants

    def is_active(self, ctx: ToggleContext) -> bool:
        return ctx.tenant_id in self._allowed


def test_scenario_tenant_rollout_lifecycle() -> None:
    reg = FeatureToggleRegistry()
    reg.register(TenantToggle("beta_feature", frozenset({"acme", "globex"})))
    acme = ToggleContext(principal_id="u1", tenant_id="acme", environment="prod")
    other = ToggleContext(principal_id="u2", tenant_id="init", environment="prod")
    assert reg.is_active("beta_feature", acme) is True
    assert reg.is_active("beta_feature", other) is False


def test_scenario_unknown_key_is_off_and_audited() -> None:
    reg = FeatureToggleRegistry()
    ctx = ToggleContext(principal_id=None, tenant_id=None, environment="dev")
    for _ in range(5):
        assert reg.is_active("not_registered", ctx) is False
    assert len(reg.audit) == 5


def test_scenario_deprecation_flow() -> None:
    class T:
        key = "aging_feature"

        def is_active(self, ctx: ToggleContext) -> bool:
            return True

    reg = FeatureToggleRegistry()
    reg.register(T())
    ctx = ToggleContext(principal_id="a", tenant_id="b", environment="prod")
    assert reg.is_active("aging_feature", ctx) is True
    reg.mark_stale("aging_feature")
    assert reg.is_stale("aging_feature")
    # Still evaluable while stale (code references remain safe).
    assert reg.is_active("aging_feature", ctx) is True
    reg.delete("aging_feature")
    # After delete, unknown-key → False.
    assert reg.is_active("aging_feature", ctx) is False


def test_scenario_broken_provider_fails_closed() -> None:
    class Broken:
        key = "brittle_feature"

        def is_active(self, ctx: ToggleContext) -> bool:
            raise ConnectionError("store unreachable")

    reg = FeatureToggleRegistry()
    reg.register(Broken())
    ctx = ToggleContext(principal_id=None, tenant_id=None, environment="prod")
    for _ in range(20):
        assert reg.is_active("brittle_feature", ctx) is False


def test_scenario_audit_contains_full_context() -> None:
    class T:
        key = "logged_on"

        def is_active(self, ctx: ToggleContext) -> bool:
            return True

    reg = FeatureToggleRegistry()
    reg.register(T())
    ctx = ToggleContext(
        principal_id="alice", tenant_id="team-1", environment="staging"
    )
    reg.is_active("logged_on", ctx)
    entry = reg.audit[-1]
    assert entry.ctx_principal == "alice"
    assert entry.ctx_tenant == "team-1"
    assert entry.ctx_environment == "staging"
    assert entry.decision is True


def test_scenario_invalid_key_rejected_at_registration() -> None:
    class T:
        key = "Bad Key With Spaces"

        def is_active(self, ctx: ToggleContext) -> bool:
            return True

    reg = FeatureToggleRegistry()
    with pytest.raises(FeatureToggleInvariantError):
        reg.register(T())
