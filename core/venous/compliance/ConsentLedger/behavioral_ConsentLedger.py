"""Behavioral scenarios for ConsentLedger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ConsentLedger import InMemoryConsentLedger


UTC = timezone.utc


def test_scenario_marketing_opt_in_then_out() -> None:
    led = InMemoryConsentLedger()
    led.grant("alice@ex.com", "marketing_email", "v2024-11", datetime(2026, 1, 1, tzinfo=UTC))
    assert led.is_granted("alice@ex.com", "marketing_email") is True
    led.revoke("alice@ex.com", "marketing_email", datetime(2026, 2, 1, tzinfo=UTC))
    assert led.is_granted("alice@ex.com", "marketing_email") is False


def test_scenario_per_purpose_granularity() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "marketing_email", "n1", datetime(2026, 1, 1, tzinfo=UTC))
    led.grant("s-1", "analytics_profiling", "n1", datetime(2026, 1, 1, tzinfo=UTC))
    led.revoke("s-1", "marketing_email", datetime(2026, 2, 1, tzinfo=UTC))
    at = datetime(2026, 3, 1, tzinfo=UTC)
    assert led.is_granted("s-1", "marketing_email", at) is False
    assert led.is_granted("s-1", "analytics_profiling", at) is True


def test_scenario_audit_reproduces_past_state() -> None:
    led = InMemoryConsentLedger()
    t_grant = datetime(2026, 1, 1, tzinfo=UTC)
    t_revoke = datetime(2026, 3, 1, tzinfo=UTC)
    led.grant("s-1", "p", "v1", t_grant)
    led.revoke("s-1", "p", t_revoke)
    # At an audit point before revoke, state reproduces.
    assert led.is_granted("s-1", "p", t_grant + timedelta(days=1)) is True


def test_scenario_history_preserves_every_action() -> None:
    led = InMemoryConsentLedger()
    led.grant("s-1", "p", "v1", datetime(2026, 1, 1, tzinfo=UTC))
    led.revoke("s-1", "p", datetime(2026, 2, 1, tzinfo=UTC))
    led.grant("s-1", "p", "v2", datetime(2026, 3, 1, tzinfo=UTC))
    assert len(led.history("s-1")) == 3


def test_scenario_unknown_subject_is_not_granted() -> None:
    led = InMemoryConsentLedger()
    assert led.is_granted("unknown", "p") is False


def test_scenario_actor_attribution_preserved() -> None:
    led = InMemoryConsentLedger()
    led.grant(
        "s-1", "p", "v1", datetime(2026, 1, 1, tzinfo=UTC),
        actor="support-agent-42",
    )
    assert led.history("s-1")[0]["actor"] == "support-agent-42"
