"""Metamorphic tests for LegalHold."""

from __future__ import annotations

from datetime import datetime, timezone

from LegalHold import InMemoryLegalHoldRegistry, LegalHold


class _NoopSink:
    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: object) -> str:
        return ""


UTC = timezone.utc


def _h(**o: object) -> LegalHold:
    base: dict[str, object] = {
        "hold_id": "h1", "scope_query": "record_id = 'x'",
        "opened_at": datetime.now(UTC), "opened_by": "c",
    }
    base.update(o)
    return LegalHold(**base)  # type: ignore[arg-type]


def test_metamorphic_release_monotonic() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(_h())
    assert r.size == 1
    r.release("h1", released_by="ops")
    assert r.size == 0
    # Second release raises; state unchanged.
    import pytest

    from LegalHold import LegalHoldError
    with pytest.raises(LegalHoldError):
        r.release("h1", released_by="ops")


def test_metamorphic_covers_idempotent() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(_h())
    a = r.covers("x")
    b = r.covers("x")
    assert a == b is True


def test_metamorphic_two_aliases_isolated() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(_h(hold_id="h1"))
    r.open(_h(hold_id="h2", scope_query="record_id = 'y'"))
    assert r.covers("x") and r.covers("y")
    r.release("h1", released_by="ops")
    assert r.covers("x") is False and r.covers("y") is True


def test_differential_like_vs_equal_scope() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(_h(scope_query="record_id LIKE 'user:%'"))
    assert r.covers("user:42") is True
    assert r.covers("other:1") is False


def test_metamorphic_open_release_reopen() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(_h())
    r.release("h1", released_by="ops")
    # Re-opening the same hold id is allowed (previously released).
    r.open(_h())
    assert r.covers("x") is True
