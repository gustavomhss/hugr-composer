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
    """Action-focused classification for a staged primitive.

    Default stance: **make it work**, not delete. Every verdict except
    REDUNDANT corresponds to a concrete path-to-functionality.

    * promote_as_adapter — motor already registered at
      `core/venous/<ns>/<Motor>/` but `_adapters/fastapi/<Motor>Adapter.py`
      is missing. The staged item is viable as that adapter; promote it
      to `_adapters/fastapi/<Motor>Adapter.py`.
    * promote_as_primitive — stateless, framework-free, registered-lite
      eligible. Fill REPLACE_ME (if any) + promote to
      `core/venous/<ns>/<Name>/` with `tier: "lite"`. Requires §B1.8
      ratification for lite; otherwise full tier.
    * extract_motor_pair — framework-coupled with NO motor registered.
      Requires splitting into (framework-free motor primitive + FastAPI
      adapter) per §B1.0.1. Substantial work per item.
    * fill_and_promote — has §A12(b) signal but shell is incomplete:
      REPLACE_ME markers or stub invariant tests. Fill the shell, then
      promote (adapter or primitive depending on framework coupling).
    * redundant — motor AND adapter both already ship registered.
      Staged copy adds no value. Default: leave in place (user may
      choose to delete or archive — not automatic).
    * needs_caller — no §A12(b) signal yet. Wait for a registered tool /
      module / benchmark spec to reference this primitive before
      promoting. §A12 discipline.
    * needs_review — classifier could not decide safely; human must
      adjudicate. NEVER a default — only when heuristics conflict.
    """

    PROMOTE_AS_ADAPTER = "promote_as_adapter"
    PROMOTE_AS_PRIMITIVE = "promote_as_primitive"
    EXTRACT_MOTOR_PAIR = "extract_motor_pair"
    FILL_AND_PROMOTE = "fill_and_promote"
    REDUNDANT = "redundant"
    NEEDS_CALLER = "needs_caller"
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
    framework_imports: list[str] = Field(
        default_factory=list,
        description=(
            "Framework modules the primitive's primary .py imports. "
            "Registered primitives may not import framework modules "
            "(CONTRACT §B1.0.1); non-empty list is a hard blocker."
        ),
    )
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
    tier: Literal["full", "lite", "adapter", "none"] = Field(
        description=(
            "Target registration tier. 'adapter' for promote_as_adapter; "
            "'lite' / 'full' for promote_as_primitive (lite requires "
            "§B1.8 ratification). 'none' for non-promotion verdicts."
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
        description=(
            "Required when verdict indicates the primitive stays in "
            "_extracted/ (NEEDS_CALLER / NEEDS_REVIEW / REDUNDANT)."
        ),
    )
    delete_reason: str | None = Field(
        default=None,
        description=(
            "Filled when REDUNDANT. Explains why the staged copy adds "
            "no value — user may use it as justification if they choose "
            "to delete, but delete is not automatic."
        ),
    )
    promotion_target: str | None = Field(
        default=None,
        description=(
            "Destination path for PROMOTE_* verdicts. E.g. "
            "`core/venous/_adapters/fastapi/BulkheadAdapter.py` for "
            "promote_as_adapter, or `core/venous/<ns>/<Name>/` for "
            "promote_as_primitive."
        ),
    )
    classifier_version: str = Field(default="1.0")

    def is_ready_to_execute(self) -> bool:
        """True iff this entry has zero blockers and an actionable verdict.

        Actionable = the executor can run it today. REDUNDANT is
        technically executable-as-delete but not default policy; the
        ready flag excludes it so `promote --from-ledger` never picks
        a REDUNDANT item by accident.
        """
        return (
            not self.blockers
            and self.verdict
            in (Verdict.PROMOTE_AS_ADAPTER, Verdict.PROMOTE_AS_PRIMITIVE)
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
