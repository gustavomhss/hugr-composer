"""Metamorphic + differential tests for CryptoEnvelope.

Algebraic laws validated:

- seal_then_open: open(seal(pt, aad), aad) == pt for every pt, aad.
- non_determinism: seal(pt, aad) never returns the same nonce twice.
- bit_flip_invalidates: flipping any bit in ciphertext, nonce, or aad breaks open.
- differential_aesgcm_chacha20: both AEADs honor the same Protocol surface and
  round-trip cleanly.
- rotation_idempotence: re-sealing a plaintext under a new key and then
  swapping back still round-trips under the original key.
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


def _env(algorithm: str = "AES-GCM") -> AeadEnvelope:
    v = InMemoryKeyVault()
    v.register("k1", secrets.token_bytes(32), algorithm=algorithm)
    return AeadEnvelope(v, algorithm=algorithm)


def test_metamorphic_seal_then_open_aesgcm() -> None:
    env = _env()
    for pt in (b"", b"x", b"short", b"A" * 1024, secrets.token_bytes(8192)):
        sealed = env.seal(pt, b"aad")
        assert env.open(sealed, b"aad") == pt


def test_metamorphic_seal_then_open_chacha20() -> None:
    env = _env(algorithm="ChaCha20-Poly1305")
    for pt in (b"", b"x", b"\x00\x01\x02", b"B" * 4096):
        sealed = env.seal(pt, b"aad")
        assert env.open(sealed, b"aad") == pt


def test_metamorphic_nonce_never_repeats() -> None:
    env = _env()
    outs = {env.seal(b"same", b"aad").nonce for _ in range(128)}
    assert len(outs) == 128


def test_metamorphic_bit_flip_in_ciphertext_invalidates() -> None:
    env = _env()
    sealed = env.seal(b"payload", b"aad")
    for i in range(0, len(sealed.ciphertext), max(1, len(sealed.ciphertext) // 8)):
        flipped = bytearray(sealed.ciphertext)
        flipped[i] ^= 0x01
        bad = Envelope(
            key_id=sealed.key_id, nonce=sealed.nonce,
            ciphertext=bytes(flipped), aad=sealed.aad,
        )
        with pytest.raises(CryptoEnvelopeError):
            env.open(bad, b"aad")


def test_metamorphic_bit_flip_in_nonce_invalidates() -> None:
    env = _env()
    sealed = env.seal(b"payload", b"aad")
    flipped_nonce = bytearray(sealed.nonce)
    flipped_nonce[0] ^= 0x01
    bad = Envelope(
        key_id=sealed.key_id, nonce=bytes(flipped_nonce),
        ciphertext=sealed.ciphertext, aad=sealed.aad,
    )
    with pytest.raises(CryptoEnvelopeError):
        env.open(bad, b"aad")


def test_differential_aesgcm_chacha20_protocol_parity() -> None:
    aes = _env("AES-GCM")
    chacha = _env("ChaCha20-Poly1305")
    for pt in (b"a", b"bb", b"three word pass"):
        s_aes = aes.seal(pt, b"aad")
        s_cha = chacha.seal(pt, b"aad")
        assert aes.open(s_aes, b"aad") == pt
        assert chacha.open(s_cha, b"aad") == pt
        # Cross-verify MUST fail — envelopes are algorithm-bound via the vault's key record.
        # (Different vaults / different key material → open is guaranteed to fail.)
        with pytest.raises(CryptoEnvelopeError):
            aes.open(s_cha, b"aad")


def test_metamorphic_rotation_idempotence() -> None:
    v = InMemoryKeyVault()
    v.register("k1", secrets.token_bytes(32))
    env = AeadEnvelope(v)

    sealed_under_k1 = env.seal(b"msg", b"aad")
    # Rotate.
    v.register("k2", secrets.token_bytes(32))
    v.set_active("k2")
    sealed_under_k2 = env.seal(b"msg", b"aad")
    # Rotate back to k1.
    v.set_active("k1")
    sealed_under_k1_again = env.seal(b"msg", b"aad")

    # All three ciphertexts open, each carrying its correct key_id.
    assert env.open(sealed_under_k1, b"aad") == b"msg"
    assert env.open(sealed_under_k2, b"aad") == b"msg"
    assert env.open(sealed_under_k1_again, b"aad") == b"msg"
    assert sealed_under_k1.key_id == "k1"
    assert sealed_under_k2.key_id == "k2"
    assert sealed_under_k1_again.key_id == "k1"


def test_metamorphic_aad_is_authenticated_not_confidential() -> None:
    # AAD is visible in the envelope (no confidentiality claim) but mutating it
    # MUST break open — metamorphic: identity under match, failure under mutation.
    env = _env()
    for aad in (b"", b"a", b"record_id=7", b"\x00\x01"):
        sealed = env.seal(b"pt", aad)
        assert env.open(sealed, aad) == b"pt"
        mutated = aad + b"!"
        forged = Envelope(
            key_id=sealed.key_id, nonce=sealed.nonce,
            ciphertext=sealed.ciphertext, aad=mutated,
        )
        with pytest.raises(CryptoEnvelopeError):
            env.open(forged, mutated)
