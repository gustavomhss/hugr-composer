"""Behavioral end-to-end scenarios for TotpVerifier — proves invariants at runtime."""

from __future__ import annotations

import pytest

from TotpVerifier import (
    DEFAULT_STEP_SECONDS,
    StandardTotpVerifier,
    TotpAdapterRegistry,
    TotpInvalidCodeError,
    TotpInvariantError,
    TotpReplayError,
    _hotp,  # type: ignore[attr-defined]
    generate_secret,
)


def _code(secret: bytes, now: float, digits: int = 6) -> str:
    return _hotp(secret, int(now // DEFAULT_STEP_SECONDS), digits, "SHA1")


def test_scenario_enrollment_then_first_verify_succeeds() -> None:
    # End-to-end: generate secret, build provisioning URI, user types the code.
    secret = generate_secret()
    v = StandardTotpVerifier()
    uri = v.provision_uri(account="alice@example.com", issuer="Acme Corp", secret=secret)
    assert uri.startswith("otpauth://totp/Acme%20Corp%3Aalice%40example.com?")

    now = 1_700_000_000.0
    v2 = StandardTotpVerifier(now_fn=lambda: now)
    code = _code(secret, now)
    step = v2.verify(secret=secret, code=code, last_used_step=None)
    assert step == int(now // DEFAULT_STEP_SECONDS)


def test_scenario_replay_rejected_across_calls() -> None:
    # Same code submitted twice with the caller persisting last_used_step
    # MUST be rejected on the second call.
    secret = generate_secret()
    now = 1_700_000_000.0
    v = StandardTotpVerifier(now_fn=lambda: now)
    code = _code(secret, now)
    used_step = v.verify(secret=secret, code=code, last_used_step=None)

    # Simulate the caller persisting used_step; they now retry the same code.
    v2 = StandardTotpVerifier(now_fn=lambda: now)  # fresh cache: caller record is authoritative
    with pytest.raises(TotpReplayError):
        v2.verify(secret=secret, code=code, last_used_step=used_step)


def test_scenario_skew_tolerates_clock_drift_but_no_further() -> None:
    secret = generate_secret()
    # User's watch is 29s ahead; their code is for step+1 but server is at step.
    now = 1_700_000_000.0
    v = StandardTotpVerifier(now_fn=lambda: now)
    future_code = _hotp(secret, int(now // DEFAULT_STEP_SECONDS) + 1, 6, "SHA1")
    step = v.verify(secret=secret, code=future_code, last_used_step=None)
    assert step == int(now // DEFAULT_STEP_SECONDS) + 1

    # Drift of two whole steps (60s) — rejected.
    v2 = StandardTotpVerifier(now_fn=lambda: now)
    far_future = _hotp(secret, int(now // DEFAULT_STEP_SECONDS) + 2, 6, "SHA1")
    with pytest.raises(TotpInvalidCodeError):
        v2.verify(secret=secret, code=far_future, last_used_step=None)


def test_scenario_weak_secret_rejected_at_enrollment_and_verify() -> None:
    # A service operator tries to ship a too-short secret — both enrollment
    # and verify reject it.
    weak = b"short"  # 5 bytes
    v = StandardTotpVerifier()
    with pytest.raises(TotpInvariantError):
        v.provision_uri(account="a", issuer="b", secret=weak)
    with pytest.raises(TotpInvariantError):
        v.verify(secret=weak, code="000000", last_used_step=None)


def test_scenario_adapter_registry_accepts_valid_rejects_invalid() -> None:
    reg = TotpAdapterRegistry()
    sha256_adapter = StandardTotpVerifier(algorithm="SHA256")
    reg.register("sha256-6d", sha256_adapter)
    assert "sha256-6d" in reg.names()

    # Not a TotpVerifier — no `verify` attribute.
    class NotAdapter:
        pass

    with pytest.raises(TotpInvariantError):
        reg.register("broken", NotAdapter())  # type: ignore[arg-type]


def test_scenario_wrong_issuer_account_shape_rejected() -> None:
    v = StandardTotpVerifier()
    secret = generate_secret()
    # Issuer with `:` would break the otpauth label.
    with pytest.raises(TotpInvariantError):
        v.provision_uri(account="alice", issuer="Ac:me", secret=secret)
    with pytest.raises(TotpInvariantError):
        v.provision_uri(account="", issuer="Acme", secret=secret)


def test_scenario_successful_verify_returns_step_for_persistence() -> None:
    # The returned int is exactly what the caller stores on the user record
    # per catalog consumption_example.
    secret = generate_secret()
    now = 1_700_000_000.0
    v = StandardTotpVerifier(now_fn=lambda: now)
    code = _code(secret, now)
    step = v.verify(secret=secret, code=code, last_used_step=None)
    # Caller persists: user.last_totp_step = step
    # Any future verify with last_used_step=step and the SAME code is a replay.
    v2 = StandardTotpVerifier(now_fn=lambda: now)
    with pytest.raises(TotpReplayError):
        v2.verify(secret=secret, code=code, last_used_step=step)
