"""Auth-only SaaS — PasswordHasher + SessionStore + RateLimiter recipe.

Self-contained demo with constant-time login and single-use reset tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field


# --- PasswordHasher (mirror of core/venous/security/PasswordHasher) --------

# Well-formed dummy hash: a real scrypt output over a random password no one
# will guess. verify_password() against this hash runs a full scrypt (i.e.
# the expensive path) — which is the whole point: login-latency for an
# unknown email must equal login-latency for a wrong password.
_DUMMY_SALT = b"\x00" * 16
_DUMMY_DK = "1" * 64  # anything 64 hex chars; the compare_digest is constant-time
DUMMY_HASH = f"v1${_DUMMY_SALT.hex()}${_DUMMY_DK}"


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Constant-time-verifiable hash. Uses scrypt for demo (Argon2 in prod)."""
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"v1${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, dk_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, TypeError):
        return False


# --- SessionStore (refresh tokens, revocable) ------------------------------


@dataclass
class _Session:
    user_id: str
    session_id: str
    revoked: bool = False
    created_at: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self) -> None:
        self._by_token: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._by_token[token] = _Session(user_id=user_id, session_id=token)
        return token

    def revoke(self, token: str) -> None:
        with self._lock:
            s = self._by_token.get(token)
            if s is not None:
                s.revoked = True

    def resolve(self, token: str) -> str | None:
        with self._lock:
            s = self._by_token.get(token)
            if s is None or s.revoked:
                return None
            return s.user_id


# --- RateLimiter (sliding window per key) ----------------------------------


class RateLimiter:
    def __init__(self, *, burst: int, window_s: float) -> None:
        self.burst = burst
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, now: float) -> bool:
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.window_s
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.burst:
                return False
            q.append(now)
            return True


# --- Password reset (single-use TTL tokens) --------------------------------


@dataclass
class _ResetToken:
    user_id: str
    expires_at: float
    used: bool = False


class PasswordResetRegistry:
    def __init__(self, *, ttl_s: float = 900) -> None:
        self.ttl_s = ttl_s
        self._tokens: dict[str, _ResetToken] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: str, *, now: float) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = _ResetToken(
                user_id=user_id, expires_at=now + self.ttl_s,
            )
        return token

    def consume(self, token: str, *, now: float) -> str | None:
        with self._lock:
            t = self._tokens.get(token)
            if t is None or t.used or t.expires_at <= now:
                return None
            t.used = True
            return t.user_id


# --- Login flow --------------------------------------------------------------


@dataclass
class UserRecord:
    email: str
    password_hash: str


class LoginService:
    """Ties hasher + store + rate-limiter together with constant-time failure.

    Returns (status_code, refresh_token_or_none). The `login()` method
    always computes a hash verify (even for unknown users, against a dummy
    hash) so wall-clock latency does not leak account existence.
    """

    def __init__(
        self,
        users: dict[str, UserRecord],
        sessions: SessionStore,
        *,
        email_limiter: RateLimiter,
        ip_limiter: RateLimiter,
    ) -> None:
        self.users = users
        self.sessions = sessions
        self.email_limiter = email_limiter
        self.ip_limiter = ip_limiter

    def login(self, email: str, password: str, *, ip: str, now: float) -> tuple[int, str | None]:
        if not self.email_limiter.allow(f"login:{email}", now=now):
            return 429, None
        if not self.ip_limiter.allow(f"login:{ip}", now=now):
            return 429, None
        user = self.users.get(email)
        if user is None:
            verify_password(password, DUMMY_HASH)
            return 401, None
        if not verify_password(password, user.password_hash):
            return 401, None
        token = self.sessions.issue(user.email)
        return 200, token
