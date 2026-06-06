"""Tests for the auth-only SaaS example."""
from __future__ import annotations

import time

import pytest

from app import (
    DUMMY_HASH,
    LoginService,
    PasswordResetRegistry,
    RateLimiter,
    SessionStore,
    UserRecord,
    hash_password,
    verify_password,
)


def test_hash_verify_roundtrip() -> None:
    stored = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", stored) is True
    assert verify_password("wrong-password", stored) is False
    # Plaintext recovery impossible — stored must not contain the password.
    assert "correct-horse-battery-staple" not in stored


def test_refresh_token_revoked_on_logout() -> None:
    store = SessionStore()
    token = store.issue("alice@example.com")
    assert store.resolve(token) == "alice@example.com"
    store.revoke(token)
    assert store.resolve(token) is None  # 401 in the real API


def test_single_use_password_reset_token() -> None:
    reg = PasswordResetRegistry(ttl_s=900)
    token = reg.issue("bob@example.com", now=1000.0)
    assert reg.consume(token, now=1100.0) == "bob@example.com"
    # Second use returns None (API returns 400).
    assert reg.consume(token, now=1200.0) is None


def test_expired_password_reset_token_rejected() -> None:
    reg = PasswordResetRegistry(ttl_s=900)
    token = reg.issue("bob@example.com", now=1000.0)
    assert reg.consume(token, now=2000.0) is None


def test_login_rate_limit_429_after_six_wrong_in_60s() -> None:
    users = {"alice@example.com": UserRecord(
        email="alice@example.com", password_hash=hash_password("right"),
    )}
    svc = LoginService(
        users, SessionStore(),
        email_limiter=RateLimiter(burst=5, window_s=60),
        ip_limiter=RateLimiter(burst=100, window_s=60),
    )
    # 5 wrong allowed (return 401), 6th trips email limiter.
    for i in range(5):
        code, _ = svc.login("alice@example.com", "WRONG", ip="1.2.3.4", now=1000.0 + i)
        assert code == 401
    code, _ = svc.login("alice@example.com", "WRONG", ip="1.2.3.4", now=1005.0)
    assert code == 429


def test_login_returns_401_unknown_email_without_time_leak() -> None:
    users = {"alice@example.com": UserRecord(
        email="alice@example.com", password_hash=hash_password("right"),
    )}
    svc = LoginService(
        users, SessionStore(),
        email_limiter=RateLimiter(burst=100, window_s=60),
        ip_limiter=RateLimiter(burst=100, window_s=60),
    )
    t0 = time.perf_counter()
    code_unknown, _ = svc.login("nobody@example.com", "whatever", ip="1.1.1.1", now=1000.0)
    t_unknown = time.perf_counter() - t0

    t0 = time.perf_counter()
    code_wrong, _ = svc.login("alice@example.com", "WRONG", ip="1.1.1.2", now=1001.0)
    t_wrong = time.perf_counter() - t0

    assert code_unknown == 401 and code_wrong == 401
    # Both paths ran scrypt — latencies must be same order of magnitude.
    # Accept 3x swing to tolerate CI jitter; without dummy-verify this
    # would be 100x+.
    assert 0.33 < t_unknown / t_wrong < 3.0, (t_unknown, t_wrong)


def test_login_success_returns_refresh_token() -> None:
    users = {"alice@example.com": UserRecord(
        email="alice@example.com", password_hash=hash_password("right"),
    )}
    svc = LoginService(
        users, SessionStore(),
        email_limiter=RateLimiter(burst=100, window_s=60),
        ip_limiter=RateLimiter(burst=100, window_s=60),
    )
    code, token = svc.login("alice@example.com", "right", ip="1.1.1.1", now=1000.0)
    assert code == 200
    assert token and len(token) >= 32


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
