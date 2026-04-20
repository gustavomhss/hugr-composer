"""PasswordHasher primitive — Argon2id password verifier with rotation metadata.

Implements the catalog Protocol for `security.PasswordHasher`. Uses argon2-cffi
when available and falls back to a stdlib-only scrypt-based reference so the
module remains importable on minimal hosts (stdlib scrypt is also memory-hard).

Import is side-effect-free: the optional `argon2` SDK is imported lazily inside
`Argon2idHasher.__init__`.

Invariant IDs (enforced at runtime):

- PWD-INV-01: stored verifier MUST encode algorithm, cost params, salt, digest.
- PWD-INV-02: verify() MUST compare in constant time (hmac.compare_digest).
- PWD-INV-03: salt MUST be ≥16 bytes from CSPRNG; MUST NEVER be reused.
- PWD-INV-04: KDF MUST be memory-hard (Argon2id / scrypt); SHA-2/MD5/PBKDF1 FORBIDDEN.
- PWD-INV-05: needs_rehash() MUST return True when stored cost < configured floor.
- PWD-INV-06: plaintext MUST NEVER be logged, serialized, or included in exceptions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

MIN_SALT_BYTES: Final[int] = 16
# Weak hash names that MUST NEVER be accepted as algorithm identifiers.
FORBIDDEN_ALGOS: Final[frozenset[str]] = frozenset(
    {"md5", "sha1", "sha224", "sha256", "sha384", "sha512", "pbkdf1", "crypt"}
)
ALLOWED_ALGOS: Final[frozenset[str]] = frozenset({"argon2id", "scrypt"})


class PasswordHasherError(ValueError):
    """Runtime invariant violation on a PasswordHasher operation.

    Message text NEVER contains the plaintext value — PWD-INV-06.
    """


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class PasswordHasher(Protocol):
    def hash(self, plaintext: str) -> str: ...
    def verify(self, plaintext: str, stored: str) -> bool: ...
    def needs_rehash(self, stored: str) -> bool: ...


# ---------------------------------------------------------------------------
# Serialization helpers — Modular Crypt Format (MCF) style `$algo$params$salt$digest`
# ---------------------------------------------------------------------------
def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.b64decode(s + pad)


@dataclass(frozen=True)
class _Parsed:
    algo: str
    params: dict[str, int]
    salt: bytes
    digest: bytes


def _parse_params(params_str: str) -> dict[str, int]:
    params: dict[str, int] = {}
    if not params_str:
        return params
    for piece in params_str.split(","):
        if "=" not in piece:
            raise PasswordHasherError("PWD-INV-01: malformed cost parameter.")
        k, v = piece.split("=", 1)
        try:
            params[k] = int(v)
        except ValueError as exc:
            raise PasswordHasherError("PWD-INV-01: cost parameter MUST be integer.") from exc
    return params


def parse_stored(stored: str) -> _Parsed:
    """Decompose an MCF-like stored verifier; raises on malformed input."""
    if not isinstance(stored, str) or not stored.startswith("$"):
        raise PasswordHasherError("PWD-INV-01: stored verifier has wrong framing.")
    parts = stored.split("$")
    # `$algo$params$salt$digest` → ['', algo, params, salt, digest]
    if len(parts) != 5:
        raise PasswordHasherError("PWD-INV-01: stored verifier MUST have 4 fields.")
    _, algo, params_str, salt_b64, digest_b64 = parts
    algo_lower = algo.lower()
    if algo_lower in FORBIDDEN_ALGOS:
        raise PasswordHasherError(
            f"PWD-INV-04: algorithm {algo!r} is FORBIDDEN (non-memory-hard)."
        )
    if algo_lower not in ALLOWED_ALGOS:
        raise PasswordHasherError(
            f"PWD-INV-04: algorithm {algo!r} is not on the allow-list."
        )
    params = _parse_params(params_str)
    try:
        salt = _b64d(salt_b64)
        digest = _b64d(digest_b64)
    except ValueError as exc:
        raise PasswordHasherError("PWD-INV-01: salt/digest base64 decode failed.") from exc
    if len(salt) < MIN_SALT_BYTES:
        raise PasswordHasherError(
            f"PWD-INV-03: salt MUST be ≥{MIN_SALT_BYTES} bytes; got {len(salt)}."
        )
    return _Parsed(algo=algo_lower, params=params, salt=salt, digest=digest)


def _render(algo: str, params: dict[str, int], salt: bytes, digest: bytes) -> str:
    params_str = ",".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"${algo}${params_str}${_b64e(salt)}${_b64e(digest)}"


# ---------------------------------------------------------------------------
# Scrypt reference implementation — stdlib only, memory-hard
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScryptCost:
    """Scrypt cost vector; `n` is log2-form (n=15 → 2**15=32768)."""

    n: int = 15
    r: int = 8
    p: int = 1
    dklen: int = 32


class ScryptHasher:
    """Stdlib scrypt verifier. Suitable as a reference when argon2 is absent.

    scrypt is memory-hard (PWD-INV-04). This implementation honors all six
    PWD invariants. For production prefer Argon2idHasher (argon2-cffi).
    """

    def __init__(self, cost: ScryptCost | None = None, cost_floor: ScryptCost | None = None) -> None:
        self._cost = cost or ScryptCost()
        self._floor = cost_floor or ScryptCost()
        self._validate_cost(self._cost)
        self._validate_cost(self._floor)

    @staticmethod
    def _validate_cost(c: ScryptCost) -> None:
        if c.n < 14 or c.n > 22:
            raise PasswordHasherError(
                "PWD-INV-05: scrypt n MUST be 14..22; smaller is weak, larger starves memory."
            )
        if c.r < 1 or c.p < 1 or c.dklen < 32:
            raise PasswordHasherError(
                "PWD-INV-05: scrypt r, p MUST be ≥1 and dklen ≥32."
            )

    def hash(self, plaintext: str) -> str:
        if not isinstance(plaintext, str):
            # PWD-INV-06: DO NOT echo the plaintext in the error.
            raise PasswordHasherError("PWD-INV-06: plaintext MUST be str (value withheld).")
        # PWD-INV-03: fresh CSPRNG salt for every credential.
        salt = secrets.token_bytes(MIN_SALT_BYTES)
        digest = hashlib.scrypt(
            plaintext.encode("utf-8"),
            salt=salt,
            n=2 ** self._cost.n,
            r=self._cost.r,
            p=self._cost.p,
            dklen=self._cost.dklen,
            maxmem=256 * 1024 * 1024,
        )
        return _render(
            "scrypt",
            {"n": self._cost.n, "r": self._cost.r, "p": self._cost.p, "dklen": self._cost.dklen},
            salt,
            digest,
        )

    def verify(self, plaintext: str, stored: str) -> bool:
        if not isinstance(plaintext, str):
            raise PasswordHasherError("PWD-INV-06: plaintext MUST be str (value withheld).")
        parsed = parse_stored(stored)
        if parsed.algo != "scrypt":
            # Not our format — caller must dispatch by algorithm tag in production.
            return False
        try:
            computed = hashlib.scrypt(
                plaintext.encode("utf-8"),
                salt=parsed.salt,
                n=2 ** parsed.params["n"],
                r=parsed.params["r"],
                p=parsed.params["p"],
                dklen=parsed.params["dklen"],
                maxmem=256 * 1024 * 1024,
            )
        except (KeyError, ValueError):
            return False
        # PWD-INV-02: constant-time compare.
        return hmac.compare_digest(computed, parsed.digest)

    def needs_rehash(self, stored: str) -> bool:
        parsed = parse_stored(stored)
        if parsed.algo != "scrypt":
            return True
        # PWD-INV-05: rehash when any stored param is below the floor.
        return (
            parsed.params.get("n", 0) < self._floor.n
            or parsed.params.get("r", 0) < self._floor.r
            or parsed.params.get("p", 0) < self._floor.p
            or parsed.params.get("dklen", 0) < self._floor.dklen
        )


# ---------------------------------------------------------------------------
# Argon2id implementation — preferred in production
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Argon2Cost:
    """Argon2id cost vector."""

    time_cost: int = 3
    memory_cost: int = 65536  # 64 MiB
    parallelism: int = 4
    hash_len: int = 32


class Argon2idHasher:
    """Argon2id-backed hasher. Requires `argon2-cffi`.

    We build the stored string ourselves so the on-disk format is stable across
    argon2-cffi versions and matches our `parse_stored` reader exactly.
    """

    def __init__(
        self,
        cost: Argon2Cost | None = None,
        cost_floor: Argon2Cost | None = None,
    ) -> None:
        # Lazy import — keeps module side-effect free.
        from argon2.low_level import Type, hash_secret_raw

        self._Type = Type
        self._hash_secret_raw = hash_secret_raw
        self._cost = cost or Argon2Cost()
        self._floor = cost_floor or Argon2Cost()
        self._validate(self._cost)
        self._validate(self._floor)

    @staticmethod
    def _validate(c: Argon2Cost) -> None:
        if c.time_cost < 2:
            raise PasswordHasherError("PWD-INV-05: argon2id time_cost MUST be ≥2.")
        if c.memory_cost < 19456:
            raise PasswordHasherError(
                "PWD-INV-05: argon2id memory_cost MUST be ≥19456 KiB per OWASP guidance."
            )
        if c.parallelism < 1 or c.hash_len < 16:
            raise PasswordHasherError(
                "PWD-INV-05: argon2id parallelism ≥1 and hash_len ≥16."
            )

    def hash(self, plaintext: str) -> str:
        if not isinstance(plaintext, str):
            raise PasswordHasherError("PWD-INV-06: plaintext MUST be str (value withheld).")
        salt = secrets.token_bytes(MIN_SALT_BYTES)
        digest = self._hash_secret_raw(
            secret=plaintext.encode("utf-8"),
            salt=salt,
            time_cost=self._cost.time_cost,
            memory_cost=self._cost.memory_cost,
            parallelism=self._cost.parallelism,
            hash_len=self._cost.hash_len,
            type=self._Type.ID,
        )
        return _render(
            "argon2id",
            {
                "t": self._cost.time_cost,
                "m": self._cost.memory_cost,
                "p": self._cost.parallelism,
                "l": self._cost.hash_len,
            },
            salt,
            digest,
        )

    def verify(self, plaintext: str, stored: str) -> bool:
        if not isinstance(plaintext, str):
            raise PasswordHasherError("PWD-INV-06: plaintext MUST be str (value withheld).")
        parsed = parse_stored(stored)
        if parsed.algo != "argon2id":
            return False
        try:
            computed = self._hash_secret_raw(
                secret=plaintext.encode("utf-8"),
                salt=parsed.salt,
                time_cost=parsed.params["t"],
                memory_cost=parsed.params["m"],
                parallelism=parsed.params["p"],
                hash_len=parsed.params["l"],
                type=self._Type.ID,
            )
        except (KeyError, ValueError):
            return False
        return hmac.compare_digest(computed, parsed.digest)

    def needs_rehash(self, stored: str) -> bool:
        parsed = parse_stored(stored)
        if parsed.algo != "argon2id":
            return True
        return (
            parsed.params.get("t", 0) < self._floor.time_cost
            or parsed.params.get("m", 0) < self._floor.memory_cost
            or parsed.params.get("p", 0) < self._floor.parallelism
            or parsed.params.get("l", 0) < self._floor.hash_len
        )


__all__ = [
    "ALLOWED_ALGOS",
    "FORBIDDEN_ALGOS",
    "MIN_SALT_BYTES",
    "Argon2Cost",
    "Argon2idHasher",
    "PasswordHasher",
    "PasswordHasherError",
    "ScryptCost",
    "ScryptHasher",
    "parse_stored",
]
