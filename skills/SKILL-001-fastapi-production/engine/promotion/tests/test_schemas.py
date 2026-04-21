"""Contract tests for promotion schemas.

Validates:
  * Required-field enforcement (pydantic rejects empties).
  * Verdict-specific field combinations (delete_reason on delete only, etc.).
  * is_ready_to_execute() logic.
  * Ledger JSON round-trip preserves every field.
"""
from __future__ import annotations

import pytest

from engine.promotion.schemas import (
    Ledger,
    LedgerEntry,
    Signal,
    SignalKind,
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
        loc=42,
        test_file_present=True,
        invariants_stubbed=False,
    )
    base.update(overrides)
    return StateFlags(**base)


def test_ledger_entry_requires_rationale_min_length():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LedgerEntry(
            primitive="X",
            namespace="api",
            verdict=Verdict.KEEP_STAGED,
            tier="none",
            rationale="short",  # < 10 chars
            state=_state(),
        )


def test_ready_to_execute_true_for_promote_with_no_blockers():
    e = LedgerEntry(
        primitive="X",
        namespace="api",
        verdict=Verdict.PROMOTE_LITE,
        tier="lite",
        rationale="stateless pure middleware ready to ship",
        state=_state(),
    )
    assert e.is_ready_to_execute() is True


def test_ready_to_execute_false_when_blockers_present():
    e = LedgerEntry(
        primitive="X",
        namespace="api",
        verdict=Verdict.PROMOTE_FULL,
        tier="full",
        rationale="strong signal but shell is incomplete at present",
        blockers=["Resolve 3 REPLACE_ME markers."],
        state=_state(replace_me_count=3),
    )
    assert e.is_ready_to_execute() is False


def test_ready_to_execute_false_for_keep_staged():
    e = LedgerEntry(
        primitive="X",
        namespace="api",
        verdict=Verdict.KEEP_STAGED,
        tier="none",
        rationale="no caller identified; awaiting benchmark signal per A12",
        staging_reason="no caller; will revisit",
        state=_state(),
    )
    assert e.is_ready_to_execute() is False


def test_ledger_round_trip_preserves_all_fields():
    e1 = LedgerEntry(
        primitive="Foo",
        namespace="api",
        verdict=Verdict.DELETE,
        tier="none",
        rationale="duplicate of a registered primitive",
        delete_reason="registered version Foo is canonical",
        signals=[
            Signal(
                kind=SignalKind.TOOL_IMPORT, source="adapt/tool.py", detail="x"
            )
        ],
        state=_state(duplicate_of_registered="Foo"),
    )
    l1 = Ledger(
        generated_at="2026-04-21T00:00:00+00:00",
        total_staged=1,
        total_quarantined=0,
        entries=[e1],
    )
    blob = l1.model_dump_json()
    l2 = Ledger.model_validate_json(blob)
    assert l2.entries[0].delete_reason == "registered version Foo is canonical"
    assert l2.entries[0].signals[0].kind == SignalKind.TOOL_IMPORT
    assert l2.entries[0].state.duplicate_of_registered == "Foo"


def test_by_verdict_filters_correctly():
    entries = [
        LedgerEntry(
            primitive=str(i),
            namespace="api",
            verdict=v,
            tier="none" if v != Verdict.PROMOTE_LITE else "lite",
            rationale=f"rationale entry index {i} detail long enough",
            state=_state(name=str(i)),
        )
        for i, v in enumerate(
            [
                Verdict.DELETE,
                Verdict.DELETE,
                Verdict.KEEP_STAGED,
                Verdict.PROMOTE_LITE,
            ]
        )
    ]
    l = Ledger(
        generated_at="2026-04-21T00:00:00+00:00",
        total_staged=4,
        total_quarantined=0,
        entries=entries,
    )
    assert len(l.by_verdict(Verdict.DELETE)) == 2
    assert len(l.by_verdict(Verdict.KEEP_STAGED)) == 1
    assert len(l.by_verdict(Verdict.PROMOTE_LITE)) == 1
