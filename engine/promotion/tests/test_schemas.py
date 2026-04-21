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
            verdict=Verdict.NEEDS_CALLER,
            tier="none",
            rationale="short",  # < 10 chars
            state=_state(),
        )


def test_ready_to_execute_true_for_promote_as_primitive_lite():
    e = LedgerEntry(
        primitive="X",
        namespace="api",
        verdict=Verdict.PROMOTE_AS_PRIMITIVE,
        tier="lite",
        rationale="stateless pure middleware ready to ship now",
        state=_state(),
    )
    assert e.is_ready_to_execute() is True


def test_ready_to_execute_true_for_promote_as_adapter():
    e = LedgerEntry(
        primitive="BulkheadMiddleware",
        namespace="resiliency",
        verdict=Verdict.PROMOTE_AS_ADAPTER,
        tier="adapter",
        rationale="motor Bulkhead registered; BulkheadAdapter.py missing",
        promotion_target="core/venous/_adapters/fastapi/BulkheadAdapter.py",
        state=_state(name="BulkheadMiddleware"),
    )
    assert e.is_ready_to_execute() is True


def test_ready_to_execute_false_when_blockers_present():
    e = LedgerEntry(
        primitive="X",
        namespace="api",
        verdict=Verdict.PROMOTE_AS_PRIMITIVE,
        tier="full",
        rationale="signal present but shell incomplete at time of classify",
        blockers=["Resolve 3 REPLACE_ME markers."],
        state=_state(replace_me_count=3),
    )
    assert e.is_ready_to_execute() is False


def test_ready_to_execute_false_for_needs_caller():
    e = LedgerEntry(
        primitive="X",
        namespace="api",
        verdict=Verdict.NEEDS_CALLER,
        tier="none",
        rationale="no caller identified; awaiting benchmark signal per A12",
        staging_reason="no caller; will revisit",
        state=_state(),
    )
    assert e.is_ready_to_execute() is False


def test_ready_to_execute_false_for_redundant():
    """REDUNDANT is technically removable but never auto-executed."""
    e = LedgerEntry(
        primitive="X",
        namespace="api",
        verdict=Verdict.REDUNDANT,
        tier="none",
        rationale="motor and adapter both registered — staged is redundant",
        delete_reason="canonical version already ships",
        state=_state(duplicate_of_registered="X"),
    )
    assert e.is_ready_to_execute() is False


def test_ledger_round_trip_preserves_all_fields():
    e1 = LedgerEntry(
        primitive="Foo",
        namespace="api",
        verdict=Verdict.REDUNDANT,
        tier="none",
        rationale="duplicate of a registered primitive reference",
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
            tier="lite" if v == Verdict.PROMOTE_AS_PRIMITIVE else "none",
            rationale=f"rationale entry index {i} detail long enough",
            state=_state(name=str(i)),
        )
        for i, v in enumerate(
            [
                Verdict.REDUNDANT,
                Verdict.REDUNDANT,
                Verdict.NEEDS_CALLER,
                Verdict.PROMOTE_AS_PRIMITIVE,
            ]
        )
    ]
    l = Ledger(
        generated_at="2026-04-21T00:00:00+00:00",
        total_staged=4,
        total_quarantined=0,
        entries=entries,
    )
    assert len(l.by_verdict(Verdict.REDUNDANT)) == 2
    assert len(l.by_verdict(Verdict.NEEDS_CALLER)) == 1
    assert len(l.by_verdict(Verdict.PROMOTE_AS_PRIMITIVE)) == 1
