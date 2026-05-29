"""
Primitive Delivery Contract — SOTA, 9-tier, absurdly rigorous.

Every primitive module submitted by a Sonnet builder agent is validated
against this contract BEFORE acceptance. A delivery that fails any tier is
rejected with a structured error — no soft-accept, ever.

Nine tiers, each a qualitatively different class of confidence:

    T1  Behavioral runtime           invariants hold in end-to-end scenarios
    T2  Formal model check           TLA+ / Alloy spec machine-verified
    T3  State-machine hypothesis     all reachable states explored
    T4  Metamorphic + differential   algebraic laws, reference-impl parity
    T5  Concurrency                  linearizability, deterministic scheduler
    T6  Adversarial ensemble         multi-model red-team ≥ 3 Claude variants
    T7  Observability                logs, metrics, traces schema-asserted
    T8  Chaos + game-day             fault injection, economic attacks
    T9  Meta                         LLM test-gap, persona, spec lint

Maturity gates which tiers are required:
    experimental  → T1 (+ T6 single-model)
    emerging      → T1, T2?, T3, T4, T6
    battle_tested → ALL 9

See also: `docs/research/SKILL_ENGINE_SPEC.md`, `docs/research/CONTRACT_STANDARDS.md`.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
class Tier(StrEnum):
    T0_STATIC = "T0_static"  # mypy --strict + ruff + rationale-attached suppressions
    T1_BEHAVIORAL = "T1_behavioral"
    T2_FORMAL = "T2_formal"
    T3_STATE_MACHINE = "T3_state_machine"
    T4_METAMORPHIC = "T4_metamorphic"
    T5_CONCURRENCY = "T5_concurrency"
    T6_ADVERSARIAL = "T6_adversarial"
    T7_OBSERVABILITY = "T7_observability"
    T8_CHAOS = "T8_chaos"
    T9_META = "T9_meta"


class GateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"  # legitimately not applicable (e.g. stateless → T2 skipped)
    ERRORED = "errored"  # gate runner crashed; treated as failure by the aggregator


class Maturity(StrEnum):
    EXPERIMENTAL = "experimental"
    EMERGING = "emerging"
    BATTLE_TESTED = "battle_tested"


MATURITY_REQUIRED_TIERS: dict[Maturity, frozenset[Tier]] = {
    Maturity.EXPERIMENTAL: frozenset({Tier.T0_STATIC, Tier.T1_BEHAVIORAL, Tier.T6_ADVERSARIAL}),
    Maturity.EMERGING: frozenset(
        {
            Tier.T0_STATIC,
            Tier.T1_BEHAVIORAL,
            Tier.T3_STATE_MACHINE,
            Tier.T4_METAMORPHIC,
            Tier.T6_ADVERSARIAL,
            Tier.T7_OBSERVABILITY,
        }
    ),
    Maturity.BATTLE_TESTED: frozenset(Tier),  # all ten
}


IMPERATIVE_STARTS = ("MUST", "NEVER", "ALWAYS", "CANNOT", "SHALL", "FORBIDDEN")


# ---------------------------------------------------------------------------
# File artefact shape
# ---------------------------------------------------------------------------
class FileArtefact(BaseModel):
    """A single file in the primitive delivery. Path + integrity + origin."""

    path: str = Field(
        min_length=5,
        max_length=200,
        description="Path relative to `core/venous/<namespace>/<name>/`.",
    )
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Hex-encoded SHA-256 digest of the file content.",
    )
    size_bytes: int = Field(ge=1, le=5_000_000)
    kind: str = Field(
        pattern=r"^(impl|test|behavioral|state_machine|metamorphic|concurrent|"
        r"adversarial|chaos|observability|dashboard|spec_md|manifest|"
        r"formal_tla|formal_alloy|contract_json|persona_reviews|"
        r"proposed_invariants|sbom)$",
        description="Functional role of the file; validator requires certain kinds per maturity.",
    )

    @field_validator("path")
    @classmethod
    def path_is_posix_and_contained(cls, v: str) -> str:
        p = PurePosixPath(v)
        if p.is_absolute():
            raise ValueError(f"path MUST be relative, got absolute '{v}'")
        if ".." in p.parts:
            raise ValueError(f"path MUST NOT traverse (`..`), got '{v}'")
        if any(part.startswith(".") for part in p.parts):
            raise ValueError(f"path MUST NOT contain dotfiles/dotdirs, got '{v}'")
        return v


# ---------------------------------------------------------------------------
# Invariant → test binding
# ---------------------------------------------------------------------------
class InvariantTestBinding(BaseModel):
    """Binds one catalog invariant to three concrete test names proving it."""

    invariant_id: str = Field(
        pattern=r"^[A-Z][A-Z0-9_]{2,40}$",
        description="Identifier such as RATE-INV-03; unique per primitive.",
    )
    invariant_text: str = Field(min_length=15, max_length=400)
    confirms_test: str = Field(
        pattern=r"^test_inv_[a-z0-9_]+_confirms$",
        description="Test name that proves the primitive DOES the invariant.",
    )
    prevents_test: str = Field(
        pattern=r"^test_inv_[a-z0-9_]+_prevents$",
        description="Test name that proves the primitive REJECTS a violation attempt.",
    )
    under_failure_test: str = Field(
        pattern=r"^test_inv_[a-z0-9_]+_under_failure$",
        description="Test name that proves the invariant HOLDS during fault injection.",
    )

    @field_validator("invariant_text")
    @classmethod
    def imperative_required(cls, v: str) -> str:
        upper = v.upper()
        if not any(kw in upper for kw in IMPERATIVE_STARTS):
            raise ValueError(f"invariant_text MUST contain one of {IMPERATIVE_STARTS}: {v!r}")
        return v

    @model_validator(mode="after")
    def test_names_share_slug(self) -> InvariantTestBinding:
        def slug(test_name: str) -> str:
            # strip `test_inv_` prefix and `_confirms|_prevents|_under_failure` suffix
            m = re.match(r"^test_inv_(.+?)_(confirms|prevents|under_failure)$", test_name)
            return m.group(1) if m else ""

        slugs = {slug(self.confirms_test), slug(self.prevents_test), slug(self.under_failure_test)}
        if len(slugs) != 1 or "" in slugs:
            raise ValueError(
                "confirms / prevents / under_failure tests MUST share a common invariant slug, got "
                f"confirms={self.confirms_test}, prevents={self.prevents_test}, "
                f"under_failure={self.under_failure_test}"
            )
        return self


# ---------------------------------------------------------------------------
# Tier report
# ---------------------------------------------------------------------------
class TierReport(BaseModel):
    """Outcome of one tier gate for a primitive."""

    tier: Tier
    status: GateStatus
    duration_ms: int = Field(ge=0, le=3_600_000)
    evidence_path: str | None = Field(default=None, max_length=200)
    tool_name: str | None = Field(default=None, max_length=80)
    tool_version: str | None = Field(default=None, max_length=40)
    summary: str = Field(min_length=5, max_length=400, description="Human-readable outcome blurb.")
    error_details: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def evidence_present_when_passed(self) -> TierReport:
        if self.status is GateStatus.PASSED and not self.evidence_path:
            raise ValueError(
                f"{self.tier.value} passed — evidence_path MUST be set (no blind PASS)."
            )
        if self.status is GateStatus.FAILED and not self.error_details:
            raise ValueError(
                f"{self.tier.value} failed — error_details MUST be set (no silent failure)."
            )
        return self


# ---------------------------------------------------------------------------
# Ensemble adversarial (T6) — per-model report
# ---------------------------------------------------------------------------
class AdversarialAttack(BaseModel):
    model: str = Field(min_length=5, max_length=60, description="e.g. 'claude-opus-4-7'.")
    attack_id: str = Field(pattern=r"^ATK-[A-Z0-9_-]{3,40}$")
    hypothesis: str = Field(
        min_length=20, max_length=600, description="What the red-team model bet would break."
    )
    input_fixture: str = Field(min_length=1, max_length=10_000)
    defender_outcome: str = Field(
        pattern=r"^(rejected|held|leaked|crashed|violated_invariant)$",
        description="What the primitive did with this input.",
    )
    violated_invariant_id: str | None = Field(default=None)

    @model_validator(mode="after")
    def leaked_requires_violation_id(self) -> AdversarialAttack:
        if (
            self.defender_outcome in ("leaked", "crashed", "violated_invariant")
            and not self.violated_invariant_id
        ):
            raise ValueError(
                f"Attack outcome '{self.defender_outcome}' MUST cite the violated invariant id."
            )
        return self


class AdversarialEnsembleReport(BaseModel):
    """T6 aggregate across 3+ models."""

    models_run: list[str] = Field(min_length=3, max_length=10)
    attacks: list[AdversarialAttack] = Field(min_length=20)
    successful_attacks: int = Field(ge=0)

    @model_validator(mode="after")
    def successful_count_matches(self) -> AdversarialEnsembleReport:
        observed = sum(
            1
            for a in self.attacks
            if a.defender_outcome in ("leaked", "crashed", "violated_invariant")
        )
        if observed != self.successful_attacks:
            raise ValueError(
                f"successful_attacks claims {self.successful_attacks} but {observed} "
                f"attacks in the report have defender_outcome in (leaked, crashed, violated_invariant)."
            )
        return self

    @model_validator(mode="after")
    def zero_successful_required(self) -> AdversarialEnsembleReport:
        if self.successful_attacks > 0:
            raise ValueError(
                f"T6 MUST have zero successful attacks to pass; got {self.successful_attacks}."
            )
        return self

    @model_validator(mode="after")
    def distinct_models(self) -> AdversarialEnsembleReport:
        if len(set(self.models_run)) != len(self.models_run):
            raise ValueError(f"models_run MUST be distinct, got {self.models_run}.")
        return self


# ---------------------------------------------------------------------------
# LLM judge report (T9-ish) — fidelity, completeness, clarity
# ---------------------------------------------------------------------------
class JudgeAxis(BaseModel):
    axis: str = Field(
        pattern=r"^(fidelity|completeness|error_quality|composability|"
        r"production_readiness|catalog_conformance)$"
    )
    score: int = Field(ge=1, le=10)
    rationale: str = Field(min_length=20, max_length=1000)


class LLMJudgeReport(BaseModel):
    judge_model: str = Field(min_length=5)
    axes: list[JudgeAxis] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def six_unique_axes(self) -> LLMJudgeReport:
        expected = {
            "fidelity",
            "completeness",
            "error_quality",
            "composability",
            "production_readiness",
            "catalog_conformance",
        }
        seen = {a.axis for a in self.axes}
        if seen != expected:
            raise ValueError(f"LLMJudgeReport MUST cover exactly {expected}, got {seen}.")
        return self

    @model_validator(mode="after")
    def every_axis_ge_8(self) -> LLMJudgeReport:
        below = [(a.axis, a.score) for a in self.axes if a.score < 8]
        if below:
            raise ValueError(f"Every axis MUST score ≥ 8/10. Below-threshold axes: {below}")
        return self


# ---------------------------------------------------------------------------
# Persona review — T9
# ---------------------------------------------------------------------------
class PersonaReview(BaseModel):
    persona: str = Field(pattern=r"^(junior_dev|principal_engineer|security_auditor|sre|pm)$")
    understood: bool
    friction_points: list[str] = Field(default_factory=list, max_length=10)
    rewrite_suggestion: str | None = Field(default=None, max_length=2000)


class PersonaReviewReport(BaseModel):
    reviews: list[PersonaReview] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def all_five_personas_present(self) -> PersonaReviewReport:
        expected = {"junior_dev", "principal_engineer", "security_auditor", "sre", "pm"}
        seen = {r.persona for r in self.reviews}
        if seen != expected:
            raise ValueError(f"PersonaReviewReport MUST cover exactly {expected}, got {seen}.")
        return self

    @model_validator(mode="after")
    def all_five_understood(self) -> PersonaReviewReport:
        unclear = [r.persona for r in self.reviews if not r.understood]
        if unclear:
            raise ValueError(
                f"All five personas MUST mark understood=true. Unclear for: {unclear}."
            )
        return self


# ---------------------------------------------------------------------------
# Observability schema declaration — T7
# ---------------------------------------------------------------------------
class EmittedLog(BaseModel):
    event_name: str = Field(pattern=r"^[a-z0-9][a-z0-9._]*[a-z0-9]$", min_length=3, max_length=80)
    required_attributes: list[str] = Field(min_length=1, max_length=20)


class EmittedMetric(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._]*[a-z0-9]$", min_length=3, max_length=80)
    metric_type: str = Field(pattern=r"^(counter|histogram|gauge|updown_counter)$")
    unit: str = Field(min_length=1, max_length=20)
    cardinality_bound: int = Field(ge=1, le=1_000_000)
    label_keys: list[str] = Field(default_factory=list, max_length=10)


class EmittedSpan(BaseModel):
    operation_name: str = Field(
        pattern=r"^[a-z0-9][a-z0-9._]*[a-z0-9]$", min_length=3, max_length=80
    )
    required_attributes: list[str] = Field(default_factory=list, max_length=20)


class ObservabilitySchema(BaseModel):
    logs: list[EmittedLog] = Field(min_length=1, max_length=50)
    metrics: list[EmittedMetric] = Field(min_length=1, max_length=50)
    spans: list[EmittedSpan] = Field(min_length=1, max_length=50)


# ---------------------------------------------------------------------------
# Full primitive delivery
# ---------------------------------------------------------------------------
class PrimitiveDelivery(BaseModel):
    """The sealed delivery of a single primitive module by a builder agent.

    Rejected outright if:
    - Any required tier is missing for the declared maturity.
    - Any tier status is FAILED / ERRORED.
    - Invariant bindings do not cover the catalog invariants.
    - Required files per maturity are missing.
    """

    # --- identity ---------------------------------------------------------
    name: str = Field(pattern=r"^[A-Z][a-zA-Z0-9]*$", max_length=40)
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=30)
    maturity: Maturity
    builder_agent_id: int = Field(ge=1, le=10)

    # --- provenance: proves catalog drift detection -----------------------
    catalog_entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # --- artefacts --------------------------------------------------------
    files: list[FileArtefact] = Field(min_length=5, max_length=30)

    # --- invariant-to-test binding ---------------------------------------
    invariant_bindings: list[InvariantTestBinding] = Field(min_length=3, max_length=15)

    # --- tier reports -----------------------------------------------------
    tier_reports: list[TierReport] = Field(min_length=2, max_length=15)

    # --- structured sub-reports (only present when their tier is included) -
    adversarial: AdversarialEnsembleReport | None = None
    judge: LLMJudgeReport | None = None
    personas: PersonaReviewReport | None = None
    observability: ObservabilitySchema | None = None

    # --- timing / cost bookkeeping ----------------------------------------
    build_duration_ms: int = Field(ge=1, le=7_200_000)
    llm_cost_usd: float = Field(ge=0.0, le=10.0)

    # =====================================================================
    # Cross-field validators
    # =====================================================================

    @model_validator(mode="after")
    def files_unique_by_path(self) -> PrimitiveDelivery:
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)):
            dupes = {p for p in paths if paths.count(p) > 1}
            raise ValueError(f"Duplicate file paths: {sorted(dupes)}")
        return self

    @model_validator(mode="after")
    def files_unique_by_sha(self) -> PrimitiveDelivery:
        shas = [f.sha256 for f in self.files]
        if len(shas) != len(set(shas)):
            raise ValueError(
                "Duplicate SHA-256 across files — delivery cannot contain identical files."
            )
        return self

    @model_validator(mode="after")
    def invariant_ids_unique(self) -> PrimitiveDelivery:
        ids = [b.invariant_id for b in self.invariant_bindings]
        if len(ids) != len(set(ids)):
            raise ValueError(
                f"invariant_ids MUST be unique per primitive, got duplicates in {ids}."
            )
        return self

    @model_validator(mode="after")
    def test_names_unique(self) -> PrimitiveDelivery:
        all_tests = []
        for b in self.invariant_bindings:
            all_tests.extend([b.confirms_test, b.prevents_test, b.under_failure_test])
        if len(all_tests) != len(set(all_tests)):
            raise ValueError("Test names MUST be unique across all invariant bindings.")
        return self

    @model_validator(mode="after")
    def tier_reports_cover_maturity(self) -> PrimitiveDelivery:
        required = MATURITY_REQUIRED_TIERS[self.maturity]
        present = {r.tier for r in self.tier_reports}
        missing = required - present
        if missing:
            raise ValueError(
                f"maturity={self.maturity.value} requires tiers {sorted(t.value for t in required)}; "
                f"missing: {sorted(t.value for t in missing)}."
            )
        return self

    @model_validator(mode="after")
    def tier_reports_unique_tier(self) -> PrimitiveDelivery:
        tiers = [r.tier for r in self.tier_reports]
        if len(tiers) != len(set(tiers)):
            raise ValueError(f"Each tier MUST appear at most once in tier_reports, got {tiers}.")
        return self

    @model_validator(mode="after")
    def no_tier_failed_or_errored(self) -> PrimitiveDelivery:
        bad = [r for r in self.tier_reports if r.status in (GateStatus.FAILED, GateStatus.ERRORED)]
        if bad:
            raise ValueError(
                f"A delivery with any FAILED / ERRORED tier is rejected. Bad tiers: "
                f"{[(r.tier.value, r.status.value) for r in bad]}"
            )
        return self

    @model_validator(mode="after")
    def required_files_present(self) -> PrimitiveDelivery:
        kinds = {f.kind for f in self.files}
        mandatory = {"impl", "test", "behavioral", "spec_md", "manifest"}
        missing = mandatory - kinds
        if missing:
            raise ValueError(
                f"Delivery MUST contain files of kinds {sorted(mandatory)}; missing {sorted(missing)}."
            )

        if self.maturity is Maturity.BATTLE_TESTED:
            # Tiers that are legitimately SKIPPED for stateless primitives may
            # omit their file kinds; evidence for those is absent by design.
            skipped_tiers = {r.tier for r in self.tier_reports if r.status is GateStatus.SKIPPED}
            battle_req = {
                "metamorphic",
                "chaos",
                "observability",
                "dashboard",
                "contract_json",
                "persona_reviews",
                "proposed_invariants",
            }
            if Tier.T3_STATE_MACHINE not in skipped_tiers:
                battle_req.add("state_machine")
            if Tier.T5_CONCURRENCY not in skipped_tiers:
                battle_req.add("concurrent")
            # Adversarial ensemble evidence lives under _evidence/ (excluded from
            # file scan); the structured sub-report is separately validated on
            # `PrimitiveDelivery.adversarial`, so we do not require a root-level
            # adversarial_*.json artefact here.
            bm = battle_req - kinds
            if bm:
                raise ValueError(
                    f"battle_tested delivery MUST contain file kinds {sorted(battle_req)}; missing {sorted(bm)}."
                )
        return self

    @model_validator(mode="after")
    def sub_reports_present_when_tier_included(self) -> PrimitiveDelivery:
        {r.tier for r in self.tier_reports}
        passed = {r.tier for r in self.tier_reports if r.status is GateStatus.PASSED}

        if Tier.T6_ADVERSARIAL in passed and self.adversarial is None:
            raise ValueError("T6 passed requires adversarial sub-report.")
        if Tier.T9_META in passed and (self.judge is None or self.personas is None):
            raise ValueError("T9 passed requires both judge and personas sub-reports.")
        if Tier.T7_OBSERVABILITY in passed and self.observability is None:
            raise ValueError("T7 passed requires observability sub-report.")
        # Tiers not included and sub-report provided → still OK; just means extra evidence.
        return self

    @model_validator(mode="after")
    def llm_cost_bounded_by_maturity(self) -> PrimitiveDelivery:
        caps = {
            Maturity.EXPERIMENTAL: 0.25,
            Maturity.EMERGING: 1.00,
            Maturity.BATTLE_TESTED: 2.50,
        }
        cap = caps[self.maturity]
        if self.llm_cost_usd > cap:
            raise ValueError(
                f"llm_cost_usd={self.llm_cost_usd} exceeds cap ${cap} for maturity={self.maturity.value}."
            )
        return self

    @model_validator(mode="after")
    def path_name_consistency(self) -> PrimitiveDelivery:
        """Every file path must live under the primitive's namespace/name directory."""
        prefix = f"{self.namespace}/{self.name}/"
        off = [f.path for f in self.files if not f.path.startswith(prefix)]
        if off:
            raise ValueError(
                f"All file paths MUST start with '{prefix}' (core/venous root implied). "
                f"Off-tree: {off}"
            )
        return self


# ---------------------------------------------------------------------------
# Top-level acceptance function
# ---------------------------------------------------------------------------
def accept_delivery(raw: dict) -> tuple[bool, PrimitiveDelivery | None, list[str]]:
    """
    Return `(ok, parsed, errors)`.

    `ok=True` only when every schema rule + cross-field validator + tier rule
    passes. No soft-accept.
    """
    try:
        delivery = PrimitiveDelivery.model_validate(raw)
    except Exception as e:
        return False, None, [f"Schema validation failed: {e}"]
    return True, delivery, []


def compute_sha256(content: bytes) -> str:
    """Helper for agents building a FileArtefact."""
    return hashlib.sha256(content).hexdigest()
