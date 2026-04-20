"""Behavioral end-to-end scenarios for PasswordHasher."""

from __future__ import annotations

import pytest

from PasswordHasher import (
    Argon2Cost,
    Argon2idHasher,
    PasswordHasherError,
    ScryptCost,
    ScryptHasher,
    parse_stored,
)


def _scrypt() -> ScryptHasher:
    cost = ScryptCost(n=14, r=8, p=1, dklen=32)
    return ScryptHasher(cost=cost, cost_floor=cost)


def test_scenario_register_then_login() -> None:
    h = _scrypt()
    stored = h.hash("user_password_42")
    assert h.verify("user_password_42", stored) is True
    assert h.verify("user_password_43", stored) is False


def test_scenario_migration_on_cost_floor_raise() -> None:
    old = ScryptHasher(cost=ScryptCost(n=14, r=8, p=1, dklen=32),
                      cost_floor=ScryptCost(n=14, r=8, p=1, dklen=32))
    stored = old.hash("pw")
    new = ScryptHasher(cost=ScryptCost(n=15, r=8, p=1, dklen=32),
                      cost_floor=ScryptCost(n=15, r=8, p=1, dklen=32))
    assert new.needs_rehash(stored) is True
    # After a successful login under the OLD hasher we rehash with the new one.
    assert old.verify("pw", stored) is True
    rehashed = new.hash("pw")
    assert new.needs_rehash(rehashed) is False


def test_scenario_cross_algorithm_migration() -> None:
    scrypt_h = _scrypt()
    argon2_h = Argon2idHasher(
        cost=Argon2Cost(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32),
        cost_floor=Argon2Cost(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32),
    )
    scrypt_stored = scrypt_h.hash("pw")
    # Argon2id hasher sees a scrypt verifier and demands rehash.
    assert argon2_h.needs_rehash(scrypt_stored) is True


def test_scenario_tampered_digest_rejected() -> None:
    h = _scrypt()
    stored = h.hash("hello")
    parts = stored.split("$")
    # Flip one character in the digest field.
    parts[4] = parts[4][:-1] + ("A" if parts[4][-1] != "A" else "B")
    tampered = "$".join(parts)
    assert h.verify("hello", tampered) is False


def test_scenario_malformed_verifier_rejected_without_leaking_plaintext() -> None:
    h = _scrypt()
    secret = "sensitivePlaintext__canary"
    try:
        h.verify(secret, "$md5$$AAAA$BBBB")
    except PasswordHasherError as e:
        assert secret not in str(e)


def test_scenario_multi_user_no_salt_reuse() -> None:
    h = _scrypt()
    shared_password = "everyone-picks-this"
    stored_a = h.hash(shared_password)
    stored_b = h.hash(shared_password)
    stored_c = h.hash(shared_password)
    a, b, c = parse_stored(stored_a), parse_stored(stored_b), parse_stored(stored_c)
    assert len({a.salt, b.salt, c.salt}) == 3
    # Same plaintext with distinct salts MUST produce distinct digests.
    assert len({a.digest, b.digest, c.digest}) == 3


def test_scenario_argon2_is_preferred_for_production_profile() -> None:
    h = Argon2idHasher(
        cost=Argon2Cost(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32),
        cost_floor=Argon2Cost(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32),
    )
    stored = h.hash("secret")
    parsed = parse_stored(stored)
    assert parsed.algo == "argon2id"
    assert parsed.params["m"] >= 19456  # OWASP floor
    assert h.verify("secret", stored) is True


def test_scenario_type_rejection_does_not_leak_value() -> None:
    h = _scrypt()
    with pytest.raises(PasswordHasherError) as err:
        h.hash(b"bytes-not-allowed")  # type: ignore[arg-type]
    assert "plaintext" in str(err.value).lower()
    # The error MUST NOT echo the bytes value.
    assert "bytes-not-allowed" not in str(err.value)
