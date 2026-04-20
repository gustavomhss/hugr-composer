"""Metamorphic + differential tests for TotpVerifier.

Algebraic properties:
- Two verifiers instantiated with the same secret + same clock produce the
  same verification outcome for the same code (determinism).
- Codes produced at step `s` are accepted at clock in [s-1, s+1] and nowhere
  else (skew invariance).
- The replay relationship is total-order: if step a < b, both valid at their
  own time, then verifying b locks out any re-verification of a as a fresh
  step on a caller record that persisted last_used_step=b.
- Differential: our HOTP against an independent reference computation for
  RFC 6238 test vectors.
"""

from __future__ import annotations

import pytest

from TotpVerifier import (
    DEFAULT_STEP_SECONDS,
    StandardTotpVerifier,
    TotpInvalidCodeError,
    TotpReplayError,
    _hotp,  # type: ignore[attr-defined]
)


_SECRET_20 = b"12345678901234567890"  # RFC 6238 SHA-1 test vector


def test_metamorphic_determinism_same_secret_same_clock() -> None:
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    a = StandardTotpVerifier(now_fn=lambda: now)
    b = StandardTotpVerifier(now_fn=lambda: now)
    code = _hotp(_SECRET_20, step, 6, "SHA1")
    sa = a.verify(secret=_SECRET_20, code=code, last_used_step=None)
    sb = b.verify(secret=_SECRET_20, code=code, last_used_step=None)
    assert sa == sb == step


def test_metamorphic_skew_invariance_acceptance_window_is_exactly_three() -> None:
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    accepted = 0
    for offset in range(-10, 11):
        v = StandardTotpVerifier(now_fn=lambda: now)
        code = _hotp(_SECRET_20, step + offset, 6, "SHA1")
        try:
            v.verify(secret=_SECRET_20, code=code, last_used_step=None)
            accepted += 1
        except TotpInvalidCodeError:
            pass
    assert accepted == 3


def test_metamorphic_replay_lockout_is_monotone() -> None:
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    # Accept step-1 first, then step → last_used_step=step → replay of step-1
    # must be rejected even though it's still inside the +/-1 window at clock.
    v1 = StandardTotpVerifier(now_fn=lambda: now)
    prev_code = _hotp(_SECRET_20, step - 1, 6, "SHA1")
    curr_code = _hotp(_SECRET_20, step, 6, "SHA1")
    used1 = v1.verify(secret=_SECRET_20, code=prev_code, last_used_step=None)
    used2 = v1.verify(secret=_SECRET_20, code=curr_code, last_used_step=used1)
    assert used2 > used1

    # Now retry prev_code with persisted last_used_step=used2 — rejected.
    v2 = StandardTotpVerifier(now_fn=lambda: now)
    with pytest.raises(TotpReplayError):
        v2.verify(secret=_SECRET_20, code=prev_code, last_used_step=used2)


def test_differential_rfc6238_sha1_test_vector() -> None:
    # RFC 6238 Appendix B test vector (secret = ASCII 1..20, SHA-1).
    # At Unix time T=59 → step=1 (30s window) → expected code 94287082.
    # Our primitive truncates to 6 digits → last 6 of the 8-digit value.
    now = 59.0
    step = int(now // DEFAULT_STEP_SECONDS)
    assert step == 1
    code8 = _hotp(_SECRET_20, step, 8, "SHA1")
    assert code8 == "94287082"
    # Six-digit form: we expect 287082 (truncation per RFC).
    code6 = _hotp(_SECRET_20, step, 6, "SHA1")
    assert code6 == "287082"


def test_differential_digits_agree_on_last_n() -> None:
    # 6-digit code must equal the last 6 characters of the 8-digit code only
    # when the leading digits happen to zero — this is NOT a general identity;
    # rather, both are `(binary % 10**n)` so six-digit = eight-digit mod 10^6.
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    code6 = _hotp(_SECRET_20, step, 6, "SHA1")
    code8 = _hotp(_SECRET_20, step, 8, "SHA1")
    assert int(code8) % 10**6 == int(code6)
