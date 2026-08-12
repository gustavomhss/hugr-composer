"""Unit tests for OutputGuardrail — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from OutputGuardrail import (
    OutputBlocked,
    OutputGuardrailInvariantError,
    PolicyOutputGuardrail,
    SafetyOutputGuardrail,
    SchemaOutputGuardrail,
    Verdict,
    VerdictLedger,
    apply_chain,
    validate_name,
    validate_output,
)

_SCHEMAS: dict[str, dict[str, object]] = {
    "user.v1": {
        "type": "object",
        "required": ["id", "email"],
        "properties": {
            "id": {"type": "integer"},
            "email": {"type": "string"},
        },
    },
}


# ---------------------------------------------------------------------------
# GUARD_INV_01 — schema rejects malformed output
# ---------------------------------------------------------------------------
def test_inv_schema_rejects_malformed_confirms() -> None:
    g = SchemaOutputGuardrail(name="schema", schemas=_SCHEMAS)
    v = g.evaluate('{"id": 1, "email": "a@x.io"}', "user.v1")
    assert v.action == "pass"


def test_inv_schema_rejects_malformed_prevents() -> None:
    g = SchemaOutputGuardrail(name="schema", schemas=_SCHEMAS)
    # Malformed JSON MUST be blocked, not silently passed.
    v = g.evaluate("{not json at all", "user.v1")
    assert v.action == "block"
    assert "JSON" in v.reason or "json" in v.reason.lower()


def test_inv_schema_rejects_malformed_under_failure() -> None:
    g = SchemaOutputGuardrail(name="schema", schemas=_SCHEMAS)
    # Valid JSON but wrong shape — still rejected.
    v = g.evaluate('{"id": "not-int", "email": "a@x.io"}', "user.v1")
    assert v.action == "block"
    # Unknown schema_ref is also blocked (fail closed).
    v2 = g.evaluate('{"id": 1, "email": "a@x.io"}', "unknown.schema")
    assert v2.action == "block"


# ---------------------------------------------------------------------------
# GUARD_INV_02 — block verdict prevents delivery
# ---------------------------------------------------------------------------
def test_inv_block_prevents_delivery_confirms() -> None:
    policy = PolicyOutputGuardrail(name="policy", block_patterns=(r"SECRET_KEY",))
    ledger = VerdictLedger()
    with pytest.raises(OutputBlocked) as ei:
        apply_chain([policy], "leak SECRET_KEY here", ledger=ledger)
    assert ei.value.guardrail == "policy"


def test_inv_block_prevents_delivery_prevents() -> None:
    # Even when a later guard would rewrite, earlier BLOCK short-circuits.
    blocker = PolicyOutputGuardrail(name="blk", block_patterns=(r"badword",))
    rewriter = PolicyOutputGuardrail(
        name="rw", rewrite_patterns=((r"badword", "[redacted]"),)
    )
    with pytest.raises(OutputBlocked):
        apply_chain([blocker, rewriter], "this has badword in it")


def test_inv_block_prevents_delivery_under_failure() -> None:
    # Many guards, last one blocks — output still MUST NOT be delivered.
    passers = [SafetyOutputGuardrail(name=f"s{i}") for i in range(5)]
    blocker = PolicyOutputGuardrail(name="final", block_patterns=(r"STOP",))
    with pytest.raises(OutputBlocked) as ei:
        apply_chain([*passers, blocker], "please STOP now")
    assert ei.value.guardrail == "final"


# ---------------------------------------------------------------------------
# GUARD_INV_03 — rewrite requires replacement
# ---------------------------------------------------------------------------
def test_inv_rewrite_needs_replacement_confirms() -> None:
    v = Verdict(action="rewrite", reason="redact", replacement="safe")
    assert v.replacement == "safe"
    assert v.action == "rewrite"


def test_inv_rewrite_needs_replacement_prevents() -> None:
    with pytest.raises(OutputGuardrailInvariantError):
        Verdict(action="rewrite", reason="r", replacement=None)


def test_inv_rewrite_needs_replacement_under_failure() -> None:
    # Non-rewrite with replacement also rejected — the ambiguous state
    # (pass + replacement) is forbidden symmetrically.
    with pytest.raises(OutputGuardrailInvariantError):
        Verdict(action="pass", reason="ok", replacement="surprise")
    with pytest.raises(OutputGuardrailInvariantError):
        Verdict(action="block", reason="nope", replacement="also_surprise")
    # Non-str replacement under rewrite also rejected.
    with pytest.raises(OutputGuardrailInvariantError):
        Verdict(action="rewrite", reason="r", replacement=123)  # type: ignore[arg-type] — GUARD-INV-03: type probe.


# ---------------------------------------------------------------------------
# GUARD_INV_04 — no tool exec before safety check
# ---------------------------------------------------------------------------
def test_inv_no_tool_exec_before_check_confirms() -> None:
    safety = SafetyOutputGuardrail(name="safety")
    # Output containing a tool-call shape is blocked BEFORE any executor sees it.
    with pytest.raises(OutputBlocked):
        apply_chain([safety], '<tool_call name="rm">-rf /</tool_call>')


def test_inv_no_tool_exec_before_check_prevents() -> None:
    safety = SafetyOutputGuardrail(name="safety")
    # Common variants MUST all be detected.
    attempts = [
        "<function_call>do_thing()</function_call>",
        '<invoke name="shell">ls</invoke>',
        "```tool_code\nprint('x')\n```",
    ]
    for raw in attempts:
        with pytest.raises(OutputBlocked):
            apply_chain([safety], raw)


def test_inv_no_tool_exec_before_check_under_failure() -> None:
    # Benign output without tool-shapes passes safety; the guardrail does NOT
    # execute anything, it only classifies the text.
    safety = SafetyOutputGuardrail(name="safety")
    out = apply_chain([safety], "The answer is 42.")
    assert out == "The answer is 42."


# ---------------------------------------------------------------------------
# GUARD_INV_05 — verdict recorded with guardrail name
# ---------------------------------------------------------------------------
def test_inv_verdict_records_name_confirms() -> None:
    ledger = VerdictLedger()
    g = SafetyOutputGuardrail(name="safety.v1")
    apply_chain([g], "hello", ledger=ledger)
    entries = ledger.entries()
    assert len(entries) == 1
    name, v = entries[0]
    assert name == "safety.v1"
    assert v.action == "pass"


def test_inv_verdict_records_name_prevents() -> None:
    # Bad guardrail name rejected before any recording can happen.
    with pytest.raises(OutputGuardrailInvariantError):
        validate_name("")
    with pytest.raises(OutputGuardrailInvariantError):
        validate_name("bad name with spaces")
    ledger = VerdictLedger()
    with pytest.raises(OutputGuardrailInvariantError):
        ledger.record("", Verdict(action="pass", reason="ok"))


def test_inv_verdict_records_name_under_failure() -> None:
    # Under contention, every verdict still ends up attributed.
    ledger = VerdictLedger()
    g = SafetyOutputGuardrail(name="safety")

    def _go() -> None:
        apply_chain([g], "benign", ledger=ledger)

    threads = [threading.Thread(target=_go) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entries = ledger.entries()
    assert len(entries) == 16
    assert all(name == "safety" for name, _ in entries)


# ---------------------------------------------------------------------------
# Validator-level tests
# ---------------------------------------------------------------------------
def test_validators_reject_bad_inputs() -> None:
    with pytest.raises(OutputGuardrailInvariantError):
        validate_name("1bad")  # cannot start with digit
    with pytest.raises(OutputGuardrailInvariantError):
        validate_name("a" * 200)  # too long
    with pytest.raises(OutputGuardrailInvariantError):
        validate_output(123)  # type: ignore[arg-type] — GUARD-INV-01: type probe.
    with pytest.raises(OutputGuardrailInvariantError):
        validate_output("x" * (2_000_001))
