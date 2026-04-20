"""SessionStore primitive — server-side session lifecycle with fixation resistance.

Implements the catalog Protocol for `auth.SessionStore` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- SESSION-INV-01: Session ids MUST carry >=128 bits of entropy from a CSPRNG
  and MUST NEVER encode user-controlled input.
- SESSION-INV-02: On privilege elevation the session id MUST be rotated; the
  prior id CANNOT be reused (fixation resistance).
- SESSION-INV-03: Sessions MUST expire at min(idle_expires_at,
  absolute_expires_at); server-side revocation MUST win over any client-held
  cookie.
- SESSION-INV-04: Session cookies MUST be Secure + HttpOnly + SameSite in
  {Lax, Strict}; Domain SHALL NEVER be broader than the application host.
- SESSION-INV-05: revoke_all_for_subject() MUST terminate every live session
  for a subject atomically; after the call load() MUST return None for each.
- SESSION-INV-06: load() MUST NEVER extend a session past absolute_expires_at
  — the absolute clock is a hard ceiling that sliding-window renew cannot
  breach.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time as _time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Tunables / constants (SESSION-INV-01, SESSION-INV-03, SESSION-INV-04)
# ---------------------------------------------------------------------------

# 32 bytes of CSPRNG output = 256 bits; URL-safe base64 yields a 43-char id.
# The absolute floor required by SESSION-INV-01 is 128 bits.
_SID_ENTROPY_BYTES: Final[int] = 32
_SID_MIN_ENTROPY_BITS: Final[int] = 128
_SID_MIN_LENGTH: Final[int] = 22  # base64url(16 bytes) is 22 chars, the floor.

# Default sliding-window (idle) and hard-cap (absolute) lifetimes, in seconds.
# OWASP ASVS V3.3.1 guidance: idle <= 30 min for sensitive apps; absolute is
# commonly 12h (sensitive) to 24h (low-risk). Defaults target the sensitive tier.
DEFAULT_IDLE_TIMEOUT_S: Final[int] = 30 * 60
DEFAULT_ABSOLUTE_TIMEOUT_S: Final[int] = 12 * 60 * 60

# Cookie attribute whitelists (SESSION-INV-04).
_ALLOWED_SAMESITE: Final[frozenset[str]] = frozenset({"Lax", "Strict"})


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class SessionInvariantError(RuntimeError):
    """Raised when a SessionStore invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Session:
    """Immutable server-side session record.

    Fields mirror the catalog api_signature verbatim. Construction is
    validated against the session-store invariants; the record is frozen so
    no middleware or consumer CAN mutate a field after issue.
    """

    id: str
    subject: str
    created_at: int
    idle_expires_at: int
    absolute_expires_at: int

    def __post_init__(self) -> None:
        # SESSION-INV-01: id must be a high-entropy string, not empty, no controls.
        if not isinstance(self.id, str) or len(self.id) < _SID_MIN_LENGTH:
            raise SessionInvariantError(
                "SESSION-INV-01: session id MUST be a high-entropy string "
                f"(>= {_SID_MIN_LENGTH} chars base64url); got "
                f"len={len(self.id) if isinstance(self.id, str) else 'n/a'}."
            )
        if any(ord(c) < 0x21 or ord(c) > 0x7E for c in self.id):
            raise SessionInvariantError(
                "SESSION-INV-01: session id MUST contain only URL-safe "
                "printable ASCII; non-printable or control codepoint rejected."
            )
        if not isinstance(self.subject, str) or self.subject == "":
            raise SessionInvariantError(
                "SESSION-INV-01: subject MUST be a non-empty string."
            )
        if not (
            isinstance(self.created_at, int)
            and isinstance(self.idle_expires_at, int)
            and isinstance(self.absolute_expires_at, int)
        ):
            raise SessionInvariantError(
                "SESSION-INV-03: all timestamp fields MUST be int (unix seconds)."
            )
        # SESSION-INV-03 / SESSION-INV-06: ordering constraints.
        if self.idle_expires_at < self.created_at:
            raise SessionInvariantError(
                "SESSION-INV-03: idle_expires_at MUST NOT be earlier than created_at."
            )
        if self.absolute_expires_at < self.created_at:
            raise SessionInvariantError(
                "SESSION-INV-06: absolute_expires_at MUST NOT be earlier than created_at."
            )
        if self.idle_expires_at > self.absolute_expires_at:
            raise SessionInvariantError(
                "SESSION-INV-06: idle_expires_at MUST NEVER exceed "
                "absolute_expires_at — the absolute clock is a hard ceiling."
            )

    def effective_expires_at(self) -> int:
        """Return min(idle, absolute) — the effective expiry per SESSION-INV-03."""
        return min(self.idle_expires_at, self.absolute_expires_at)

    def is_expired_at(self, now: int) -> bool:
        """True iff now >= effective expiry (half-open interval [created, exp))."""
        return now >= self.effective_expires_at()


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class SessionStore(Protocol):
    def create(self, subject: str) -> Session: ...
    def load(self, session_id: str) -> Session | None: ...
    def rotate(self, session_id: str) -> Session: ...
    def revoke(self, session_id: str) -> None: ...
    def revoke_all_for_subject(self, subject: str) -> int: ...


# ---------------------------------------------------------------------------
# Cookie configuration (SESSION-INV-04)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CookieConfig:
    """Declarative, validated cookie attributes.

    The store does NOT set cookies itself — it validates the config that the
    web layer will use. This keeps the primitive independent of any web
    framework while still enforcing SESSION-INV-04 at bind time.
    """

    name: str = "sid"
    secure: bool = True
    http_only: bool = True
    same_site: str = "Lax"
    domain: str | None = None
    path: str = "/"

    def __post_init__(self) -> None:
        if not self.secure:
            raise SessionInvariantError(
                "SESSION-INV-04: session cookie MUST be Secure."
            )
        if not self.http_only:
            raise SessionInvariantError(
                "SESSION-INV-04: session cookie MUST be HttpOnly."
            )
        if self.same_site not in _ALLOWED_SAMESITE:
            raise SessionInvariantError(
                "SESSION-INV-04: SameSite MUST be one of "
                f"{sorted(_ALLOWED_SAMESITE)}; got {self.same_site!r}."
            )
        if self.domain is not None:
            if not isinstance(self.domain, str) or self.domain == "":
                raise SessionInvariantError(
                    "SESSION-INV-04: Domain MUST be None or a non-empty host string."
                )
            if self.domain.startswith("."):
                raise SessionInvariantError(
                    "SESSION-INV-04: Domain MUST NOT start with '.' (broader "
                    f"than the application host): {self.domain!r}."
                )


def validate_cookie_host(config: CookieConfig, application_host: str) -> None:
    """SESSION-INV-04: Domain SHALL NEVER be broader than the app host.

    If `config.domain` is set, it MUST equal `application_host`; anything
    else (a parent domain, a wildcard, a different host) is rejected. `None`
    is the preferred production value (host-only cookie).
    """
    if config.domain is None:
        return
    if config.domain != application_host:
        raise SessionInvariantError(
            "SESSION-INV-04: cookie Domain MUST NOT be broader than the "
            f"application host; got Domain={config.domain!r}, "
            f"host={application_host!r}."
        )


# ---------------------------------------------------------------------------
# Session id minting (SESSION-INV-01)
# ---------------------------------------------------------------------------
def mint_session_id(entropy_bytes: int = _SID_ENTROPY_BYTES) -> str:
    """Return a URL-safe base64 session id with at least 128 bits of CSPRNG entropy.

    The caller CANNOT inject user data — the id is drawn entirely from
    `secrets.token_urlsafe`, which wraps os.urandom (a CSPRNG).
    """
    if entropy_bytes * 8 < _SID_MIN_ENTROPY_BITS:
        raise SessionInvariantError(
            "SESSION-INV-01: session id MUST carry >=128 bits of entropy; "
            f"got {entropy_bytes * 8} bits."
        )
    return secrets.token_urlsafe(entropy_bytes)


# ---------------------------------------------------------------------------
# Reference in-memory implementation
# ---------------------------------------------------------------------------
@dataclass
class _Record:
    """Internal mutable record. Never exposed to callers."""

    session: Session
    revoked: bool = False


class InMemorySessionStore:
    """Reference SessionStore that keeps records in a threadsafe dict.

    Production adapters (redis / postgres) SHOULD mirror this state machine
    and re-use the `Session` value object unchanged. The `clock` and
    `id_factory` hooks exist only so tests can inject a deterministic clock
    and id generator; production callers leave both at the defaults.
    """

    def __init__(
        self,
        *,
        idle_timeout_s: int = DEFAULT_IDLE_TIMEOUT_S,
        absolute_timeout_s: int = DEFAULT_ABSOLUTE_TIMEOUT_S,
        clock: Callable[[], int] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if idle_timeout_s <= 0 or absolute_timeout_s <= 0:
            raise SessionInvariantError(
                "SESSION-INV-03: idle and absolute timeouts MUST be positive."
            )
        if idle_timeout_s > absolute_timeout_s:
            raise SessionInvariantError(
                "SESSION-INV-06: idle_timeout MUST NOT exceed absolute_timeout "
                "— the absolute clock is a hard ceiling."
            )
        self._idle = idle_timeout_s
        self._abs = absolute_timeout_s
        # time.time() returns a float; cast to int so all timestamps are int.
        self._clock: Callable[[], int] = clock or (lambda: int(_time.time()))
        self._id_factory: Callable[[], str] = id_factory or mint_session_id
        self._by_id: dict[str, _Record] = {}
        self._by_subject: dict[str, set[str]] = {}
        self._revoked_ids: set[str] = set()
        self._lock = threading.RLock()

    # ----- mint helper ------------------------------------------------------
    def _mint_session(self, subject: str) -> Session:
        # SESSION-INV-01: subject MUST be a non-empty string; fail fast before mint.
        if not isinstance(subject, str) or subject == "":
            raise SessionInvariantError(
                "SESSION-INV-01: subject MUST be a non-empty string."
            )
        now = self._clock()
        return Session(
            id=self._id_factory(),
            subject=subject,
            created_at=now,
            idle_expires_at=now + self._idle,
            absolute_expires_at=now + self._abs,
        )

    # ----- Protocol methods -------------------------------------------------
    def create(self, subject: str) -> Session:
        session = self._mint_session(subject)
        with self._lock:
            if session.id in self._by_id or session.id in self._revoked_ids:
                # SESSION-INV-01: a CSPRNG collision would indicate catastrophic
                # RNG failure; refuse to continue rather than overwrite silently.
                raise SessionInvariantError(
                    "SESSION-INV-01: CSPRNG produced a duplicate session id; "
                    "this indicates a broken RNG — refusing to continue."
                )
            self._by_id[session.id] = _Record(session=session)
            self._by_subject.setdefault(subject, set()).add(session.id)
        return session

    def load(self, session_id: str) -> Session | None:
        if not isinstance(session_id, str) or session_id == "":
            return None
        now = self._clock()
        with self._lock:
            rec = self._by_id.get(session_id)
            if rec is None:
                return None
            # SESSION-INV-03: revocation wins over any client-held cookie.
            if rec.revoked:
                return None
            session = rec.session
            # SESSION-INV-03 / SESSION-INV-06: expire at min(idle, absolute).
            if session.is_expired_at(now):
                # Drop expired record so subsequent loads stay O(1) and the
                # caller sees a clean miss. Revoked-id set is not populated for
                # natural expiry so a later token with an identical id (which
                # is astronomically unlikely) is not treated as a replay.
                self._drop_record_locked(session)
                return None
            # Sliding-window renew: extend idle but NEVER past absolute
            # (SESSION-INV-06 — hard ceiling).
            new_idle = min(now + self._idle, session.absolute_expires_at)
            if new_idle != session.idle_expires_at:
                renewed = Session(
                    id=session.id,
                    subject=session.subject,
                    created_at=session.created_at,
                    idle_expires_at=new_idle,
                    absolute_expires_at=session.absolute_expires_at,
                )
                rec.session = renewed
                return renewed
            return session

    def rotate(self, session_id: str) -> Session:
        # SESSION-INV-02: elevate -> mint new id, burn the old, preserve subject
        # and absolute ceiling (the hard cap does NOT reset on rotate).
        with self._lock:
            rec = self._by_id.get(session_id)
            if rec is None or rec.revoked:
                raise SessionInvariantError(
                    "SESSION-INV-02: rotate() MUST target a live session; "
                    "the caller passed an unknown or revoked id."
                )
            now = self._clock()
            old = rec.session
            if old.is_expired_at(now):
                # Expired sessions cannot be elevated; force re-authentication.
                self._drop_record_locked(old)
                raise SessionInvariantError(
                    "SESSION-INV-02: rotate() MUST NOT resurrect an expired "
                    "session — require fresh authentication instead."
                )
            new_id = self._id_factory()
            if new_id == session_id or new_id in self._by_id or new_id in self._revoked_ids:
                # Paranoid: reject any chance of id reuse even against a broken RNG.
                raise SessionInvariantError(
                    "SESSION-INV-02: rotation MUST produce a fresh id; "
                    "prior id CANNOT be reused."
                )
            rotated = Session(
                id=new_id,
                subject=old.subject,
                created_at=old.created_at,
                idle_expires_at=min(now + self._idle, old.absolute_expires_at),
                absolute_expires_at=old.absolute_expires_at,
            )
            # Retire the old id: mark revoked AND move to tombstone set so a
            # replay of the old cookie CANNOT be accepted (SESSION-INV-02).
            rec.revoked = True
            self._revoked_ids.add(old.id)
            subj_ids = self._by_subject.get(old.subject)
            if subj_ids is not None:
                subj_ids.discard(old.id)
            # Install the fresh record.
            self._by_id.pop(old.id, None)
            self._by_id[new_id] = _Record(session=rotated)
            self._by_subject.setdefault(old.subject, set()).add(new_id)
            return rotated

    def revoke(self, session_id: str) -> None:
        if not isinstance(session_id, str) or session_id == "":
            return
        with self._lock:
            rec = self._by_id.get(session_id)
            if rec is None:
                # Revoking an unknown id is idempotent; we still tombstone it
                # so a later replay of that id CANNOT be accepted.
                self._revoked_ids.add(session_id)
                return
            rec.revoked = True
            self._revoked_ids.add(session_id)
            subj_ids = self._by_subject.get(rec.session.subject)
            if subj_ids is not None:
                subj_ids.discard(session_id)
            self._by_id.pop(session_id, None)

    def revoke_all_for_subject(self, subject: str) -> int:
        if not isinstance(subject, str) or subject == "":
            return 0
        with self._lock:
            ids = list(self._by_subject.get(subject, ()))
            count = 0
            for sid in ids:
                rec = self._by_id.pop(sid, None)
                self._revoked_ids.add(sid)
                if rec is not None:
                    rec.revoked = True
                    count += 1
            self._by_subject.pop(subject, None)
            return count

    # ----- introspection helpers (tests only; NOT part of Protocol) --------
    def is_revoked(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._revoked_ids

    def live_session_ids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._by_id.keys())

    # ----- internals --------------------------------------------------------
    def _drop_record_locked(self, session: Session) -> None:
        # MUST be called with self._lock held.
        self._by_id.pop(session.id, None)
        subj_ids = self._by_subject.get(session.subject)
        if subj_ids is not None:
            subj_ids.discard(session.id)
            if not subj_ids:
                self._by_subject.pop(session.subject, None)


# ---------------------------------------------------------------------------
# Constant-time id comparison helper
# ---------------------------------------------------------------------------
def sids_equal(a: str, b: str) -> bool:
    """Constant-time session id equality — avoids timing-oracle leaks (SESSION-INV-01)."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a, b)


# ---------------------------------------------------------------------------
# Registration guard: adapters lacking revoke_all_for_subject are rejected.
# ---------------------------------------------------------------------------
def register_adapter(
    adapter: object,
    *,
    capabilities: Mapping[str, bool],
) -> None:
    """SESSION-INV-05 / extension contract gate.

    Adapters that cannot perform server-side revocation (e.g. pure signed
    cookies) MUST NOT be registered when policy requires
    `revoke_all_for_subject`. The caller presents a capability map and the
    guard refuses registration unless both capabilities are declared true.
    """
    if not isinstance(capabilities, Mapping):
        raise SessionInvariantError(
            "SESSION-INV-05: capability map MUST be a Mapping[str, bool]."
        )
    required = ("server_side_revocation", "subject_wide_revocation")
    missing = [k for k in required if not capabilities.get(k, False)]
    if missing:
        raise SessionInvariantError(
            "SESSION-INV-05: adapter lacks required capabilities "
            f"{missing}; signed-cookie-only adapters are FORBIDDEN when "
            "revoke_all_for_subject is required by policy."
        )
    # Sanity: adapter must actually implement the Protocol surface.
    for method in ("create", "load", "rotate", "revoke", "revoke_all_for_subject"):
        if not callable(getattr(adapter, method, None)):
            raise SessionInvariantError(
                "SESSION-INV-05: adapter MUST implement the SessionStore "
                f"Protocol; missing callable '{method}'."
            )


__all__ = [
    "DEFAULT_ABSOLUTE_TIMEOUT_S",
    "DEFAULT_IDLE_TIMEOUT_S",
    "CookieConfig",
    "InMemorySessionStore",
    "Session",
    "SessionInvariantError",
    "SessionStore",
    "mint_session_id",
    "register_adapter",
    "sids_equal",
    "validate_cookie_host",
]

# `field` is imported for future dataclass extensions in adapters that want to
# add optional fields without altering the Protocol surface. Keeping the
# import avoids an F401 in ruff once adapters start landing.
_ = field
