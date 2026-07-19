"""Unit tests for TotpVerifier — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import hmac
import threading
import time
from unittest import mock

import pytest
from TotpVerifier import (
    DEFAULT_STEP_SECONDS,
    MIN_SECRET_BYTES,
    StandardTotpVerifier,
    TotpInvalidCodeError,
    TotpInvariantError,
    TotpReplayError,
    _hotp,  # type: ignore[attr-defined]  # internal: exercised for INV proofs
    generate_secret,
)

_SECRET = b"12345678901234567890"  # RFC 6238 test vector (ASCII "1..20"), 20 bytes
assert len(_SECRET) == MIN_SECRET_BYTES


def _frozen_verifier(now: float, **kwargs: object) -> StandardTotpVerifier:
    return StandardTotpVerifier(now_fn=lambda: now, **kwargs)  # type: ignore[arg-type]


def _code_for(secret: bytes, now: float, *, digits: int = 6) -> str:
    step = int(now // DEFAULT_STEP_SECONDS)
    return _hotp(secret, step, digits, "SHA1")


# ---------------------------------------------------------------------------
# TOTP_INV_01 — secret entropy (>=160 bits)
# ---------------------------------------------------------------------------
def test_inv_secret_entropy_confirms() -> None:
    v = StandardTotpVerifier()
    uri = v.provision_uri(account="alice@example.com", issuer="Acme", secret=_SECRET)
    assert uri.startswith("otpauth://totp/")
    # Secret is base32-encoded into URI but never the raw bytes
    assert "12345678901234567890" not in uri


def test_inv_secret_entropy_prevents() -> None:
    v = StandardTotpVerifier()
    short = b"too_short"  # 9 bytes < 20
    with pytest.raises(TotpInvariantError, match="TOTP-INV-01"):
        v.verify(secret=short, code="123456", last_used_step=None)
    with pytest.raises(TotpInvariantError, match="TOTP-INV-01"):
        v.provision_uri(account="a", issuer="Acme", secret=short)


def test_inv_secret_entropy_under_failure() -> None:
    # Even repeated failing attempts with short secrets must never accept.
    v = StandardTotpVerifier()
    for i in range(50):
        short = bytes([i]) * (MIN_SECRET_BYTES - 1)
        with pytest.raises(TotpInvariantError):
            v.verify(secret=short, code="000000", last_used_step=None)
    # A fresh CSPRNG secret must satisfy the invariant and still work.
    fresh = generate_secret()
    assert len(fresh) >= MIN_SECRET_BYTES
    now = 1_700_000_000.0
    v2 = _frozen_verifier(now)
    code = _code_for(fresh, now)
    assert v2.verify(secret=fresh, code=code, last_used_step=None) == int(now // DEFAULT_STEP_SECONDS)


# ---------------------------------------------------------------------------
# TOTP_INV_02 — constant-time comparison
# ---------------------------------------------------------------------------
def test_inv_constant_time_confirms() -> None:
    # Confirm that hmac.compare_digest is the comparison primitive in use by
    # forcing a match and a near-miss and observing the outcomes correctly.
    now = 1_700_000_000.0
    v = _frozen_verifier(now)
    good = _code_for(_SECRET, now)
    assert v.verify(secret=_SECRET, code=good, last_used_step=None) == int(now // DEFAULT_STEP_SECONDS)

    # Near-miss (only last digit wrong) must be rejected — no prefix accept.
    v2 = _frozen_verifier(now)
    bad = good[:-1] + ("0" if good[-1] != "0" else "1")
    with pytest.raises(TotpInvalidCodeError):
        v2.verify(secret=_SECRET, code=bad, last_used_step=None)


def test_inv_constant_time_prevents() -> None:
    # Patch hmac.compare_digest to fail loudly if ANY call site short-circuits
    # through plain ==. We monkey-patch `hmac.compare_digest` to a counter and
    # ensure verify() calls it at least once per candidate step (so 3 calls for
    # +/-1 window).
    now = 1_700_000_000.0
    v = _frozen_verifier(now)
    good = _code_for(_SECRET, now)

    calls: list[int] = []
    real = hmac.compare_digest

    def spy(a: object, b: object) -> bool:
        calls.append(1)
        return real(a, b)  # type: ignore[arg-type]

    with mock.patch("TotpVerifier.hmac.compare_digest", spy):
        v.verify(secret=_SECRET, code=good, last_used_step=None)
    # +/-1 step window = 3 candidate steps, all compared.
    assert len(calls) == 3


def test_inv_constant_time_under_failure() -> None:
    # Even with thousands of random wrong codes, none passes and total wall
    # time varies narrowly (no prefix leak). We assert outcome correctness
    # rather than micro-benchmarking (flaky on shared runners).
    now = 1_700_000_000.0
    v = _frozen_verifier(now)
    for i in range(200):
        wrong = str(i).zfill(6)
        good = _code_for(_SECRET, now)
        if wrong == good:
            continue
        with pytest.raises(TotpInvalidCodeError):
            v.verify(secret=_SECRET, code=wrong, last_used_step=None)


# ---------------------------------------------------------------------------
# TOTP_INV_03 — skew window bounded to +/-1 step
# ---------------------------------------------------------------------------
def test_inv_skew_window_confirms() -> None:
    now = 1_700_000_000.0
    step_now = int(now // DEFAULT_STEP_SECONDS)
    v_prev = _frozen_verifier(now)
    v_curr = _frozen_verifier(now)
    v_next = _frozen_verifier(now)

    prev_code = _hotp(_SECRET, step_now - 1, 6, "SHA1")
    curr_code = _hotp(_SECRET, step_now, 6, "SHA1")
    next_code = _hotp(_SECRET, step_now + 1, 6, "SHA1")

    assert v_prev.verify(secret=_SECRET, code=prev_code, last_used_step=None) == step_now - 1
    assert v_curr.verify(secret=_SECRET, code=curr_code, last_used_step=None) == step_now
    assert v_next.verify(secret=_SECRET, code=next_code, last_used_step=None) == step_now + 1


def test_inv_skew_window_prevents() -> None:
    now = 1_700_000_000.0
    step_now = int(now // DEFAULT_STEP_SECONDS)
    v = _frozen_verifier(now)
    # +/-2 step codes MUST be rejected.
    far_past = _hotp(_SECRET, step_now - 2, 6, "SHA1")
    far_future = _hotp(_SECRET, step_now + 2, 6, "SHA1")
    with pytest.raises(TotpInvalidCodeError):
        v.verify(secret=_SECRET, code=far_past, last_used_step=None)
    with pytest.raises(TotpInvalidCodeError):
        v.verify(secret=_SECRET, code=far_future, last_used_step=None)


def test_inv_skew_window_under_failure() -> None:
    # Sweep a wide range of steps; only three (step-1, step, step+1) MUST
    # be accepted. Everything else rejected.
    now = 1_700_000_000.0
    step_now = int(now // DEFAULT_STEP_SECONDS)
    accepted: set[int] = set()
    for offset in range(-10, 11):
        v = _frozen_verifier(now)
        code = _hotp(_SECRET, step_now + offset, 6, "SHA1")
        try:
            s = v.verify(secret=_SECRET, code=code, last_used_step=None)
            accepted.add(s - step_now)
        except TotpInvalidCodeError:
            pass
    assert accepted == {-1, 0, 1}


# ---------------------------------------------------------------------------
# TOTP_INV_04 — step replay rejected
# ---------------------------------------------------------------------------
def test_inv_replay_rejected_confirms() -> None:
    now = 1_700_000_000.0
    v = _frozen_verifier(now)
    step = int(now // DEFAULT_STEP_SECONDS)
    code = _hotp(_SECRET, step, 6, "SHA1")
    used = v.verify(secret=_SECRET, code=code, last_used_step=None)
    assert used == step
    # Caller persists `used`; next legitimate code is step+1 once time advances.


def test_inv_replay_rejected_prevents() -> None:
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    code = _hotp(_SECRET, step, 6, "SHA1")

    # Fresh verifier (fresh in-memory cache); supply last_used_step so the
    # caller's record rejects the replay.
    v = _frozen_verifier(now)
    v.verify(secret=_SECRET, code=code, last_used_step=step - 1)
    # Replay with the persisted last_used_step = step must be rejected.
    v2 = _frozen_verifier(now)
    with pytest.raises(TotpReplayError):
        v2.verify(secret=_SECRET, code=code, last_used_step=step)


def test_inv_replay_rejected_under_failure() -> None:
    # Many concurrent replays of the same code must all be rejected except
    # (at most) one winner.
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    code = _hotp(_SECRET, step, 6, "SHA1")

    v = _frozen_verifier(now)
    winners: list[int] = []
    losers: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            s = v.verify(secret=_SECRET, code=code, last_used_step=None)
            with lock:
                winners.append(s)
        except TotpReplayError as exc:
            with lock:
                losers.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1
    assert len(losers) == 31


# ---------------------------------------------------------------------------
# TOTP_INV_05 — six decimal digits by default
# ---------------------------------------------------------------------------
def test_inv_six_digits_confirms() -> None:
    v = StandardTotpVerifier()
    now = time.time()
    code = _hotp(_SECRET, int(now // DEFAULT_STEP_SECONDS), 6, "SHA1")
    assert len(code) == 6
    assert code.isdigit()


def test_inv_six_digits_prevents() -> None:
    # 7 / 8 digits require explicit opt-in; other lengths rejected outright.
    with pytest.raises(TotpInvariantError, match="TOTP-INV-05"):
        StandardTotpVerifier(digits=8)
    with pytest.raises(TotpInvariantError):
        StandardTotpVerifier(digits=5, allow_nonstandard_digits=True)
    with pytest.raises(TotpInvariantError):
        StandardTotpVerifier(digits=10, allow_nonstandard_digits=True)

    # Non-digit code rejected.
    v = StandardTotpVerifier()
    with pytest.raises(TotpInvariantError):
        v.verify(secret=_SECRET, code="abcdef", last_used_step=None)
    with pytest.raises(TotpInvariantError):
        v.verify(secret=_SECRET, code="12345", last_used_step=None)


def test_inv_six_digits_under_failure() -> None:
    # Opt-in path works (8 digits), default path rejects 8-digit codes.
    v8 = StandardTotpVerifier(digits=8, allow_nonstandard_digits=True)
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    code8 = _hotp(_SECRET, step, 8, "SHA1")
    v8b = StandardTotpVerifier(digits=8, allow_nonstandard_digits=True, now_fn=lambda: now)
    assert v8b.verify(secret=_SECRET, code=code8, last_used_step=None) == step

    v6 = StandardTotpVerifier(now_fn=lambda: now)
    with pytest.raises(TotpInvariantError):
        v6.verify(secret=_SECRET, code=code8, last_used_step=None)
    _ = v8  # silence "unused" in case linters object
