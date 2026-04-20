"""Behavioral end-to-end scenarios for CryptoEnvelope.

Each scenario exercises the Protocol surface through a realistic workflow
(store PII, rotate key, replay attempt, adversarial ciphertext). The scenarios
prove the CRY invariants hold at runtime, not just in unit fixtures.
"""

from __future__ import annotations

import secrets

import pytest

from CryptoEnvelope import (
    AeadEnvelope,
    CryptoEnvelopeError,
    Envelope,
    InMemoryKeyVault,
)


def _fresh_vault(algorithm: str = "AES-GCM") -> InMemoryKeyVault:
    vault = InMemoryKeyVault()
    key_len = 32 if algorithm == "ChaCha20-Poly1305" else 32
    vault.register("k-prod-1", secrets.token_bytes(key_len), algorithm=algorithm)
    return vault


def test_scenario_store_then_read_pii() -> None:
    """Classic PII store/read round-trip bound to a record id via aad."""
    vault = _fresh_vault()
    env = AeadEnvelope(vault)
    record_id = "user-42"
    pii = b'{"ssn":"123-45-6789"}'
    sealed = env.seal(plaintext=pii, aad=record_id.encode())
    # Storage layer replays record_id as aad on read.
    assert env.open(sealed, record_id.encode()) == pii


def test_scenario_cross_record_aad_attack_fails() -> None:
    """An attacker with DB write swaps envelope between two records.

    Under CRY-INV-03 the aad mismatch MUST abort before plaintext is returned.
    """
    vault = _fresh_vault()
    env = AeadEnvelope(vault)
    sealed_a = env.seal(b"secret-for-A", aad=b"record_id=A")
    # Attacker overwrites record B with envelope A's ciphertext. Reader replays
    # B's id as aad — open MUST reject.
    with pytest.raises(CryptoEnvelopeError):
        env.open(sealed_a, aad=b"record_id=B")


def test_scenario_rotate_key_keeps_old_ciphertext_readable() -> None:
    """Rotation is write-time-only; stored ciphertext keeps opening under its own key."""
    vault = _fresh_vault()
    env = AeadEnvelope(vault)
    old_sealed = env.seal(b"historical", aad=b"aad-hist")
    assert old_sealed.key_id == "k-prod-1"

    # Introduce k-prod-2, flip active.
    vault.register("k-prod-2", secrets.token_bytes(32))
    vault.set_active("k-prod-2")

    fresh_sealed = env.seal(b"current", aad=b"aad-current")
    assert fresh_sealed.key_id == "k-prod-2"

    # Both envelopes open; ciphertext was NOT re-encrypted.
    assert env.open(old_sealed, b"aad-hist") == b"historical"
    assert env.open(fresh_sealed, b"aad-current") == b"current"


def test_scenario_retired_key_blocks_decryption() -> None:
    """After a key_id is dropped, its envelopes are unopenable — CRY-INV-04."""
    vault = _fresh_vault()
    env = AeadEnvelope(vault)
    sealed = env.seal(b"legacy", aad=b"a")
    vault.register("k-prod-2", secrets.token_bytes(32))
    vault.set_active("k-prod-2")
    vault.drop("k-prod-1")
    with pytest.raises(CryptoEnvelopeError):
        env.open(sealed, b"a")


def test_scenario_tampered_ciphertext_fails_with_opaque_error() -> None:
    """CRY-INV-01: a bit flipped in ciphertext produces the SAME error class
    as a bad aad or unknown key — no oracle leakage to the attacker."""
    vault = _fresh_vault()
    env = AeadEnvelope(vault)
    sealed = env.seal(b"payload", b"aad")
    flipped = bytearray(sealed.ciphertext)
    flipped[0] ^= 0x01
    bad_ct = Envelope(
        key_id=sealed.key_id, nonce=sealed.nonce,
        ciphertext=bytes(flipped), aad=sealed.aad,
    )
    with pytest.raises(CryptoEnvelopeError) as e1:
        env.open(bad_ct, b"aad")
    with pytest.raises(CryptoEnvelopeError) as e2:
        env.open(sealed, b"different-aad")
    # Exception class is identical — oracle defense.
    assert type(e1.value) is type(e2.value)


def test_scenario_chacha20_parity_with_aesgcm() -> None:
    """Swapping AEAD algorithm via extension contract MUST remain invariant-safe."""
    vault = _fresh_vault(algorithm="ChaCha20-Poly1305")
    env = AeadEnvelope(vault, algorithm="ChaCha20-Poly1305")
    sealed = env.seal(b"stream-payload", b"aad-chacha")
    assert env.open(sealed, b"aad-chacha") == b"stream-payload"
    with pytest.raises(CryptoEnvelopeError):
        env.open(sealed, b"wrong-aad")


def test_scenario_nonce_is_non_deterministic_across_equal_plaintexts() -> None:
    """Two seal() calls with identical plaintext+aad MUST produce distinct
    ciphertexts because the nonce is CSPRNG-fresh — CRY-INV-02."""
    vault = _fresh_vault()
    env = AeadEnvelope(vault)
    a = env.seal(b"same", b"aad")
    b = env.seal(b"same", b"aad")
    assert a.nonce != b.nonce
    assert a.ciphertext != b.ciphertext
    # Both still decrypt correctly.
    assert env.open(a, b"aad") == b"same"
    assert env.open(b, b"aad") == b"same"
