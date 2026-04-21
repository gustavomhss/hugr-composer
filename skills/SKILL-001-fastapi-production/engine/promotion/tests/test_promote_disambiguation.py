"""Tests for the `_resolve_match` disambiguation helper in promote.py."""
from __future__ import annotations

import pytest

from engine.promotion.promote import _resolve_match
from engine.promotion.schemas import (
    Ledger,
    LedgerEntry,
    StateFlags,
    Verdict,
)


def _state(**overrides) -> StateFlags:
    base = dict(
        name="X",
        namespace="api",
        is_quarantined=False,
        replace_me_count=0,
        has_tla=False,
        has_concurrency=False,
        has_mutable_class_state=False,
        loc=10,
        test_file_present=True,
        invariants_stubbed=False,
    )
    base.update(overrides)
    return StateFlags(**base)


def _entry(name: str, is_q: bool) -> LedgerEntry:
    return LedgerEntry(
        primitive=name,
        namespace="resiliency" if not is_q else "_quarantine",
        verdict=Verdict.REDUNDANT,
        tier="none",
        rationale=f"entry {name} quarantined={is_q} for disambiguation test",
        delete_reason="test",
        state=_state(name=name, is_quarantined=is_q, namespace="resiliency"),
    )


def _ledger(entries: list[LedgerEntry]) -> Ledger:
    return Ledger(
        generated_at="2026-04-22T00:00:00+00:00",
        total_staged=sum(1 for e in entries if not e.state.is_quarantined),
        total_quarantined=sum(1 for e in entries if e.state.is_quarantined),
        entries=entries,
    )


def test_single_match_no_hint_returns_entry():
    l = _ledger([_entry("Foo", is_q=False)])
    e = _resolve_match(l, "Foo", None)
    assert e.primitive == "Foo"
    assert e.state.is_quarantined is False


def test_no_match_raises():
    l = _ledger([_entry("Foo", is_q=False)])
    with pytest.raises(SystemExit, match="No ledger entry"):
        _resolve_match(l, "Bar", None)


def test_duplicate_no_hint_raises_with_locations_hint():
    l = _ledger([_entry("Foo", is_q=False), _entry("Foo", is_q=True)])
    with pytest.raises(SystemExit) as exc:
        _resolve_match(l, "Foo", None)
    assert "2 times" in str(exc.value)
    assert "--quarantined" in str(exc.value) or "--staged" in str(exc.value)


def test_duplicate_with_staged_hint_picks_staged():
    l = _ledger([_entry("Foo", is_q=False), _entry("Foo", is_q=True)])
    e = _resolve_match(l, "Foo", is_quarantined=False)
    assert e.state.is_quarantined is False


def test_duplicate_with_quarantined_hint_picks_quarantined():
    l = _ledger([_entry("Foo", is_q=False), _entry("Foo", is_q=True)])
    e = _resolve_match(l, "Foo", is_quarantined=True)
    assert e.state.is_quarantined is True


def test_hint_mismatch_raises():
    l = _ledger([_entry("Foo", is_q=False)])
    with pytest.raises(SystemExit, match="is_quarantined=True"):
        _resolve_match(l, "Foo", is_quarantined=True)
