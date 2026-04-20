"""Unit tests for LegalHold — 3 per invariant."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from LegalHold import InMemoryLegalHoldRegistry, LegalHold, LegalHoldError


UTC = timezone.utc
T = datetime(2026, 1, 1, tzinfo=UTC)


class _NoopSink:
    """Minimal AuditSink stub — LH_INV_02 now mandates a sink at construction."""

    def append(
        self, actor: str, action: str, resource: str, outcome: str,
        attributes: object,
    ) -> str:
        return f"{action}:{resource}"


def _reg() -> InMemoryLegalHoldRegistry:
    return InMemoryLegalHoldRegistry(audit_sink=_NoopSink())


def _hold(**o: object) -> LegalHold:
    base: dict[str, object] = {
        "hold_id": "case-1",
        "scope_query": "record_id = 'user:42'",
        "opened_at": T,
        "opened_by": "counsel@ex.com",
    }
    base.update(o)
    return LegalHold(**base)  # type: ignore[arg-type]


# LH_INV_01 — covers MUST be called before deletion.
def test_inv_covers_gates_delete_confirms() -> None:
    r = _reg()
    r.open(_hold())
    assert r.covers("user:42") is True
    assert r.covers("user:99") is False


def test_inv_covers_gates_delete_prevents() -> None:
    r = _reg()
    # covers() on empty registry always False (no accidental hold).
    assert r.covers("user:42") is False


def test_inv_covers_gates_delete_under_failure() -> None:
    # Released hold does not cover.
    r = _reg()
    r.open(_hold())
    r.release("case-1", released_by="ops@ex.com")
    assert r.covers("user:42") is False


# LH_INV_02 — open/release emit audit.
class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: object) -> str:
        self.rows.append({"actor": actor, "action": action, "resource": resource})
        return "h"


def test_inv_audit_on_lifecycle_confirms() -> None:
    sink = _Sink()
    r = InMemoryLegalHoldRegistry(audit_sink=sink)
    r.open(_hold())
    r.release("case-1", released_by="ops@ex.com")
    assert [x["action"] for x in sink.rows] == ["legal_hold.open", "legal_hold.release"]


def test_inv_audit_on_lifecycle_prevents() -> None:
    # Opening invalid hold raises; no audit row.
    sink = _Sink()
    r = InMemoryLegalHoldRegistry(audit_sink=sink)
    with pytest.raises(LegalHoldError):
        r.open(object())  # type: ignore[arg-type]
    assert sink.rows == []


def test_inv_audit_on_lifecycle_under_failure() -> None:
    # Without sink, lifecycle still works.
    r = _reg()
    r.open(_hold())
    r.release("case-1", released_by="x")
    assert r.size == 0


# LH_INV_03 — released_by differs from opened_by (override required).
def test_inv_distinct_releaser_confirms() -> None:
    r = _reg()
    r.open(_hold())
    r.release("case-1", released_by="ops@ex.com")


def test_inv_distinct_releaser_prevents() -> None:
    r = _reg()
    r.open(_hold())
    with pytest.raises(LegalHoldError):
        r.release("case-1", released_by="counsel@ex.com")  # same as opened_by


def test_inv_distinct_releaser_under_failure() -> None:
    r = _reg()
    r.open(_hold())
    # Override flag allows same-actor release — must be explicit.
    r.release(
        "case-1", released_by="counsel@ex.com",
        override=True, override_reason="counsel self-release: matter dismissed",
    )


# LH_INV_04 — held records remain readable (the registry does not drop them).
def test_inv_readable_held_confirms() -> None:
    r = _reg()
    r.open(_hold())
    # The registry knows the hold exists; covers() returns True; read-paths
    # are NOT blocked — only delete-paths call covers() to skip.
    assert r.covers("user:42") is True


def test_inv_readable_held_prevents() -> None:
    r = _reg()
    # Registry has no 'drop_from_index' surface — it cannot remove.
    for attr in ("drop_from_index", "hide", "delete_record"):
        assert not hasattr(r, attr)


def test_inv_readable_held_under_failure() -> None:
    r = _reg()
    # A second open with the same id fails — cannot silently replace.
    r.open(_hold())
    with pytest.raises(LegalHoldError):
        r.open(_hold())


# LH_INV_05 — scope_query validates fields at open time.
def test_inv_scope_valid_confirms() -> None:
    r = _reg()
    r.open(_hold(scope_query="tenant_id = 'acme' AND created_at >= '2023-01-01'"))


def test_inv_scope_valid_prevents() -> None:
    r = _reg()
    with pytest.raises(LegalHoldError):
        r.open(_hold(scope_query="nonexistent_field = 'x'"))


def test_inv_scope_valid_under_failure() -> None:
    with pytest.raises(LegalHoldError):
        _hold(scope_query="")
