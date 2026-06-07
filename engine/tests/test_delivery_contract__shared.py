"""
Shared fixtures/helpers for the primitive delivery contract meta-tests.

This module is imported by the test_delivery_contract__partN.py siblings.
It contains no tests itself; only the fixture factory functions and the
accept/reject assertion helpers that the split test files share.
"""

from __future__ import annotations

import copy
import hashlib
import sys
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
    return FileArtefact(
        path=path, sha256=sha_for(body + path), size_bytes=max(1, len(body)), kind=kind
    )


def make_binding(slug: str, *, text: str | None = None) -> InvariantTestBinding:
    return InvariantTestBinding(
        invariant_id=f"INV_{slug.upper()}",
        invariant_text=text or f"MUST {slug.replace('_', ' ')} within the declared window.",
        confirms_test=f"test_inv_{slug}_confirms",
        prevents_test=f"test_inv_{slug}_prevents",
        under_failure_test=f"test_inv_{slug}_under_failure",
    )


def make_tier_report(
    tier: Tier, status: GateStatus = GateStatus.PASSED, *, ev: str = "_evidence/x.log"
) -> TierReport:
    if status == GateStatus.PASSED:
        return TierReport(
            tier=tier,
            status=status,
            duration_ms=10,
            evidence_path=ev,
            tool_name="pytest",
            tool_version="8.0",
            summary="Passed with evidence captured.",
        )
    if status == GateStatus.FAILED:
        return TierReport(
            tier=tier,
            status=status,
            duration_ms=10,
            summary="Failed with stderr captured.",
            error_details="stderr blob for failing test",
        )
    if status == GateStatus.SKIPPED:
        return TierReport(
            tier=tier,
            status=status,
            duration_ms=1,
            summary="Skipped, tier not applicable for this primitive.",
        )
    return TierReport(
        tier=tier,
        status=status,
        duration_ms=1,
        summary="Errored, runner crashed.",
        error_details="traceback snippet",
    )


def _attack(
    model: str, idx: int, outcome: str = "rejected", violated: str | None = None
) -> AdversarialAttack:
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
        for a in (
            "fidelity",
            "completeness",
            "error_quality",
            "composability",
            "production_readiness",
            "catalog_conformance",
        )
    ]
    return LLMJudgeReport(judge_model="claude-opus-4-7", axes=axes)


def _personas_clean() -> PersonaReviewReport:
    return PersonaReviewReport(
        reviews=[
            PersonaReview(persona=p, understood=True, friction_points=[])
            for p in ("junior_dev", "principal_engineer", "security_auditor", "sre", "pm")
        ]
    )


def _obs_clean() -> ObservabilitySchema:
    return ObservabilitySchema(
        logs=[
            EmittedLog(
                event_name="primitive.state.changed", required_attributes=["from", "to", "reason"]
            )
        ],
        metrics=[
            EmittedMetric(
                name="primitive.invariant.checks",
                metric_type="counter",
                unit="call",
                cardinality_bound=100,
                label_keys=["outcome"],
            )
        ],
        spans=[
            EmittedSpan(
                operation_name="primitive.public_method",
                required_attributes=["primitive.name", "primitive.version"],
            )
        ],
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
        files.extend(
            [
                make_file(f"{namespace}/{name}/state_machine_{name}.py", kind="state_machine"),
                make_file(f"{namespace}/{name}/metamorphic_{name}.py", kind="metamorphic"),
                make_file(f"{namespace}/{name}/concurrent_{name}.py", kind="concurrent"),
                make_file(f"{namespace}/{name}/adversarial_claude_opus.json", kind="adversarial"),
                make_file(f"{namespace}/{name}/chaos_{name}.py", kind="chaos"),
                make_file(f"{namespace}/{name}/observability_{name}.py", kind="observability"),
                make_file(f"{namespace}/{name}/dashboard.json", kind="dashboard"),
                make_file(f"{namespace}/{name}/{name}.contract.json", kind="contract_json"),
                make_file(f"{namespace}/{name}/persona_reviews.json", kind="persona_reviews"),
                make_file(
                    f"{namespace}/{name}/proposed_invariants.json", kind="proposed_invariants"
                ),
            ]
        )

    bindings = [make_binding(f"s{i}") for i in range(3)]

    tier_reports = [
        make_tier_report(Tier.T0_STATIC),
        make_tier_report(Tier.T1_BEHAVIORAL),
        make_tier_report(Tier.T6_ADVERSARIAL),
    ]
    if maturity is Maturity.BATTLE_TESTED:
        tier_reports = [make_tier_report(t) for t in Tier]
    elif maturity is Maturity.EMERGING:
        tier_reports = [
            make_tier_report(t)
            for t in (
                Tier.T0_STATIC,
                Tier.T1_BEHAVIORAL,
                Tier.T3_STATE_MACHINE,
                Tier.T4_METAMORPHIC,
                Tier.T6_ADVERSARIAL,
                Tier.T7_OBSERVABILITY,
            )
        ]

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


# Re-export the copy module symbol used by some test files for deepcopy.
__all__ = [
    "copy",
    "hashlib",
    "AdversarialAttack",
    "AdversarialEnsembleReport",
    "EmittedLog",
    "EmittedMetric",
    "EmittedSpan",
    "FileArtefact",
    "GateStatus",
    "InvariantTestBinding",
    "JudgeAxis",
    "LLMJudgeReport",
    "Maturity",
    "ObservabilitySchema",
    "PersonaReview",
    "PersonaReviewReport",
    "PrimitiveDelivery",
    "Tier",
    "TierReport",
    "accept_delivery",
    "compute_sha256",
    "sha_for",
    "make_file",
    "make_binding",
    "make_tier_report",
    "_attack",
    "_ensemble_report_clean",
    "_judge_clean",
    "_personas_clean",
    "_obs_clean",
    "valid_delivery_dict",
    "_expect_ok",
    "_expect_fail",
]
