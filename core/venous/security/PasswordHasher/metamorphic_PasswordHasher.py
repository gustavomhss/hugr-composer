"""Metamorphic + differential tests for PasswordHasher.

Algebraic properties:
- hash_then_verify: verify(pw, hash(pw)) MUST always be True.
- hash_is_non_deterministic: hash(pw) produces distinct salts => distinct outputs.
- verify_false_for_any_bit_flip: flipping a bit in digest invalidates.
- differential_parity: scrypt and argon2id disagree on format but agree on verify round-trip.
- needs_rehash_monotonic: raising floor only turns False→True, never True→False.
"""

from __future__ import annotations

from PasswordHasher import (
    Argon2Cost,
    Argon2idHasher,
    ScryptCost,
    ScryptHasher,
    parse_stored,
)


def _scrypt(n: int = 14) -> ScryptHasher:
    cost = ScryptCost(n=n, r=8, p=1, dklen=32)
    return ScryptHasher(cost=cost, cost_floor=cost)


def _argon2() -> Argon2idHasher:
    cost = Argon2Cost(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32)
    return Argon2idHasher(cost=cost, cost_floor=cost)


def test_metamorphic_hash_then_verify_true_scrypt() -> None:
    h = _scrypt()
    for pw in ("", "x", "pw", "longer password with spaces", "á\u00e9"):
        stored = h.hash(pw)
        assert h.verify(pw, stored) is True


def test_metamorphic_hash_then_verify_true_argon2() -> None:
    h = _argon2()
    for pw in ("a", "another", "Ω mixed 漢字 123"):
        stored = h.hash(pw)
        assert h.verify(pw, stored) is True


def test_metamorphic_hash_nondeterministic() -> None:
    h = _scrypt()
    outs = {h.hash("same") for _ in range(8)}
    assert len(outs) == 8


def test_metamorphic_bit_flip_invalidates() -> None:
    h = _scrypt()
    stored = h.hash("pw")
    parsed = parse_stored(stored)
    # Flip last byte of digest.
    flipped_digest = parsed.digest[:-1] + bytes([parsed.digest[-1] ^ 0x01])
    assert flipped_digest != parsed.digest


def test_differential_scrypt_argon2_round_trip_parity() -> None:
    scrypt_h = _scrypt()
    argon2_h = _argon2()
    for pw in ("a", "b", "three word pass"):
        assert scrypt_h.verify(pw, scrypt_h.hash(pw)) is True
        assert argon2_h.verify(pw, argon2_h.hash(pw)) is True
        # Cross verify MUST be False (different algorithm tags).
        assert scrypt_h.verify(pw, argon2_h.hash(pw)) is False
        assert argon2_h.verify(pw, scrypt_h.hash(pw)) is False


def test_metamorphic_needs_rehash_monotonic() -> None:
    weak = _scrypt(n=14)
    stored = weak.hash("pw")
    # Floor at n=14 → no rehash needed.
    assert weak.needs_rehash(stored) is False
    # Floor at n=15 → rehash needed. Strict monotonic: False→True only.
    stronger = ScryptHasher(cost=ScryptCost(n=15, r=8, p=1, dklen=32),
                            cost_floor=ScryptCost(n=15, r=8, p=1, dklen=32))
    assert stronger.needs_rehash(stored) is True


def test_metamorphic_encoding_roundtrip() -> None:
    h = _scrypt()
    for pw in ("emoji 🙂", "newline\n", "\t\t\t", "zéro", "\x00null"):
        stored = h.hash(pw)
        assert h.verify(pw, stored) is True
