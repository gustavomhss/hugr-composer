"""Hypothesis state-machine exploration of TotpVerifier lifecycle.

Models the caller holding a `last_used_step` record and the verifier's
in-memory replay cache as a joint state machine. Every reachable state
upholds TOTP-INV-04 (no step accepted twice) and the +/-1 skew bound.
"""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from TotpVerifier import (
    DEFAULT_STEP_SECONDS,
    StandardTotpVerifier,
    TotpInvalidCodeError,
    TotpReplayError,
    _hotp,  # type: ignore[attr-defined]
    generate_secret,
)


class TotpMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.secret = generate_secret()
        self.now = 1_700_000_000.0
        self.verifier = StandardTotpVerifier(now_fn=lambda: self.now)
        self.last_used_step: int | None = None
        self.accepted_steps: set[int] = set()

    @rule(offset=st.integers(min_value=-5, max_value=5))
    def attempt_verify(self, offset: int) -> None:
        current_step = int(self.now // DEFAULT_STEP_SECONDS)
        target_step = current_step + offset
        code = _hotp(self.secret, target_step, 6, "SHA1")
        try:
            s = self.verifier.verify(
                secret=self.secret, code=code, last_used_step=self.last_used_step
            )
        except TotpInvalidCodeError:
            # Out-of-window: must be |offset| > 1.
            assert abs(offset) > 1, f"in-window code rejected: offset={offset}"
            return
        except TotpReplayError:
            # Must be a replay of an already-accepted step (either in
            # accepted_steps or <= last_used_step).
            assert target_step in self.accepted_steps or (
                self.last_used_step is not None and target_step <= self.last_used_step
            )
            return
        # Accepted: enforce invariants.
        assert abs(offset) <= 1, f"out-of-window step accepted: offset={offset}"
        assert s == target_step
        assert s not in self.accepted_steps, "step accepted twice (INV-04 violation)"
        self.accepted_steps.add(s)
        self.last_used_step = s

    @rule()
    def tick(self) -> None:
        # Time advances by one step — simulate clock progress.
        self.now += DEFAULT_STEP_SECONDS

    @invariant()
    def last_used_monotone(self) -> None:
        if not hasattr(self, "accepted_steps"):
            return
        if not self.accepted_steps:
            return
        if self.last_used_step is None:
            return
        assert self.last_used_step == max(self.accepted_steps)

    @invariant()
    def no_duplicates(self) -> None:
        if not hasattr(self, "accepted_steps"):
            return
        # By construction `accepted_steps` is a set — this just asserts
        # the harness has not accidentally tracked something wrong.
        assert len(self.accepted_steps) == len(set(self.accepted_steps))


# Pytest entry point
TestTotpMachine = TotpMachine.TestCase
