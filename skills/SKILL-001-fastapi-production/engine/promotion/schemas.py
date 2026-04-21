"""Typed contracts for the promotion pipeline.

Every ledger entry, signal, and verdict flows through these Pydantic
models. Drift between code and ledger is impossible: the writer and the
reader use the same schema.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """Terminal classification for a staged primitive.

    * promote_full — ship to `core/venous/<ns>/<Name>/` at full tier
      (TLA+ required).
    * promote_lite — ship at lite tier (no TLA+). Requires ratified
      tier-lite amendment (docs/decisions/0004-tier-lite.md).
    * keep_staged — remains in `_extracted/`; `staging_reason` must
      accompany.
    * delete     — redundant with an already-registered primitive,
      quarantined beyond repair, or superseded by design. Removed from
      `_extracted/` entirely.
    * needs_review — classifier could not decide safely; human must
      adjudicate. NEVER a default — only used when signals conflict.
    """

    PROMOTE_FULL = "promote_full"
    PROMOTE_LITE = "promote_lite"
    KEEP_STAGED = "keep_staged"
    DELETE = "delete"
    NEEDS_REVIEW = "needs_review"


class SignalKind(str, Enum):
    """What evidence connects the primitive to a caller.

    §A12 recognises (a) benchmark gap, (b) registered-tool import, and
    (c) a ratified triage-pass entry. This enum captures the machine-
    detectable signals; the ratified-triage signal lives in the ledger
    itself as an `approved_by` field rather than here.
    """

    TOOL_IMPORT = "tool_import"
    BENCHMARK_REF = "benchmark_ref"
    GENERATOR_REF = "generator_ref"
    MODULE_REF = "module_ref"
    RECIPE_MENTION = "recipe_mention"


class Signal(BaseModel):
    """One piece of evidence that the primitive is called from somewhere."""

    kind: SignalKind
    source: str = Field(..., description="File path or benchmark spec id.")
    detail: str = Field(
        default="",
        description=(
            "Free-form explanation — the exact import line, the spec "
            "section, the recipe wording. Never empty when provenance "
            "matters for audit."
        ),
    )


class StateFlags(BaseModel):
    """Machine-measured state of a staged primitive at classification time."""

    name: str
    namespace: str
    is_quarantined: bool
    replace_me_count: int = Field(
        ge=0,
        description="Total REPLACE_ME markers across the primitive's tree.",
    )
    has_tla: bool
    has_concurrency: bool = Field(
        description=(
            "True if the primitive's own .py imports threading, asyncio, "
            "multiprocessing, or uses Lock / Queue / Semaphore / Event."
        ),
    )
    has_mutable_class_state: bool = Field(
        description=(
            "True if the primitive's main class has instance attributes "
            "beyond ctor-assigned immutables (heuristic — triggers "
            "human-review for lite eligibility)."
        ),
    )
    loc: int = Field(ge=0, description="Lines of code in primary .py (no tests).")
    primitive_score: int = Field(
        default=0,
        ge=0,
        description="Extraction confidence score from _origin.json.",
    )
    origin_tool: str = Field(
        default="",
        description="Relative path of the tool that produced this primitive.",
    )
    quarantine_reason: str = Field(default="")
    forbidden_modules: list[str] = Field(default_factory=list)
    duplicate_of_registered: str | None = Field(
        default=None,
        description=(
            "Name of a registered primitive this staged item duplicates, "
            "if any (same shape-hash or identical public API)."
        ),
    )
    test_file_present: bool
    invariants_stubbed: bool = Field(
        description=(
            "True if invariant_bindings.json or test file carries "
            "REPLACE_ME markers that would fail audit at promotion time."
        ),
    )


class LedgerEntry(BaseModel):
    """One row in the promotion ledger.

    An entry is self-contained: a future auditor (or Gustavo) can decide
    approve/reject without needing any other file.
    """

    primitive: str
    namespace: str
    verdict: Verdict
    tier: Literal["full", "lite", "none"] = Field(
        description=(
            "Only meaningful when verdict is PROMOTE_*. 'none' for "
            "keep_staged / delete / needs_review."
        ),
    )
    rationale: str = Field(
        min_length=10,
        max_length=400,
        description="Two-sentence max reason for the verdict.",
    )
    signals: list[Signal] = Field(default_factory=list)
    blockers: list[str] = Field(
        default_factory=list,
        description=(
            "Hard preconditions that must be resolved before this verdict "
            "can be executed. Empty list = immediately executable."
        ),
    )
    state: StateFlags
    staging_reason: str | None = Field(
        default=None,
        description="Required when verdict=keep_staged, otherwise None.",
    )
    delete_reason: str | None = Field(
        default=None,
        description="Required when verdict=delete, otherwise None.",
    )
    classifier_version: str = Field(default="1.0")

    def is_ready_to_execute(self) -> bool:
        """True iff this entry has zero blockers and a terminal verdict."""
        return (
            not self.blockers
            and self.verdict
            in (Verdict.PROMOTE_FULL, Verdict.PROMOTE_LITE, Verdict.DELETE)
        )


class Ledger(BaseModel):
    """The full triage output — one entry per staged+quarantined primitive."""

    generated_at: str = Field(
        description="ISO-8601 UTC timestamp at ledger generation."
    )
    classifier_version: str = Field(default="1.0")
    total_staged: int = Field(ge=0)
    total_quarantined: int = Field(ge=0)
    entries: list[LedgerEntry]

    def by_verdict(self, v: Verdict) -> list[LedgerEntry]:
        return [e for e in self.entries if e.verdict == v]

    def ready_to_execute(self) -> list[LedgerEntry]:
        return [e for e in self.entries if e.is_ready_to_execute()]
