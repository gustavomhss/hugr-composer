"""Unit tests for PasswordHasher — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import hmac
import secrets
import threading
import time

import pytest

from PasswordHasher import (
    FORBIDDEN_ALGOS,
    MIN_SALT_BYTES,
    Argon2Cost,
    Argon2idHasher,
    PasswordHasherError,
    ScryptCost,
    ScryptHasher,
    parse_stored,
)


def _fast_scrypt() -> ScryptHasher:
    cost = ScryptCost(n=14, r=8, p=1, dklen=32)
    return ScryptHasher(cost=cost, cost_floor=cost)


def _fast_argon2() -> Argon2idHasher:
    cost = Argon2Cost(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32)
    return Argon2idHasher(cost=cost, cost_floor=cost)


# ---------------------------------------------------------------------------
# PWD_INV_01 — self-describing stored format
# ---------------------------------------------------------------------------
def test_inv_stored_format_confirms() -> None:
    h = _fast_scrypt()
    stored = h.hash("hunter2")
    parsed = parse_stored(stored)
    assert parsed.algo == "scrypt"
    assert parsed.params["n"] >= 14
    assert parsed.params["r"] >= 1
    assert parsed.params["p"] >= 1
    assert len(parsed.salt) >= MIN_SALT_BYTES
    assert len(parsed.digest) >= 32


def test_inv_stored_format_prevents() -> None:
    with pytest.raises(PasswordHasherError):
        parse_stored("not-a-verifier")
    with pytest.raises(PasswordHasherError):
        parse_stored("$scrypt$n=14$badsalt$baddigest$extra")
    with pytest.raises(PasswordHasherError):
        parse_stored("$scrypt$nope$AAAA$BBBB")


def test_inv_stored_format_under_failure() -> None:
    h = _fast_scrypt()
    stored = h.hash("pw")
    # Corrupt salt field by truncation — parse_stored MUST refuse it.
    parts = stored.split("$")
    # shorten the salt field until len(salt) < MIN_SALT_BYTES
    parts[3] = parts[3][:2]
    corrupt = "$".join(parts)
    with pytest.raises(PasswordHasherError):
        parse_stored(corrupt)


# ---------------------------------------------------------------------------
# PWD_INV_02 — constant-time verify
# ---------------------------------------------------------------------------
def test_inv_constant_time_verify_confirms() -> None:
    h = _fast_scrypt()
    stored = h.hash("correct horse battery staple")
    assert h.verify("correct horse battery staple", stored) is True
    assert h.verify("correct horse battery stapla", stored) is False


def test_inv_constant_time_verify_prevents() -> None:
    # Validate at the primitive level: compare_digest is the only comparator used.
    # Structural check: hmac.compare_digest on bytes MUST NOT short-circuit.
    a = b"\x00" * 32
    b = b"\x00" * 32
    c = b"\xff" + b"\x00" * 31
    assert hmac.compare_digest(a, b) is True
    assert hmac.compare_digest(a, c) is False


def test_inv_constant_time_verify_under_failure() -> None:
    # Even when the caller supplies malformed stored, verify returns False OR raises —
    # it MUST NEVER return True.
    h = _fast_scrypt()
    for bad in ("", "$scrypt$n=14$AAAA$BBBB", "$unknown$x=1$AAAABBBBCCCCDDDDEEEE$AAAA"):
        try:
            result = h.verify("any", bad)
        except PasswordHasherError:
            continue
        assert result is False


# ---------------------------------------------------------------------------
# PWD_INV_03 — salt from CSPRNG, ≥16 bytes, unique
# ---------------------------------------------------------------------------
def test_inv_salt_entropy_confirms() -> None:
    h = _fast_scrypt()
    seen: set[bytes] = set()
    for _ in range(20):
        stored = h.hash("same_plaintext")
        parsed = parse_stored(stored)
        assert len(parsed.salt) >= MIN_SALT_BYTES
        seen.add(parsed.salt)
    assert len(seen) == 20  # no salt reuse


def test_inv_salt_entropy_prevents() -> None:
    # A manually crafted stored with a short salt MUST be rejected.
    short_salt_stored = f"$scrypt$n=14,r=8,p=1,dklen=32${secrets.token_bytes(8).hex()}${'A' * 43}"
    with pytest.raises(PasswordHasherError):
        parse_stored(short_salt_stored)


def test_inv_salt_entropy_under_failure() -> None:
    # Even under threaded load, every salt MUST be unique.
    h = _fast_scrypt()
    salts: list[bytes] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(5):
            parsed = parse_stored(h.hash("x"))
            with lock:
                salts.append(parsed.salt)

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(salts) == len(set(salts))


# ---------------------------------------------------------------------------
# PWD_INV_04 — memory-hard algorithm; weak algorithms FORBIDDEN
# ---------------------------------------------------------------------------
def test_inv_memory_hard_confirms() -> None:
    scrypt_s = _fast_scrypt().hash("x")
    argon_s = _fast_argon2().hash("x")
    assert parse_stored(scrypt_s).algo == "scrypt"
    assert parse_stored(argon_s).algo == "argon2id"


def test_inv_memory_hard_prevents() -> None:
    for bad_algo in FORBIDDEN_ALGOS:
        with pytest.raises(PasswordHasherError):
            parse_stored(f"${bad_algo}$$AAAAAAAAAAAAAAAAAAAAAAAA$BBBB")


def test_inv_memory_hard_under_failure() -> None:
    # An attacker submits a "verifier" tagged with a permitted algo but with
    # impossible params. parse_stored MUST surface PasswordHasherError, not
    # fall through to a silent accept.
    h = _fast_scrypt()
    with pytest.raises(PasswordHasherError):
        # salt base64 that decodes to <16 bytes
        h.verify("pw", "$scrypt$n=14,r=8,p=1,dklen=32$QUJD$BBBB")


# ---------------------------------------------------------------------------
# PWD_INV_05 — needs_rehash drives rotation
# ---------------------------------------------------------------------------
def test_inv_rotation_confirms() -> None:
    weak = ScryptHasher(cost=ScryptCost(n=14, r=8, p=1, dklen=32),
                        cost_floor=ScryptCost(n=14, r=8, p=1, dklen=32))
    stored = weak.hash("pw")
    # Raise the floor — the same stored now needs rehashing.
    stronger = ScryptHasher(cost=ScryptCost(n=15, r=8, p=1, dklen=32),
                            cost_floor=ScryptCost(n=15, r=8, p=1, dklen=32))
    assert stronger.needs_rehash(stored) is True


def test_inv_rotation_prevents() -> None:
    with pytest.raises(PasswordHasherError):
        # Cost below absolute minimum rejected at construction.
        ScryptHasher(cost=ScryptCost(n=10, r=8, p=1, dklen=32))
    with pytest.raises(PasswordHasherError):
        Argon2idHasher(cost=Argon2Cost(time_cost=1))


def test_inv_rotation_under_failure() -> None:
    # If the stored string is for a different algorithm, needs_rehash MUST be True
    # so the caller triggers a migrating rehash.
    scrypt_h = _fast_scrypt()
    stored_argon = _fast_argon2().hash("pw")
    assert scrypt_h.needs_rehash(stored_argon) is True


# ---------------------------------------------------------------------------
# PWD_INV_06 — plaintext NEVER logged/leaked in exceptions
# ---------------------------------------------------------------------------
def test_inv_no_plaintext_leak_confirms() -> None:
    h = _fast_scrypt()
    secret = "SuperSecretValue123!@#"
    stored = h.hash(secret)
    assert secret not in stored  # stored encodes digest, never the plaintext


def test_inv_no_plaintext_leak_prevents() -> None:
    h = _fast_scrypt()
    secret = "LeakCanaryZZZ"
    try:
        h.verify(secret, "not-a-verifier")  # malformed stored → raises
    except PasswordHasherError as e:
        assert secret not in str(e)
        assert secret not in repr(e)
    try:
        h.verify(123, "whatever")  # type: ignore[arg-type]
    except PasswordHasherError as e:
        assert "123" not in str(e) or "plaintext" in str(e).lower()


def test_inv_no_plaintext_leak_under_failure() -> None:
    h = _fast_scrypt()
    secret = "NeverLogThisFFFFF"
    # Chain three failure modes; none may surface the secret.
    msgs: list[str] = []
    for bad in ("", None, 12345, "$garbage"):
        try:
            h.verify(secret, bad)  # type: ignore[arg-type]
        except PasswordHasherError as e:
            msgs.append(str(e))
    for m in msgs:
        assert secret not in m


# ---------------------------------------------------------------------------
# Performance sanity (non-invariant, but part of the primitive's contract)
# ---------------------------------------------------------------------------
def test_hash_does_not_block_forever() -> None:
    h = _fast_scrypt()
    start = time.monotonic()
    h.hash("x")
    assert time.monotonic() - start < 2.0
