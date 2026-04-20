"""Behavioral end-to-end scenarios for OutputGuardrail — proves invariants at runtime."""

from __future__ import annotations

import pytest

from OutputGuardrail import (
    OutputBlocked,
    PolicyOutputGuardrail,
    SafetyOutputGuardrail,
    SchemaOutputGuardrail,
    VerdictLedger,
    apply_chain,
)

_SCHEMAS: dict[str, dict[str, object]] = {
    "answer.v1": {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    },
}


def test_scenario_pass_through_chain() -> None:
    # Pure pass-through: schema valid, no policy hits, no tool shapes.
    ledger = VerdictLedger()
    chain = [
        SafetyOutputGuardrail(name="safety"),
        PolicyOutputGuardrail(name="policy"),
        SchemaOutputGuardrail(name="schema", schemas=_SCHEMAS),
    ]
    out = apply_chain(chain, '{"answer": "42"}', schema_ref="answer.v1", ledger=ledger)
    assert out == '{"answer": "42"}'
    # Every guard contributed a verdict to the ledger (GUARD-INV-05).
    assert ledger.size() == 3
    assert {name for name, _ in ledger.entries()} == {"safety", "policy", "schema"}


def test_scenario_rewrite_redacts_pii() -> None:
    # Rewriter redacts a PII-looking pattern; downstream still passes.
    ledger = VerdictLedger()
    chain = [
        SafetyOutputGuardrail(name="safety"),
        PolicyOutputGuardrail(
            name="redactor",
            rewrite_patterns=((r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),),
        ),
    ]
    out = apply_chain(chain, "My SSN is 123-45-6789.", ledger=ledger)
    assert out == "My SSN is [SSN]."
    redactor_verdicts = ledger.entries_for("redactor")
    assert len(redactor_verdicts) == 1
    assert redactor_verdicts[0].action == "rewrite"
    assert redactor_verdicts[0].replacement == "My SSN is [SSN]."


def test_scenario_block_halts_pipeline_and_attributes() -> None:
    # BLOCK verdict halts and the exception carries attribution (GUARD-INV-02, 05).
    ledger = VerdictLedger()
    chain = [
        PolicyOutputGuardrail(name="banlist", block_patterns=(r"CREDENTIALS",)),
        SafetyOutputGuardrail(name="safety"),
    ]
    with pytest.raises(OutputBlocked) as ei:
        apply_chain(chain, "leak CREDENTIALS now", ledger=ledger)
    assert ei.value.guardrail == "banlist"
    # Second guard never runs — ledger has only the blocker's record.
    names = [n for n, _ in ledger.entries()]
    assert names == ["banlist"]


def test_scenario_tool_call_shape_blocked_before_execution() -> None:
    # Adversarial output containing a tool-call shape is blocked BEFORE any
    # downstream code could parse it (GUARD-INV-04).
    safety = SafetyOutputGuardrail(name="safety")
    with pytest.raises(OutputBlocked) as ei:
        apply_chain([safety], '<tool_call name="rm -rf">/</tool_call>')
    assert "tool-call-shape" in ei.value.reason


def test_scenario_schema_then_policy_then_safety_order_matters() -> None:
    # The ordered chain semantics (NeMo-style "output rails"): earlier
    # guards see the raw output; later guards see any rewrites.
    chain = [
        PolicyOutputGuardrail(
            name="normalize", rewrite_patterns=((r"\bfoo\b", "bar"),)
        ),
        PolicyOutputGuardrail(name="banbar", block_patterns=(r"bar",)),
    ]
    with pytest.raises(OutputBlocked) as ei:
        apply_chain(chain, "this says foo exactly")
    # The block happened AFTER the rewrite, proving the chain propagated
    # the rewritten text.
    assert ei.value.guardrail == "banbar"


def test_scenario_empty_chain_returns_raw_unchanged() -> None:
    # Degenerate but explicit: no guards → no verdicts → raw returned verbatim.
    ledger = VerdictLedger()
    out = apply_chain([], "pristine output", ledger=ledger)
    assert out == "pristine output"
    assert ledger.size() == 0
