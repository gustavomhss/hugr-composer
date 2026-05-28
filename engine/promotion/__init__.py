"""Promotion pipeline for staged primitives.

Modules:
    schemas       — Pydantic models for verdicts, ledger entries, signals.
    signals       — Detect benchmark/tool-import signals per primitive.
    classify      — Produce per-primitive verdict.
    ledger        — Emit machine-readable JSON + human-facing Markdown ledger.
    placeholders  — Detect REPLACE_ME blockers.
    promote       — Execute an approved verdict (atomic, rollback on failure).

Entry points:
    python -m engine.promotion.classify     regenerate ledger from _staging/.
    python -m engine.promotion.promote NAME --tier=lite|full  promote one.

Contract §A12 discipline is preserved: `promote` refuses to run unless the
named primitive has an active signal (benchmark gap, registered-tool import,
or a ratified triage-pass entry in the ledger).
"""

from __future__ import annotations
