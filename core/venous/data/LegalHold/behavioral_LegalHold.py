"""Behavioral scenarios for LegalHold."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from LegalHold import InMemoryLegalHoldRegistry, LegalHold, LegalHoldError


class _NoopSink:
    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: object) -> str:
        return ""


UTC = timezone.utc


def test_scenario_litigation_hold_blocks_erasure() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(LegalHold(
        hold_id="case-2024-1138",
        scope_query="record_id = 'tenant:acme:user:*'",
        opened_at=datetime.now(UTC),
        opened_by="counsel@acme.com",
    ))
    assert r.covers("tenant:acme:user:42") is True
    assert r.covers("tenant:other:user:1") is False


def test_scenario_release_requires_distinct_actor() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(LegalHold(
        hold_id="h1", scope_query="record_id = 'x'",
        opened_at=datetime.now(UTC), opened_by="a",
    ))
    with pytest.raises(LegalHoldError):
        r.release("h1", released_by="a")


def test_scenario_release_with_override_allowed() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(LegalHold(
        hold_id="h1", scope_query="record_id = 'x'",
        opened_at=datetime.now(UTC), opened_by="a",
    ))
    r.release("h1", released_by="a", override=True)
    assert r.size == 0


def test_scenario_unknown_field_in_scope_rejected() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    with pytest.raises(LegalHoldError):
        r.open(LegalHold(
            hold_id="bad", scope_query="bogus_field = 'x'",
            opened_at=datetime.now(UTC), opened_by="c",
        ))


def test_scenario_two_holds_compose() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(LegalHold(
        hold_id="h1", scope_query="record_id = 'a'",
        opened_at=datetime.now(UTC), opened_by="c1",
    ))
    r.open(LegalHold(
        hold_id="h2", scope_query="record_id = 'b'",
        opened_at=datetime.now(UTC), opened_by="c2",
    ))
    assert r.covers("a") and r.covers("b")
