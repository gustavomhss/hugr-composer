"""
Delivery-contract meta-tests, part 2: invariant bindings, tier reports,
sub-report linkage, and the LLM cost cap. Split from test_delivery_contract.py.
"""

from __future__ import annotations

from engine.contracts import GateStatus, Maturity, Tier, TierReport

from engine.tests.test_delivery_contract__shared import (
    _expect_fail,
    _expect_ok,
    valid_delivery_dict,
)


# ==========================================================================
# INVARIANT BINDINGS
# ==========================================================================
def test_binding_requires_imperative():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["invariant_bindings"][0]["invariant_text"] = "provides correctness and responsiveness"
    _expect_fail(r, "must contain one of")


def test_binding_test_names_pattern_enforced():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["invariant_bindings"][0]["confirms_test"] = "test_not_matching_pattern"
    _expect_fail(r, "string should match pattern")


def test_binding_test_names_slug_mismatch_rejected():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["invariant_bindings"][0]["prevents_test"] = "test_inv_xxx_prevents"
    _expect_fail(r, "share a common invariant slug")


def test_invariant_ids_unique():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["invariant_bindings"][1]["invariant_id"] = r["invariant_bindings"][0]["invariant_id"]
    _expect_fail(r, "invariant_ids must be unique")


def test_test_names_unique_across_bindings():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["invariant_bindings"][1]["confirms_test"] = r["invariant_bindings"][0]["confirms_test"]
    # This WILL trip slug check first if slugs differ, so swap slug too.
    r["invariant_bindings"][1]["prevents_test"] = r["invariant_bindings"][0]["prevents_test"]
    r["invariant_bindings"][1]["under_failure_test"] = r["invariant_bindings"][0][
        "under_failure_test"
    ]
    # Now the binding is valid on its own (slug consistent) but duplicates the other binding
    # IDs — so the invariant_id uniqueness check fires first; make IDs distinct and slugs equal.
    r["invariant_bindings"][1]["invariant_id"] = "INV_DIFFERENT"
    _expect_fail(r, "test names must be unique")


def test_bindings_minimum_three():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["invariant_bindings"] = r["invariant_bindings"][:2]
    _expect_fail(r, "at least 3")


# ==========================================================================
# TIER REPORTS
# ==========================================================================
def test_tier_reports_unique_per_tier():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["tier_reports"].append(r["tier_reports"][0])
    _expect_fail(r, "each tier must appear at most once")


def test_failed_tier_rejects_delivery():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["tier_reports"][0]["status"] = "failed"
    r["tier_reports"][0]["error_details"] = "something bad"
    r["tier_reports"][0].pop("evidence_path", None)
    _expect_fail(r, "failed / errored tier")


def test_errored_tier_rejects_delivery():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["tier_reports"][0]["status"] = "errored"
    r["tier_reports"][0]["error_details"] = "runner crashed"
    r["tier_reports"][0].pop("evidence_path", None)
    _expect_fail(r, "failed / errored tier")


def test_passed_tier_without_evidence_path_rejected():
    from pydantic import ValidationError

    try:
        TierReport(
            tier=Tier.T1_BEHAVIORAL, status=GateStatus.PASSED, duration_ms=1, summary="no evidence"
        )
    except ValidationError as e:
        assert "evidence_path MUST be set" in str(e)
        return
    raise AssertionError("Passed tier without evidence should be rejected.")


def test_failed_tier_without_error_details_rejected():
    from pydantic import ValidationError

    try:
        TierReport(
            tier=Tier.T1_BEHAVIORAL,
            status=GateStatus.FAILED,
            duration_ms=1,
            summary="silent failure",
        )
    except ValidationError as e:
        assert "error_details MUST be set" in str(e)
        return
    raise AssertionError("Failed tier without error_details should be rejected.")


def test_maturity_missing_required_tier():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    # drop T5
    r["tier_reports"] = [tr for tr in r["tier_reports"] if tr["tier"] != "T5_concurrency"]
    _expect_fail(r, "requires tiers")


def test_experimental_accepts_t0_t1_t6():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    assert len(r["tier_reports"]) == 3
    _expect_ok(r)


def test_t0_static_required_for_experimental():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["tier_reports"] = [tr for tr in r["tier_reports"] if tr["tier"] != "T0_static"]
    _expect_fail(r, "requires tiers")


def test_t0_static_required_for_emerging():
    r = valid_delivery_dict(Maturity.EMERGING)
    r["tier_reports"] = [tr for tr in r["tier_reports"] if tr["tier"] != "T0_static"]
    _expect_fail(r, "requires tiers")


def test_t0_static_required_for_battle_tested():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["tier_reports"] = [tr for tr in r["tier_reports"] if tr["tier"] != "T0_static"]
    _expect_fail(r, "requires tiers")


# ==========================================================================
# SUB-REPORT LINKAGE
# ==========================================================================
def test_t6_passed_without_adversarial_subreport_rejected():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r.pop("adversarial")
    _expect_fail(r, "t6 passed requires adversarial")


def test_t9_passed_without_judge_rejected():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r.pop("judge")
    _expect_fail(r, "t9 passed requires both judge and personas")


def test_t9_passed_without_personas_rejected():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r.pop("personas")
    _expect_fail(r, "t9 passed requires both judge and personas")


def test_t7_passed_without_observability_rejected():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r.pop("observability")
    _expect_fail(r, "t7 passed requires observability")


# ==========================================================================
# LLM COST CAP
# ==========================================================================
def test_experimental_cost_cap_enforced():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["llm_cost_usd"] = 0.26
    _expect_fail(r, "exceeds cap")


def test_emerging_cost_cap_enforced():
    r = valid_delivery_dict(Maturity.EMERGING)
    r["llm_cost_usd"] = 1.01
    _expect_fail(r, "exceeds cap")


def test_battle_tested_cost_cap_enforced():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["llm_cost_usd"] = 2.51
    _expect_fail(r, "exceeds cap")


def test_cost_at_cap_accepted():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["llm_cost_usd"] = 2.50
    _expect_ok(r)
