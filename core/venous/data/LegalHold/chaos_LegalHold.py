"""Chaos tests for LegalHold."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from LegalHold import InMemoryLegalHoldRegistry, LegalHold, LegalHoldError


class _NoopSink:
    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: object) -> str:
        return ""


UTC = timezone.utc


def _h(**o: object) -> LegalHold:
    base: dict[str, object] = {
        "hold_id": "h", "scope_query": "record_id = 'x'",
        "opened_at": datetime.now(UTC), "opened_by": "c",
    }
    base.update(o)
    return LegalHold(**base)  # type: ignore[arg-type]


def test_chaos_double_open_rejected() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    r.open(_h())
    with pytest.raises(LegalHoldError):
        r.open(_h())


def test_chaos_release_nonexistent_rejected() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    with pytest.raises(LegalHoldError):
        r.release("nope", released_by="ops")


def test_chaos_empty_scope_query_rejected() -> None:
    with pytest.raises(LegalHoldError):
        _h(scope_query="")


def test_chaos_naive_opened_at_rejected() -> None:
    with pytest.raises(LegalHoldError):
        _h(opened_at=datetime(2026, 1, 1))


def test_chaos_unknown_scope_field_repeatedly_rejected() -> None:
    r = InMemoryLegalHoldRegistry(audit_sink=_NoopSink())
    for bad in ("foo = 'x'", "random_field = 'y'"):
        with pytest.raises(LegalHoldError):
            r.open(_h(scope_query=bad))
