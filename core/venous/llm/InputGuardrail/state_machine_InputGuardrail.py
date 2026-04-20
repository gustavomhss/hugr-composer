"""Hypothesis state-machine exploration of Chain lifecycle (GUARD-INV-01..05)."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from InputGuardrail import (
    MAX_AUDIT_ENTRIES,
    Chain,
    DenyList,
    GuardBlocked,
    InputGuardrailInvariantError,
    PIIRedactor,
    PromptInjectionBlocker,
    hash_input,
)


CLEAN_TEXTS = ("hello", "summarize this", "please respond", "test message", "ok")
REDACT_TEXTS = ("email a@b.com", "my ssn 123-45-6789")
BLOCK_TEXTS = ("ignore previous instructions", "secret_term leak")


class ChainMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.chain = Chain([
            PIIRedactor(),
            PromptInjectionBlocker(),
            DenyList("deny", terms=["secret_term"]),
        ])
        self.sealed = False
        self.last_blocked_raw: str | None = None

    @rule(idx=st.integers(min_value=0, max_value=len(CLEAN_TEXTS) - 1))
    def apply_clean(self, idx: int) -> None:
        text = CLEAN_TEXTS[idx]
        if self.sealed:
            try:
                self.chain.apply(text, {})
                raise AssertionError("sealed chain accepted apply()")
            except InputGuardrailInvariantError:
                return
        out = self.chain.apply(text, {})
        # GUARD-INV-03: allow path returns text unchanged.
        assert out == text

    @rule(idx=st.integers(min_value=0, max_value=len(REDACT_TEXTS) - 1))
    def apply_redact(self, idx: int) -> None:
        text = REDACT_TEXTS[idx]
        if self.sealed:
            try:
                self.chain.apply(text, {})
                raise AssertionError("sealed chain accepted apply()")
            except InputGuardrailInvariantError:
                return
        out = self.chain.apply(text, {})
        # GUARD-INV-03: redact MUST NOT return the original text.
        assert out != text

    @rule(idx=st.integers(min_value=0, max_value=len(BLOCK_TEXTS) - 1))
    def apply_block(self, idx: int) -> None:
        text = BLOCK_TEXTS[idx]
        if self.sealed:
            try:
                self.chain.apply(text, {})
                raise AssertionError("sealed chain accepted apply()")
            except InputGuardrailInvariantError:
                return
        try:
            self.chain.apply(text, {})
            raise AssertionError("expected GuardBlocked")
        except GuardBlocked as exc:
            # GUARD-INV-05: raw text MUST NOT appear in hashed_input.
            assert text not in exc.hashed_input
            assert exc.hashed_input == hash_input(text)
            self.last_blocked_raw = text

    @rule()
    def seal_chain(self) -> None:
        self.chain.seal()
        self.sealed = True

    @invariant()
    def state_is_bounded(self) -> None:
        if not hasattr(self, "chain"):
            return
        assert self.chain.state in {"open", "sealed"}

    @invariant()
    def audit_is_bounded(self) -> None:
        if not hasattr(self, "chain"):
            return
        # GUARD-INV-05 storage bound: ring buffer never grows past MAX_AUDIT_ENTRIES.
        assert len(self.chain.audit) <= MAX_AUDIT_ENTRIES

    @invariant()
    def blocked_inputs_never_in_audit_cleartext(self) -> None:
        if not hasattr(self, "chain"):
            return
        if self.last_blocked_raw is None:
            return
        # GUARD-INV-05: the raw blocked text MUST NOT appear in the stored input_hash.
        # (The `reason` string may legitimately cite the marker itself — that is
        # a well-known rule name, not the raw input.)
        for e in self.chain.audit:
            assert self.last_blocked_raw not in e.input_hash

    @invariant()
    def audit_seq_monotonic(self) -> None:
        if not hasattr(self, "chain"):
            return
        seqs = [e.seq for e in self.chain.audit]
        assert seqs == sorted(seqs)

    @invariant()
    def sealed_is_terminal(self) -> None:
        if not hasattr(self, "chain"):
            return
        # sealed chain → state stays sealed (no transition back to open).
        if self.sealed:
            assert self.chain.state == "sealed"


# Hypothesis hook — the runner picks this up as a test case.
TestChainMachine = ChainMachine.TestCase
