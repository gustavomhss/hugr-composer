"""Chaos / fault-injection for InputGuardrail.

Game-day scenarios: malformed input types, guard raises mid-chain, adversarial
pipelines, concurrent apply(), oversized inputs. The chain MUST remain correct
(no silent allow, no clear-text in audit) under each.
"""

from __future__ import annotations

import threading

import pytest

from InputGuardrail import (
    Chain,
    Decision,
    DenyList,
    GuardBlocked,
    InputGuardrailInvariantError,
    LengthLimit,
    PIIRedactor,
    PromptInjectionBlocker,
)


def test_chaos_non_string_input_rejected() -> None:
    chain = Chain([PIIRedactor()])
    with pytest.raises(InputGuardrailInvariantError):
        chain.apply(12345, {})  # type: ignore[arg-type] — GUARD-INV-04 defense


def test_chaos_guard_raising_mid_chain_propagates() -> None:
    class Boom:
        name = "boom"

        def evaluate(self, text: str, context: dict[str, str]) -> Decision:
            raise RuntimeError("guard crashed")

    chain = Chain([PIIRedactor(), Boom()])
    with pytest.raises(RuntimeError):
        chain.apply("plain", {})


def test_chaos_concurrent_apply_preserves_audit_consistency() -> None:
    chain = Chain([PromptInjectionBlocker()])
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            for i in range(20):
                chain.apply(f"msg-{idx}-{i}", {})
        except BaseException as exc:  # pragma: no cover — defensive
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Bounded ring: at most MAX_AUDIT_ENTRIES rows.
    assert len(chain.audit) <= 1_000
    # Sequence numbers are strictly monotonic in the retained window.
    seqs = [e.seq for e in chain.audit]
    assert seqs == sorted(seqs)


def test_chaos_oversized_input_blocked_without_crash() -> None:
    chain = Chain([LengthLimit(max_chars=1024)])
    huge = "A" * 10_000
    with pytest.raises(GuardBlocked):
        chain.apply(huge, {})


def test_chaos_malformed_decision_from_custom_guard_rejected() -> None:
    # A custom guard that returns a decision claiming redact but with None text
    # MUST be rejected by the chain's defense-in-depth validation.
    class Liar:
        name = "liar"

        def evaluate(self, text: str, context: dict[str, str]) -> Decision:
            # Build a Decision but bypass slot setter with object.__setattr__ to
            # simulate a corrupt third-party implementation.
            d = Decision(action="allow", reason="fine")
            object.__setattr__(d, "action", "redact")
            object.__setattr__(d, "redacted_text", None)
            return d

    chain = Chain([Liar()])
    with pytest.raises(InputGuardrailInvariantError):
        chain.apply("anything", {})


def test_chaos_empty_denylist_rejected_at_construction() -> None:
    with pytest.raises(InputGuardrailInvariantError):
        DenyList("empty", terms=[])


def test_chaos_empty_chain_rejected() -> None:
    with pytest.raises(InputGuardrailInvariantError):
        Chain([])


def test_chaos_sealed_chain_rejects_further_apply() -> None:
    chain = Chain([PromptInjectionBlocker()])
    chain.apply("first", {})
    chain.seal()
    with pytest.raises(InputGuardrailInvariantError):
        chain.apply("second", {})
    assert chain.state == "sealed"
