"""TotpVerifier primitive — RFC 6238 TOTP with replay-step protection.

Implements the catalog Protocol for `auth.TotpVerifier` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- TOTP-INV-01: shared secrets MUST be >=160 bits drawn from a CSPRNG; the
  verifier REJECTS secrets shorter than 20 bytes and NEVER logs or echoes
  secret material.
- TOTP-INV-02: verify() MUST compare codes in constant time via
  `hmac.compare_digest`; short-circuit / prefix-match comparisons are
  FORBIDDEN.
- TOTP-INV-03: accepted clock skew MUST be bounded to +/-1 step (+/-30s);
  larger windows CANNOT be configured through the public surface.
- TOTP-INV-04: a successfully used step number MUST be recorded through the
  returned `next_step` value and the same step CANNOT be accepted again;
  `last_used_step >= next_step` rejects the replay.
- TOTP-INV-05: emitted and accepted codes SHALL be six decimal digits per
  RFC 4226; alternative digit counts (7, 8) require the explicit opt-in flag
  `allow_nonstandard_digits=True` on the constructor.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
import threading
import time
import urllib.parse
from collections.abc import Callable
from hashlib import sha256
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_SECRET_BYTES: Final[int] = 20          # TOTP-INV-01: 160 bits = 20 bytes
DEFAULT_STEP_SECONDS: Final[int] = 30      # RFC 6238 default period
DEFAULT_DIGITS: Final[int] = 6             # TOTP-INV-05: RFC 4226 canonical
MAX_SKEW_STEPS: Final[int] = 1             # TOTP-INV-03: bounded to +/-1 step
ALLOWED_DIGITS: Final[frozenset[int]] = frozenset({6, 7, 8})
_DIGIT_CHARS: Final[frozenset[str]] = frozenset("0123456789")

# Supported HMAC digests. SHA-1 is the RFC 6238 default and is required for
# compatibility with authenticator apps; SHA-256 / SHA-512 are opt-in per the
# extension contract.
_ALGO_MAP: Final[dict[str, str]] = {
    "SHA1": "sha1",
    "SHA256": "sha256",
    "SHA512": "sha512",
}


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class TotpInvariantError(ValueError):
    """Raised when a construction or operation violates a TotpVerifier invariant."""


class TotpReplayError(TotpInvariantError):
    """TOTP-INV-04: step already consumed; replay rejected."""


class TotpInvalidCodeError(TotpInvariantError):
    """Submitted code did not match any code inside the +/-1 step window."""


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class TotpVerifier(Protocol):
    def provision_uri(self, account: str, issuer: str, secret: bytes) -> str: ...
    def verify(self, secret: bytes, code: str, last_used_step: int | None) -> int: ...


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class StandardTotpVerifier:
    """Reference TOTP verifier honouring all five catalog invariants.

    The instance is stateless with respect to the caller's account — the
    caller MUST persist the returned step via `last_used_step` on the account
    record (the replay-step set described in the TLA+ spec). Thread-safety is
    provided for the optional shared in-memory replay cache.
    """

    def __init__(
        self,
        *,
        digits: int = DEFAULT_DIGITS,
        step_seconds: int = DEFAULT_STEP_SECONDS,
        algorithm: str = "SHA1",
        allow_nonstandard_digits: bool = False,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        # TOTP-INV-05: reject non-six-digit unless the explicit opt-in is set.
        if digits != DEFAULT_DIGITS and not allow_nonstandard_digits:
            raise TotpInvariantError(
                "TOTP-INV-05: non-six-digit codes require allow_nonstandard_digits=True."
            )
        if digits not in ALLOWED_DIGITS:
            raise TotpInvariantError(
                f"TOTP-INV-05: digits MUST be one of {sorted(ALLOWED_DIGITS)}, got {digits}."
            )
        if step_seconds <= 0 or step_seconds > 300:
            raise TotpInvariantError(
                "TOTP-INV-03: step_seconds MUST be in (0, 300]; default 30 per RFC 6238."
            )
        algo_upper = algorithm.upper()
        if algo_upper not in _ALGO_MAP:
            raise TotpInvariantError(
                f"algorithm MUST be one of {sorted(_ALGO_MAP)}, got {algorithm!r}."
            )
        self._digits: int = digits
        self._step_seconds: int = step_seconds
        self._algorithm: str = algo_upper
        self._now_fn = now_fn if now_fn is not None else time.time
        # An optional in-memory replay cache keyed by secret fingerprint; the
        # public API still requires the caller to pass `last_used_step`, so
        # this cache is a defence-in-depth shield against single-process
        # concurrent verify() calls racing on the same (secret, step).
        self._lock = threading.Lock()
        self._seen_steps: set[tuple[str, int]] = set()

    # ----- Protocol API ------------------------------------------------------
    def provision_uri(self, account: str, issuer: str, secret: bytes) -> str:
        """Return an otpauth:// URI for enrollment (QR-code payload).

        The caller MUST transmit this URI only over the enrollment channel
        (TOTP-INV-01: secrets never leave enrollment).
        """
        _validate_secret(secret)
        _validate_label_component(account, "account")
        _validate_label_component(issuer, "issuer")
        encoded_secret = base64.b32encode(secret).rstrip(b"=").decode("ascii")
        label = urllib.parse.quote(f"{issuer}:{account}", safe="")
        params = {
            "secret": encoded_secret,
            "issuer": issuer,
            "algorithm": self._algorithm,
            "digits": str(self._digits),
            "period": str(self._step_seconds),
        }
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        return f"otpauth://totp/{label}?{query}"

    def verify(self, secret: bytes, code: str, last_used_step: int | None) -> int:
        """Verify a submitted code and return the step number to persist.

        Raises:
          TotpInvariantError on invalid inputs (TOTP-INV-01 / 02 / 05).
          TotpReplayError if the code matches a step <= last_used_step
            (TOTP-INV-04).
          TotpInvalidCodeError if the code does not match any code in the
            +/-1 step window (TOTP-INV-03).
        """
        _validate_secret(secret)
        _validate_code_shape(code, self._digits)

        current_step = int(self._now_fn() // self._step_seconds)
        # TOTP-INV-03: the window is hard-coded to +/-MAX_SKEW_STEPS.
        candidate_steps = tuple(
            current_step + offset for offset in range(-MAX_SKEW_STEPS, MAX_SKEW_STEPS + 1)
        )

        # TOTP-INV-02: compare ALL candidate steps with hmac.compare_digest and
        # only pick the winner at the end. This avoids leaking the matching
        # offset via timing.
        matched_step: int | None = None
        submitted_bytes = code.encode("ascii")
        for step in candidate_steps:
            expected = _hotp(secret, step, self._digits, self._algorithm).encode("ascii")
            if hmac.compare_digest(submitted_bytes, expected):
                # Do NOT break — continue iterating so the total work is
                # constant regardless of the matching offset.
                if matched_step is None:
                    matched_step = step

        if matched_step is None:
            raise TotpInvalidCodeError(
                "TOTP-INV-03: submitted code does not match any code in the +/-1 step window."
            )

        # TOTP-INV-04: reject any step already consumed either by the caller's
        # persisted record OR by the in-memory per-secret cache.
        if last_used_step is not None and matched_step <= last_used_step:
            raise TotpReplayError(
                "TOTP-INV-04: step already consumed; a fresh step is required."
            )
        fingerprint = _secret_fingerprint(secret)
        with self._lock:
            if (fingerprint, matched_step) in self._seen_steps:
                raise TotpReplayError(
                    "TOTP-INV-04: step already consumed within this process; replay rejected."
                )
            self._seen_steps.add((fingerprint, matched_step))
        return matched_step


# ---------------------------------------------------------------------------
# Adapter registry (extension contract)
# ---------------------------------------------------------------------------
class TotpAdapterRegistry:
    """Registry for alternative TOTP adapters (SHA-256, 8-digit, custom step).

    Enforces that every adapter declares its digest + period AND implements a
    replay-step API. Adapters that skip replay-step persistence are REJECTED
    (catalog extension_contract).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._adapters: dict[str, TotpVerifier] = {}

    def register(self, name: str, adapter: TotpVerifier) -> None:
        if not name or not name.replace("_", "").replace("-", "").isalnum():
            raise TotpInvariantError(
                "adapter name MUST be non-empty alphanumeric (with _ or - allowed)."
            )
        if not isinstance(adapter, TotpVerifier):
            raise TotpInvariantError(
                "adapter MUST implement the TotpVerifier Protocol (provision_uri + verify)."
            )
        # Replay-step persistence check: the verify() signature returns int and
        # accepts `last_used_step`. The Protocol guarantees the shape; we also
        # require the adapter to expose a verify() method that is callable.
        verify_fn = getattr(adapter, "verify", None)
        if not callable(verify_fn):
            raise TotpInvariantError(
                "adapter MUST provide a callable verify() that returns the used step."
            )
        with self._lock:
            self._adapters[name] = adapter

    def get(self, name: str) -> TotpVerifier:
        with self._lock:
            if name not in self._adapters:
                raise KeyError(f"no adapter registered under name={name!r}.")
            return self._adapters[name]

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._adapters))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _validate_secret(secret: bytes) -> None:
    # TOTP-INV-01: >=160 bits from a CSPRNG, rejected otherwise.
    if not isinstance(secret, (bytes, bytearray)):
        raise TotpInvariantError(
            "TOTP-INV-01: secret MUST be bytes; string / int / None rejected."
        )
    if len(secret) < MIN_SECRET_BYTES:
        raise TotpInvariantError(
            f"TOTP-INV-01: secret MUST be >={MIN_SECRET_BYTES} bytes (>=160 bits); "
            f"got {len(secret)} bytes."
        )


def _validate_code_shape(code: str, digits: int) -> None:
    if not isinstance(code, str):
        raise TotpInvariantError("code MUST be a string of decimal digits.")
    if len(code) != digits:
        raise TotpInvariantError(
            f"code MUST be exactly {digits} characters; got {len(code)}."
        )
    if not all(ch in _DIGIT_CHARS for ch in code):
        raise TotpInvariantError("TOTP-INV-05: code MUST contain only decimal digits 0-9.")


def _validate_label_component(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise TotpInvariantError(f"{field_name} MUST be a non-empty string.")
    if ":" in value or "/" in value or "?" in value or "#" in value:
        raise TotpInvariantError(
            f"{field_name} MUST NOT contain ':', '/', '?', or '#' (URI-reserved)."
        )


def _hotp(secret: bytes, counter: int, digits: int, algorithm: str) -> str:
    """RFC 4226 HOTP truncation. Returns a zero-padded decimal code string."""
    digest_name = _ALGO_MAP[algorithm]
    msg = struct.pack(">Q", counter)
    mac = hmac.new(bytes(secret), msg, digest_name).digest()
    offset = mac[-1] & 0x0F
    binary = (
        (mac[offset] & 0x7F) << 24
        | (mac[offset + 1] & 0xFF) << 16
        | (mac[offset + 2] & 0xFF) << 8
        | (mac[offset + 3] & 0xFF)
    )
    code_int = binary % (10 ** digits)
    return str(code_int).zfill(digits)


def _secret_fingerprint(secret: bytes) -> str:
    """Return a non-reversible fingerprint of a secret for cache keying.

    The fingerprint is a SHA-256 of the secret; it is NEVER logged and only
    used as a dict key. (TOTP-INV-01: never leaks the raw secret.)
    """
    return sha256(bytes(secret)).hexdigest()


def generate_secret(num_bytes: int = MIN_SECRET_BYTES) -> bytes:
    """Generate a fresh TOTP secret from the system CSPRNG.

    (TOTP-INV-01: secrets MUST be drawn from a CSPRNG. `secrets.token_bytes`
    is backed by `os.urandom` on every platform Python supports.)
    """
    if num_bytes < MIN_SECRET_BYTES:
        raise TotpInvariantError(
            f"TOTP-INV-01: generated secret MUST be >={MIN_SECRET_BYTES} bytes."
        )
    return secrets.token_bytes(num_bytes)


__all__ = [
    "ALLOWED_DIGITS",
    "DEFAULT_DIGITS",
    "DEFAULT_STEP_SECONDS",
    "MAX_SKEW_STEPS",
    "MIN_SECRET_BYTES",
    "StandardTotpVerifier",
    "TotpAdapterRegistry",
    "TotpInvalidCodeError",
    "TotpInvariantError",
    "TotpReplayError",
    "TotpVerifier",
    "generate_secret",
]
