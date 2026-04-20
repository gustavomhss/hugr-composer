"""Chaos / game-day tests for TotpVerifier.

Simulates adversarial and anomalous inputs: clock skew, replay storms,
malformed codes, extreme secrets, and constructor misconfiguration.
"""

from __future__ import annotations

import pytest

from TotpVerifier import (
    DEFAULT_STEP_SECONDS,
    StandardTotpVerifier,
    TotpInvalidCodeError,
    TotpInvariantError,
    TotpReplayError,
    _hotp,  # type: ignore[attr-defined]
    generate_secret,
)


def test_chaos_far_future_clock_code_rejected() -> None:
    secret = generate_secret()
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    v = StandardTotpVerifier(now_fn=lambda: now)
    # Attacker pre-computes a code 10 steps in the future (300s drift) — must
    # be rejected because window is bounded to +/-1.
    future_code = _hotp(secret, step + 10, 6, "SHA1")
    with pytest.raises(TotpInvalidCodeError):
        v.verify(secret=secret, code=future_code, last_used_step=None)


def test_chaos_clock_rewind_replay_rejected() -> None:
    # Clock jumps backward (NTP correction) — the in-process replay cache
    # still remembers the used step and rejects the replay.
    secret = generate_secret()
    state = {"now": 1_700_000_000.0}
    step_then = int(state["now"] // DEFAULT_STEP_SECONDS)
    v = StandardTotpVerifier(now_fn=lambda: state["now"])
    code = _hotp(secret, step_then, 6, "SHA1")
    used = v.verify(secret=secret, code=code, last_used_step=None)
    assert used == step_then

    # Clock rewinds 60 seconds — same code, same verifier, must be rejected.
    state["now"] -= 60.0
    with pytest.raises((TotpReplayError, TotpInvalidCodeError)):
        v.verify(secret=secret, code=code, last_used_step=None)


def test_chaos_massive_replay_storm() -> None:
    secret = generate_secret()
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    v = StandardTotpVerifier(now_fn=lambda: now)
    code = _hotp(secret, step, 6, "SHA1")
    v.verify(secret=secret, code=code, last_used_step=None)
    rejections = 0
    for _ in range(10_000):
        try:
            v.verify(secret=secret, code=code, last_used_step=None)
        except TotpReplayError:
            rejections += 1
    assert rejections == 10_000


def test_chaos_malformed_codes_never_accepted() -> None:
    v = StandardTotpVerifier()
    secret = generate_secret()
    bad_inputs = [
        "",          # empty
        "1234",      # short
        "1234567",   # too long for 6-digit
        "abcdef",    # non-digit
        "12 456",    # space
        "12-456",    # hyphen
        "１２３４５６",  # full-width digits (non-ASCII)
    ]
    for code in bad_inputs:
        with pytest.raises(TotpInvariantError):
            v.verify(secret=secret, code=code, last_used_step=None)


def test_chaos_constructor_rejects_illegal_params() -> None:
    # digits out of range
    with pytest.raises(TotpInvariantError):
        StandardTotpVerifier(digits=10, allow_nonstandard_digits=True)
    # step_seconds zero
    with pytest.raises(TotpInvariantError):
        StandardTotpVerifier(step_seconds=0)
    # step_seconds too large
    with pytest.raises(TotpInvariantError):
        StandardTotpVerifier(step_seconds=600)
    # unknown algorithm
    with pytest.raises(TotpInvariantError):
        StandardTotpVerifier(algorithm="MD5")


def test_chaos_secret_types_that_should_fail() -> None:
    v = StandardTotpVerifier()
    # None, string, int — all rejected by the bytes type guard.
    for bad in (None, "not-bytes", 12345, object()):
        with pytest.raises(TotpInvariantError):
            v.verify(secret=bad, code="000000", last_used_step=None)  # type: ignore[arg-type]


def test_chaos_empty_verify_after_good_verify_is_safe() -> None:
    # Good path followed by pathological inputs MUST NOT corrupt prior good
    # state or cause later legit calls to misbehave.
    secret = generate_secret()
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    v = StandardTotpVerifier(now_fn=lambda: now)
    good = _hotp(secret, step, 6, "SHA1")
    v.verify(secret=secret, code=good, last_used_step=None)

    for junk in ("", "abcdef", "12"):
        with pytest.raises(TotpInvariantError):
            v.verify(secret=secret, code=junk, last_used_step=None)

    # Next step at a later clock still works.
    later = now + DEFAULT_STEP_SECONDS
    v2 = StandardTotpVerifier(now_fn=lambda: later)
    later_code = _hotp(secret, int(later // DEFAULT_STEP_SECONDS), 6, "SHA1")
    v2.verify(secret=secret, code=later_code, last_used_step=step)
