"""Chaos / fault-injection for OutputGuardrail.

Game-day scenarios: oversize output, Unicode edge cases, nested tool-shapes,
pathological regex inputs, concurrent ledger contention, immutability probes.
"""

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
)


def test_chaos_oversize_output_rejected() -> None:
    g = SafetyOutputGuardrail(name="safety")
    with pytest.raises(OutputGuardrailInvariantError):
        g.evaluate("x" * 2_000_001, None)


def test_chaos_unicode_output_passes_through_safety() -> None:
    g = SafetyOutputGuardrail(name="safety")
    for raw in ("日本語の答え", "🔥💧🦉", "straße", "\u202eoverride"):
        v = g.evaluate(raw, None)
        assert v.action == "pass"


def test_chaos_nested_tool_shape_still_blocked() -> None:
    safety = SafetyOutputGuardrail(name="safety")
    attempts = [
        'prefix <tool_call name="x">body</tool_call> suffix',
        "\n\n<function_call>\ndo()\n</function_call>",
        '<invoke tool="rm">args</invoke>',
        "```tool_code\nexec()\n```",
    ]
    for raw in attempts:
        with pytest.raises(OutputBlocked):
            apply_chain([safety], raw)


def test_chaos_concurrent_ledger_records_are_atomic() -> None:
    ledger = VerdictLedger()
    g = SafetyOutputGuardrail(name="safety")

    def _go() -> None:
        apply_chain([g], "benign", ledger=ledger)

    threads = [threading.Thread(target=_go) for _ in range(64)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # No lost records, no phantom records, every entry attributed.
    entries = ledger.entries()
    assert len(entries) == 64
    assert all(name == "safety" for name, _ in entries)


def test_chaos_verdict_immutable() -> None:
    v = Verdict(action="pass", reason="ok")
    for attr in ("_action", "_reason", "_replacement", "action", "reason", "replacement"):
        with pytest.raises(OutputGuardrailInvariantError):
            setattr(v, attr, "hijacked")


def test_chaos_malformed_json_shape_rejected() -> None:
    schemas: dict[str, dict[str, object]] = {
        "s": {"type": "object", "required": ["k"], "properties": {"k": {"type": "string"}}},
    }
    g = SchemaOutputGuardrail(name="s", schemas=schemas)
    # Mix of adversarial malformed payloads.
    for payload in (
        "",
        "null",           # null instead of object
        "[]",             # array instead of object
        '{"k": 123}',     # wrong type
        '{"other": "x"}', # missing required
        '{"k": "a"',      # truncated
    ):
        v = g.evaluate(payload, "s")
        assert v.action == "block"


def test_chaos_block_pattern_with_many_hits_still_blocks_first() -> None:
    g = PolicyOutputGuardrail(
        name="blk",
        block_patterns=(r"AAA", r"BBB", r"CCC"),
    )
    v = g.evaluate("AAA BBB CCC all in one line", None)
    assert v.action == "block"
    # First matched pattern is cited in the reason.
    assert "AAA" in v.reason


def test_chaos_rewrite_with_many_patterns_applies_all() -> None:
    g = PolicyOutputGuardrail(
        name="redact",
        rewrite_patterns=(
            (r"foo", "FOO"),
            (r"bar", "BAR"),
            (r"baz", "BAZ"),
        ),
    )
    v = g.evaluate("foo bar baz qux", None)
    assert v.action == "rewrite"
    assert v.replacement == "FOO BAR BAZ qux"
