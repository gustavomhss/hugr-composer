"""
Meta-tests for the primitive delivery contract.

Goal: prove each validator in `primitive_delivery_contract.py` accepts valid
input and rejects every specific failure mode. Every rejection path gets at
least one test. If a rule is not tested here, it is not enforced in practice.

Run:
    python3 -m engine.tests.test_delivery_contract
    # or pytest
"""
from __future__ import annotations

import copy
import hashlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from engine.contracts import (  # noqa: E402
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
    PrimitiveDelivery,
    Tier,
    TierReport,
    accept_delivery,
    compute_sha256,
)


# ==========================================================================
# Fixtures
# ==========================================================================

def sha_for(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def make_file(path: str, *, kind: str, body: str = "x") -> FileArtefact:
    return FileArtefact(path=path, sha256=sha_for(body + path), size_bytes=max(1, len(body)), kind=kind)


def make_binding(slug: str, *, text: str | None = None) -> InvariantTestBinding:
    return InvariantTestBinding(
        invariant_id=f"INV_{slug.upper()}",
        invariant_text=text or f"MUST {slug.replace('_', ' ')} within the declared window.",
        confirms_test=f"test_inv_{slug}_confirms",
        prevents_test=f"test_inv_{slug}_prevents",
        under_failure_test=f"test_inv_{slug}_under_failure",
    )


def make_tier_report(tier: Tier, status: GateStatus = GateStatus.PASSED, *, ev: str = "_evidence/x.log") -> TierReport:
    if status == GateStatus.PASSED:
        return TierReport(tier=tier, status=status, duration_ms=10, evidence_path=ev,
                          tool_name="pytest", tool_version="8.0",
                          summary="Passed with evidence captured.")
    if status == GateStatus.FAILED:
        return TierReport(tier=tier, status=status, duration_ms=10,
                          summary="Failed with stderr captured.",
                          error_details="stderr blob for failing test")
    if status == GateStatus.SKIPPED:
        return TierReport(tier=tier, status=status, duration_ms=1,
                          summary="Skipped, tier not applicable for this primitive.")
    return TierReport(tier=tier, status=status, duration_ms=1,
                      summary="Errored, runner crashed.",
                      error_details="traceback snippet")


def _attack(model: str, idx: int, outcome: str = "rejected", violated: str | None = None) -> AdversarialAttack:
    return AdversarialAttack(
        model=model,
        attack_id=f"ATK-N{idx:03d}",
        hypothesis="Adversary input exercises the invariant boundary beyond normal use.",
        input_fixture=f"fixture_{idx}",
        defender_outcome=outcome,
        violated_invariant_id=violated,
    )


def _ensemble_report_clean() -> AdversarialEnsembleReport:
    attacks: list[AdversarialAttack] = []
    for m in ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"):
        for i in range(8):
            attacks.append(_attack(m, i))
    return AdversarialEnsembleReport(
        models_run=["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        attacks=attacks,
        successful_attacks=0,
    )


def _judge_clean() -> LLMJudgeReport:
    axes = [
        JudgeAxis(axis=a, score=9, rationale="Strong evidence in the impl and docs for this axis.")
        for a in ("fidelity", "completeness", "error_quality", "composability",
                  "production_readiness", "catalog_conformance")
    ]
    return LLMJudgeReport(judge_model="claude-opus-4-7", axes=axes)


def _personas_clean() -> PersonaReviewReport:
    return PersonaReviewReport(reviews=[
        PersonaReview(persona=p, understood=True, friction_points=[])
        for p in ("junior_dev", "principal_engineer", "security_auditor", "sre", "pm")
    ])


def _obs_clean() -> ObservabilitySchema:
    return ObservabilitySchema(
        logs=[EmittedLog(event_name="primitive.state.changed", required_attributes=["from", "to", "reason"])],
        metrics=[EmittedMetric(name="primitive.invariant.checks", metric_type="counter",
                               unit="call", cardinality_bound=100, label_keys=["outcome"])],
        spans=[EmittedSpan(operation_name="primitive.public_method",
                           required_attributes=["primitive.name", "primitive.version"])],
    )


def valid_delivery_dict(maturity: Maturity = Maturity.BATTLE_TESTED) -> dict:
    namespace = "obs"
    name = "HealthProbe"

    # Minimum file set depends on maturity. BATTLE_TESTED is the widest.
    files = [
        make_file(f"{namespace}/{name}/{name}.py", kind="impl"),
        make_file(f"{namespace}/{name}/test_{name}.py", kind="test"),
        make_file(f"{namespace}/{name}/behavioral_{name}.py", kind="behavioral"),
        make_file(f"{namespace}/{name}/{name}.md", kind="spec_md"),
        make_file(f"{namespace}/{name}/{name}.manifest.json", kind="manifest"),
    ]
    if maturity is Maturity.BATTLE_TESTED:
        files.extend([
            make_file(f"{namespace}/{name}/state_machine_{name}.py", kind="state_machine"),
            make_file(f"{namespace}/{name}/metamorphic_{name}.py", kind="metamorphic"),
            make_file(f"{namespace}/{name}/concurrent_{name}.py", kind="concurrent"),
            make_file(f"{namespace}/{name}/adversarial_claude_opus.json", kind="adversarial"),
            make_file(f"{namespace}/{name}/chaos_{name}.py", kind="chaos"),
            make_file(f"{namespace}/{name}/observability_{name}.py", kind="observability"),
            make_file(f"{namespace}/{name}/dashboard.json", kind="dashboard"),
            make_file(f"{namespace}/{name}/{name}.contract.json", kind="contract_json"),
            make_file(f"{namespace}/{name}/persona_reviews.json", kind="persona_reviews"),
            make_file(f"{namespace}/{name}/proposed_invariants.json", kind="proposed_invariants"),
        ])

    bindings = [make_binding(f"s{i}") for i in range(3)]

    tier_reports = [
        make_tier_report(Tier.T0_STATIC),
        make_tier_report(Tier.T1_BEHAVIORAL),
        make_tier_report(Tier.T6_ADVERSARIAL),
    ]
    if maturity is Maturity.BATTLE_TESTED:
        tier_reports = [make_tier_report(t) for t in Tier]
    elif maturity is Maturity.EMERGING:
        tier_reports = [make_tier_report(t) for t in (
            Tier.T0_STATIC, Tier.T1_BEHAVIORAL, Tier.T3_STATE_MACHINE,
            Tier.T4_METAMORPHIC, Tier.T6_ADVERSARIAL, Tier.T7_OBSERVABILITY,
        )]

    raw: dict = {
        "name": name,
        "namespace": namespace,
        "maturity": maturity.value,
        "builder_agent_id": 1,
        "catalog_entry_sha256": "0" * 64,
        "files": [f.model_dump() for f in files],
        "invariant_bindings": [b.model_dump() for b in bindings],
        "tier_reports": [r.model_dump() for r in tier_reports],
        "build_duration_ms": 5000,
        "llm_cost_usd": 0.10,
    }
    # Always attach sub-reports that the selected tiers require.
    tier_ids = {tr["tier"] for tr in raw["tier_reports"]}
    if "T6_adversarial" in tier_ids:
        raw["adversarial"] = _ensemble_report_clean().model_dump()
    if "T9_meta" in tier_ids:
        raw["judge"] = _judge_clean().model_dump()
        raw["personas"] = _personas_clean().model_dump()
    if "T7_observability" in tier_ids:
        raw["observability"] = _obs_clean().model_dump()
    return raw


def _expect_ok(raw: dict) -> PrimitiveDelivery:
    ok, parsed, errors = accept_delivery(raw)
    assert ok, f"Expected valid, got errors: {errors}"
    assert parsed is not None
    return parsed


def _expect_fail(raw: dict, needle: str) -> None:
    ok, _, errors = accept_delivery(raw)
    assert not ok, f"Expected failure mentioning '{needle}', but payload passed."
    blob = " | ".join(errors).lower()
    assert needle.lower() in blob, f"Wrong rejection reason. needle={needle!r}, errors={errors}"


# ==========================================================================
# POSITIVE — full valid deliveries at each maturity
# ==========================================================================
def test_valid_battle_tested_passes():
    _expect_ok(valid_delivery_dict(Maturity.BATTLE_TESTED))


def test_valid_emerging_passes():
    _expect_ok(valid_delivery_dict(Maturity.EMERGING))


def test_valid_experimental_passes():
    _expect_ok(valid_delivery_dict(Maturity.EXPERIMENTAL))


def test_compute_sha256_matches_python_hashlib():
    assert compute_sha256(b"abc") == hashlib.sha256(b"abc").hexdigest()


# ==========================================================================
# IDENTITY — name, namespace, builder_agent_id, maturity, catalog_entry_sha256
# ==========================================================================
def test_name_rejects_lowercase_start():
    r = valid_delivery_dict()
    r["name"] = "healthProbe"
    _expect_fail(r, "string should match pattern")


def test_name_rejects_underscore():
    r = valid_delivery_dict()
    r["name"] = "Health_Probe"
    _expect_fail(r, "string should match pattern")


def test_name_rejects_too_long():
    r = valid_delivery_dict()
    r["name"] = "A" * 41
    _expect_fail(r, "at most 40 characters")


def test_name_accepts_pascal_with_digits():
    r = valid_delivery_dict()
    r["name"] = "HealthProbeV2"
    # Also need to reflect into file paths + catalog dirs — so instead, verify pattern accepts.
    from pydantic import ValidationError
    try:
        PrimitiveDelivery.model_validate(r)
    except ValidationError as e:
        # The path_name_consistency check will trip; we only assert the name regex accepts.
        assert "should match pattern" not in str(e).split("name")[0].lower(), str(e)


def test_namespace_rejects_uppercase():
    r = valid_delivery_dict()
    r["namespace"] = "Obs"
    _expect_fail(r, "string should match pattern")


def test_namespace_rejects_hyphen():
    r = valid_delivery_dict()
    r["namespace"] = "obs-ext"
    _expect_fail(r, "string should match pattern")


def test_builder_agent_out_of_range_low():
    r = valid_delivery_dict()
    r["builder_agent_id"] = 0
    _expect_fail(r, "greater than or equal to 1")


def test_builder_agent_out_of_range_high():
    r = valid_delivery_dict()
    r["builder_agent_id"] = 11
    _expect_fail(r, "less than or equal to 10")


def test_maturity_invalid_value():
    r = valid_delivery_dict()
    r["maturity"] = "unstable"
    _expect_fail(r, "input should be")


def test_catalog_sha256_must_be_hex():
    r = valid_delivery_dict()
    r["catalog_entry_sha256"] = "G" * 64
    _expect_fail(r, "string should match pattern")


def test_catalog_sha256_must_be_64_chars():
    r = valid_delivery_dict()
    r["catalog_entry_sha256"] = "0" * 63
    _expect_fail(r, "string should match pattern")


# ==========================================================================
# FILES — FileArtefact + collection rules
# ==========================================================================
def test_file_path_rejects_absolute():
    r = valid_delivery_dict()
    r["files"][0]["path"] = "/etc/secrets"
    _expect_fail(r, "relative")


def test_file_path_rejects_parent_traversal():
    r = valid_delivery_dict()
    r["files"][0]["path"] = "obs/HealthProbe/../etc/x.py"
    _expect_fail(r, "traverse")


def test_file_path_rejects_dotfile():
    r = valid_delivery_dict()
    r["files"][0]["path"] = "obs/HealthProbe/.env"
    _expect_fail(r, "dotfiles")


def test_file_sha_must_be_hex():
    r = valid_delivery_dict()
    r["files"][0]["sha256"] = "XYZ" + "0" * 61
    _expect_fail(r, "string should match pattern")


def test_file_size_zero_rejected():
    r = valid_delivery_dict()
    r["files"][0]["size_bytes"] = 0
    _expect_fail(r, "greater than or equal to 1")


def test_file_size_too_large_rejected():
    r = valid_delivery_dict()
    r["files"][0]["size_bytes"] = 5_000_001
    _expect_fail(r, "less than or equal to 5000000")


def test_file_kind_enum():
    r = valid_delivery_dict()
    r["files"][0]["kind"] = "whatever"
    _expect_fail(r, "string should match pattern")


def test_files_duplicate_path_rejected():
    r = valid_delivery_dict()
    # duplicate the first file path under a new sha (so sha dedup doesn't fire first)
    dup = copy.deepcopy(r["files"][0])
    dup["sha256"] = "a" * 64
    r["files"].append(dup)
    _expect_fail(r, "duplicate file paths")


def test_files_duplicate_sha_rejected():
    r = valid_delivery_dict()
    dup = copy.deepcopy(r["files"][0])
    dup["path"] = "obs/HealthProbe/different_name.py"
    dup["kind"] = "test"
    r["files"].append(dup)
    _expect_fail(r, "duplicate sha-256")


def _swap_kind(files: list[dict], drop_kind: str, add_kind: str, add_suffix: str) -> list[dict]:
    """Drop one file of drop_kind; add a valid filler of add_kind to keep count."""
    out = [f for f in files if f["kind"] != drop_kind]
    filler = make_file(
        f"obs/HealthProbe/filler_{add_suffix}.py",
        kind=add_kind,
        body=f"filler_{add_suffix}",
    )
    out.append(filler.model_dump())
    return out


def test_required_files_missing_impl():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "impl", "state_machine", "a")
    _expect_fail(r, "impl")


def test_required_files_missing_test():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "test", "state_machine", "b")
    _expect_fail(r, "test")


def test_required_files_missing_behavioral():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "behavioral", "state_machine", "c")
    _expect_fail(r, "behavioral")


def test_required_files_missing_spec_md():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "spec_md", "state_machine", "d")
    _expect_fail(r, "spec_md")


def test_required_files_missing_manifest():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "manifest", "state_machine", "e")
    _expect_fail(r, "manifest")


def test_battle_tested_requires_state_machine():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "state_machine"]
    _expect_fail(r, "state_machine")


def test_battle_tested_requires_chaos():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "chaos"]
    _expect_fail(r, "chaos")


def test_battle_tested_requires_observability_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "observability"]
    _expect_fail(r, "observability")


def test_battle_tested_does_not_require_adversarial_file_artefact():
    # Adversarial evidence lives under _evidence/ (excluded from file scan);
    # the structured sub-report is validated on PrimitiveDelivery.adversarial.
    # Therefore dropping the file kind alone MUST pass; dropping the sub-report
    # is tested separately in test_t6_passed_without_adversarial_subreport_rejected.
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "adversarial"]
    _expect_ok(r)


def test_battle_tested_requires_persona_reviews_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "persona_reviews"]
    _expect_fail(r, "persona_reviews")


def test_battle_tested_requires_proposed_invariants_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "proposed_invariants"]
    _expect_fail(r, "proposed_invariants")


def test_battle_tested_requires_dashboard_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "dashboard"]
    _expect_fail(r, "dashboard")


def test_battle_tested_requires_contract_json_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "contract_json"]
    _expect_fail(r, "contract_json")


def test_off_tree_file_rejected():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"][0]["path"] = "other_namespace/other_name/impl.py"
    _expect_fail(r, "off-tree")


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
    r["invariant_bindings"][1]["under_failure_test"] = r["invariant_bindings"][0]["under_failure_test"]
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
        TierReport(tier=Tier.T1_BEHAVIORAL, status=GateStatus.PASSED,
                   duration_ms=1, summary="no evidence")
    except ValidationError as e:
        assert "evidence_path MUST be set" in str(e)
        return
    raise AssertionError("Passed tier without evidence should be rejected.")


def test_failed_tier_without_error_details_rejected():
    from pydantic import ValidationError
    try:
        TierReport(tier=Tier.T1_BEHAVIORAL, status=GateStatus.FAILED,
                   duration_ms=1, summary="silent failure")
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
        assert "at least 20 items" in str(e).lower() or "list should have at least 20" in str(e).lower()
        return
    raise AssertionError("<20 attacks should be rejected.")


def test_ensemble_any_successful_rejected():
    from pydantic import ValidationError
    attacks = list(_ensemble_report_clean().attacks)
    attacks[0] = _attack("claude-opus-4-7", 0, outcome="violated_invariant", violated="INV_X")
    try:
        AdversarialEnsembleReport(
            models_run=["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
            attacks=attacks, successful_attacks=1,
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
            attacks=attacks, successful_attacks=3,
        )
    except ValidationError as e:
        assert "claims 3" in str(e).lower() or "observed" in str(e).lower()
        return
    raise AssertionError("Claim-mismatch in successful_attacks count should be rejected.")


def test_attack_leaked_outcome_requires_violation_id():
    from pydantic import ValidationError
    try:
        AdversarialAttack(model="claude-opus-4-7", attack_id="ATK-LEAK-01",
                          hypothesis="Exfiltrate via error path exposing stack to the caller.",
                          input_fixture="...", defender_outcome="leaked")
    except ValidationError as e:
        assert "must cite the violated invariant id" in str(e).lower()
        return
    raise AssertionError("Leaked outcome without violation_id should be rejected.")


def test_attack_id_pattern_enforced():
    from pydantic import ValidationError
    try:
        AdversarialAttack(model="claude-opus-4-7", attack_id="bad-id",
                          hypothesis="Adversary does not satisfy attack_id pattern.",
                          input_fixture="x", defender_outcome="rejected")
    except ValidationError as e:
        assert "pattern" in str(e).lower()
        return
    raise AssertionError("attack_id pattern violation should be rejected.")


# ==========================================================================
# LLM JUDGE REPORT
# ==========================================================================
def test_judge_requires_six_unique_axes():
    from pydantic import ValidationError
    axes = [JudgeAxis(axis="fidelity", score=9,
                      rationale="solid reasoning over the impl and docs evidence")] * 6
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
        for a in ("completeness", "error_quality", "composability",
                  "production_readiness", "catalog_conformance")
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
        for a in ("fidelity", "completeness", "error_quality",
                  "composability", "production_readiness")
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
    reviews = [PersonaReview(persona=p, understood=True)
               for p in ("junior_dev", "principal_engineer", "security_auditor", "sre")]
    try:
        PersonaReviewReport(reviews=reviews)
    except ValidationError as e:
        assert "at least 5" in str(e).lower() or "length" in str(e).lower()
        return
    raise AssertionError("Four personas should be rejected.")


def test_personas_all_must_understand():
    from pydantic import ValidationError
    reviews = [PersonaReview(persona=p, understood=True)
               for p in ("junior_dev", "principal_engineer", "security_auditor", "sre")]
    reviews.append(PersonaReview(persona="pm", understood=False,
                                 friction_points=["Too much jargon"]))
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
        EmittedMetric(name="foo.bar", metric_type="invalid",
                      unit="call", cardinality_bound=1)
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
            metrics=[EmittedMetric(name="foo.bar", metric_type="counter", unit="call", cardinality_bound=1)],
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
        TierReport(tier=Tier.T1_BEHAVIORAL, status=GateStatus.SKIPPED,
                   duration_ms=3_600_001, summary="too slow")
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
            invariant_text="MUST x",          # 7 chars
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
        FileArtefact(path="abc", sha256="0"*64, size_bytes=1, kind="impl")
    except ValidationError as e:
        assert "at least 5" in str(e).lower()
        return
    raise AssertionError("Too-short file path should be rejected.")


def test_file_path_max_length():
    from pydantic import ValidationError
    try:
        FileArtefact(path="x" * 201, sha256="0"*64, size_bytes=1, kind="impl")
    except ValidationError as e:
        assert "at most 200" in str(e).lower()
        return
    raise AssertionError("Too-long file path should be rejected.")


# ==========================================================================
# MANUAL runner (pytest-less)
# ==========================================================================
def _run() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed: list[tuple[str, str]] = []
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✓ {t.__name__}")
        except Exception:
            failed.append((t.__name__, traceback.format_exc()))
            print(f"  ✗ {t.__name__}")
    print(f"\n{passed}/{len(tests)} passed")
    for name, tb in failed:
        print(f"\n--- {name} ---\n{tb}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(_run())
