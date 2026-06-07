"""
Delivery-contract meta-tests, part 3: adversarial ensemble report, LLM judge
report, persona review report, observability schema, timing/cost field bounds,
and the InvariantTestBinding / FileArtefact field validators.
Split from test_delivery_contract.py.
"""

from __future__ import annotations

from engine.contracts import (
    AdversarialAttack,
    AdversarialEnsembleReport,
    EmittedLog,
    EmittedMetric,
    EmittedSpan,
    FileArtefact,
    GateStatus,
    InvariantTestBinding,
    JudgeAxis,
    LLMJudgeReport,
    Maturity,
    ObservabilitySchema,
    PersonaReview,
    PersonaReviewReport,
    Tier,
    TierReport,
)
from engine.tests.test_delivery_contract__shared import (
    _attack,
    _ensemble_report_clean,
    _expect_fail,
    valid_delivery_dict,
)


# ==========================================================================
# ADVERSARIAL ENSEMBLE REPORT
# ==========================================================================
def test_ensemble_requires_three_distinct_models():
    from pydantic import ValidationError

    ok = _ensemble_report_clean()
    bad = ok.model_dump()
    bad["models_run"] = ["claude-opus-4-7", "claude-opus-4-7", "claude-opus-4-7"]
    try:
        AdversarialEnsembleReport(**bad)
    except ValidationError as e:
        assert "distinct" in str(e).lower()
        return
    raise AssertionError("Duplicate models_run should be rejected.")


def test_ensemble_requires_20_attacks():
    from pydantic import ValidationError

    bad = _ensemble_report_clean().model_dump()
    bad["attacks"] = bad["attacks"][:10]
    try:
        AdversarialEnsembleReport(**bad)
    except ValidationError as e:
        assert (
            "at least 20 items" in str(e).lower()
            or "list should have at least 20" in str(e).lower()
        )
        return
    raise AssertionError("<20 attacks should be rejected.")


def test_ensemble_any_successful_rejected():
    from pydantic import ValidationError

    attacks = list(_ensemble_report_clean().attacks)
    attacks[0] = _attack("claude-opus-4-7", 0, outcome="violated_invariant", violated="INV_X")
    try:
        AdversarialEnsembleReport(
            models_run=["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
            attacks=attacks,
            successful_attacks=1,
        )
    except ValidationError as e:
        assert "zero successful attacks" in str(e).lower()
        return
    raise AssertionError("Any successful attack must reject the ensemble report.")


def test_ensemble_successful_count_must_match_observed():
    from pydantic import ValidationError

    attacks = list(_ensemble_report_clean().attacks)
    try:
        AdversarialEnsembleReport(
            models_run=["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
            attacks=attacks,
            successful_attacks=3,
        )
    except ValidationError as e:
        assert "claims 3" in str(e).lower() or "observed" in str(e).lower()
        return
    raise AssertionError("Claim-mismatch in successful_attacks count should be rejected.")


def test_attack_leaked_outcome_requires_violation_id():
    from pydantic import ValidationError

    try:
        AdversarialAttack(
            model="claude-opus-4-7",
            attack_id="ATK-LEAK-01",
            hypothesis="Exfiltrate via error path exposing stack to the caller.",
            input_fixture="...",
            defender_outcome="leaked",
        )
    except ValidationError as e:
        assert "must cite the violated invariant id" in str(e).lower()
        return
    raise AssertionError("Leaked outcome without violation_id should be rejected.")


def test_attack_id_pattern_enforced():
    from pydantic import ValidationError

    try:
        AdversarialAttack(
            model="claude-opus-4-7",
            attack_id="bad-id",
            hypothesis="Adversary does not satisfy attack_id pattern.",
            input_fixture="x",
            defender_outcome="rejected",
        )
    except ValidationError as e:
        assert "pattern" in str(e).lower()
        return
    raise AssertionError("attack_id pattern violation should be rejected.")


# ==========================================================================
# LLM JUDGE REPORT
# ==========================================================================
def test_judge_requires_six_unique_axes():
    from pydantic import ValidationError

    axes = [
        JudgeAxis(
            axis="fidelity", score=9, rationale="solid reasoning over the impl and docs evidence"
        )
    ] * 6
    try:
        LLMJudgeReport(judge_model="claude-opus-4-7", axes=axes)
    except ValidationError as e:
        assert "exactly" in str(e).lower()
        return
    raise AssertionError("Non-unique axes should be rejected.")


def test_judge_any_axis_below_eight_rejected():
    from pydantic import ValidationError

    axes = [
        JudgeAxis(axis="fidelity", score=7, rationale="borderline fidelity story"),
    ] + [
        JudgeAxis(axis=a, score=9, rationale="solid evidence for axis")
        for a in (
            "completeness",
            "error_quality",
            "composability",
            "production_readiness",
            "catalog_conformance",
        )
    ]
    try:
        LLMJudgeReport(judge_model="claude-opus-4-7", axes=axes)
    except ValidationError as e:
        assert "score ≥ 8" in str(e) or "must score" in str(e).lower()
        return
    raise AssertionError("Axis score < 8 should be rejected.")


def test_judge_score_out_of_range_rejected():
    from pydantic import ValidationError

    try:
        JudgeAxis(axis="fidelity", score=11, rationale="above the allowed max range value")
    except ValidationError as e:
        assert "less than or equal to 10" in str(e).lower()
        return
    raise AssertionError("Score>10 should be rejected.")


def test_judge_missing_axis_rejected():
    from pydantic import ValidationError

    axes = [
        JudgeAxis(axis=a, score=9, rationale="ok evidence for axis under review")
        for a in (
            "fidelity",
            "completeness",
            "error_quality",
            "composability",
            "production_readiness",
        )
    ]
    try:
        LLMJudgeReport(judge_model="claude-opus-4-7", axes=axes)
    except ValidationError as e:
        assert "at least 6" in str(e).lower() or "length" in str(e).lower()
        return
    raise AssertionError("Missing axis should be rejected.")


# ==========================================================================
# PERSONA REVIEW REPORT
# ==========================================================================
def test_personas_requires_all_five():
    from pydantic import ValidationError

    reviews = [
        PersonaReview(persona=p, understood=True)
        for p in ("junior_dev", "principal_engineer", "security_auditor", "sre")
    ]
    try:
        PersonaReviewReport(reviews=reviews)
    except ValidationError as e:
        assert "at least 5" in str(e).lower() or "length" in str(e).lower()
        return
    raise AssertionError("Four personas should be rejected.")


def test_personas_all_must_understand():
    from pydantic import ValidationError

    reviews = [
        PersonaReview(persona=p, understood=True)
        for p in ("junior_dev", "principal_engineer", "security_auditor", "sre")
    ]
    reviews.append(
        PersonaReview(persona="pm", understood=False, friction_points=["Too much jargon"])
    )
    try:
        PersonaReviewReport(reviews=reviews)
    except ValidationError as e:
        assert "understood=true" in str(e).lower() or "unclear" in str(e).lower()
        return
    raise AssertionError("Persona not understood should be rejected.")


def test_personas_duplicate_persona_rejected():
    from pydantic import ValidationError

    reviews = [PersonaReview(persona="junior_dev", understood=True)] * 5
    try:
        PersonaReviewReport(reviews=reviews)
    except ValidationError as e:
        assert "exactly" in str(e).lower()
        return
    raise AssertionError("Duplicate personas should be rejected.")


# ==========================================================================
# OBSERVABILITY SCHEMA
# ==========================================================================
def test_obs_schema_metric_type_enum():
    from pydantic import ValidationError

    try:
        EmittedMetric(name="foo.bar", metric_type="invalid", unit="call", cardinality_bound=1)
    except ValidationError as e:
        assert "pattern" in str(e).lower()
        return
    raise AssertionError("Invalid metric_type should be rejected.")


def test_obs_schema_cardinality_bound_required():
    from pydantic import ValidationError

    try:
        EmittedMetric(name="foo.bar", metric_type="counter", unit="call", cardinality_bound=0)
    except ValidationError as e:
        assert "greater than or equal to 1" in str(e).lower()
        return
    raise AssertionError("Cardinality bound 0 should be rejected.")


def test_obs_schema_empty_logs_rejected():
    from pydantic import ValidationError

    try:
        ObservabilitySchema(
            logs=[],
            metrics=[
                EmittedMetric(
                    name="foo.bar", metric_type="counter", unit="call", cardinality_bound=1
                )
            ],
            spans=[EmittedSpan(operation_name="foo.bar")],
        )
    except ValidationError as e:
        assert "at least 1" in str(e).lower() or "length" in str(e).lower()
        return
    raise AssertionError("Empty logs should be rejected.")


def test_obs_schema_event_name_pattern():
    from pydantic import ValidationError

    try:
        EmittedLog(event_name="Bad Name", required_attributes=["a"])
    except ValidationError as e:
        assert "pattern" in str(e).lower()
        return
    raise AssertionError("Invalid event_name pattern should be rejected.")


# ==========================================================================
# TIMING / COST FIELD BOUNDS
# ==========================================================================
def test_build_duration_nonzero_required():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["build_duration_ms"] = 0
    _expect_fail(r, "greater than or equal to 1")


def test_build_duration_cap_enforced():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["build_duration_ms"] = 7_200_001
    _expect_fail(r, "less than or equal to 7200000")


def test_llm_cost_non_negative():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["llm_cost_usd"] = -0.01
    _expect_fail(r, "greater than or equal to 0")


def test_tier_report_duration_cap():
    from pydantic import ValidationError

    try:
        TierReport(
            tier=Tier.T1_BEHAVIORAL,
            status=GateStatus.SKIPPED,
            duration_ms=3_600_001,
            summary="too slow",
        )
    except ValidationError as e:
        assert "less than or equal to 3600000" in str(e).lower()
        return
    raise AssertionError("Tier duration over cap should be rejected.")


# ==========================================================================
# INVARIANT BINDING FIELD VALIDATORS
# ==========================================================================
def test_binding_text_too_short_rejected():
    from pydantic import ValidationError

    try:
        InvariantTestBinding(
            invariant_id="INV_X",
            invariant_text="MUST x",  # 7 chars
            confirms_test="test_inv_x_confirms",
            prevents_test="test_inv_x_prevents",
            under_failure_test="test_inv_x_under_failure",
        )
    except ValidationError as e:
        assert "at least 15" in str(e).lower()
        return
    raise AssertionError("Invariant text <15 chars should be rejected.")


def test_binding_id_pattern_enforced():
    from pydantic import ValidationError

    try:
        InvariantTestBinding(
            invariant_id="inv-lowercase",
            invariant_text="MUST conform to the declared invariant pattern.",
            confirms_test="test_inv_x_confirms",
            prevents_test="test_inv_x_prevents",
            under_failure_test="test_inv_x_under_failure",
        )
    except ValidationError as e:
        assert "pattern" in str(e).lower()
        return
    raise AssertionError("Invariant id pattern violation should be rejected.")


# ==========================================================================
# FileArtefact FIELD VALIDATORS
# ==========================================================================
def test_file_path_min_length():
    from pydantic import ValidationError

    try:
        FileArtefact(path="abc", sha256="0" * 64, size_bytes=1, kind="impl")
    except ValidationError as e:
        assert "at least 5" in str(e).lower()
        return
    raise AssertionError("Too-short file path should be rejected.")


def test_file_path_max_length():
    from pydantic import ValidationError

    try:
        FileArtefact(path="x" * 201, sha256="0" * 64, size_bytes=1, kind="impl")
    except ValidationError as e:
        assert "at most 200" in str(e).lower()
        return
    raise AssertionError("Too-long file path should be rejected.")
