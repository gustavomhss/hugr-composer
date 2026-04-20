"""Metamorphic + differential tests for SignatureVerifier.

Algebraic laws validated:

- sign_then_verify: verify(sign(m, kid), kid) returns None for all m, kid.
- determinism_ed25519_hmac: sign(m, kid) == sign(m, kid) for the deterministic
  algorithms (Ed25519 per RFC 8032, HMAC-SHA256 by construction).
- bit_flip_invalidates: flipping any bit in signature MUST break verify.
- differential_algorithm_parity: all three adapters honor the same Protocol
  surface and round-trip cleanly, but their signatures are NOT interchangeable.
- rotation_idempotence: adding a second kid does not change behavior under
  the first kid.
"""

from __future__ import annotations

import pytest

from SignatureVerifier import (
    ALG_ECDSA_P256,
    ALG_ED25519,
    ALG_HMAC_SHA256,
    DetachedSigner,
    SignatureVerifierError,
    TrustAnchor,
    frame_message,
    generate_ecdsa_p256_keypair,
    generate_ed25519_keypair,
    generate_hmac_key,
)


def _mk(algorithm: str) -> DetachedSigner:
    anchor = TrustAnchor()
    if algorithm == ALG_ED25519:
        sk, pk = generate_ed25519_keypair()
        anchor.register("k1", algorithm, public_key=pk, private_key=sk)
    elif algorithm == ALG_ECDSA_P256:
        sk, pk = generate_ecdsa_p256_keypair()
        anchor.register("k1", algorithm, public_key=pk, private_key=sk)
    else:
        hk = generate_hmac_key()
        anchor.register("k1", algorithm, public_key=hk, private_key=hk)
    return DetachedSigner(anchor, default_msg_type="meta")


def test_metamorphic_sign_then_verify_ed25519() -> None:
    s = _mk(ALG_ED25519)
    for m in (b"", b"x", b"short", b"A" * 1024, b"B" * 8192):
        sig = s.sign(m, "k1")
        s.verify(m, sig, "k1")


def test_metamorphic_sign_then_verify_ecdsa() -> None:
    s = _mk(ALG_ECDSA_P256)
    for m in (b"", b"x", b"\x00\x01\x02", b"B" * 4096):
        sig = s.sign(m, "k1")
        s.verify(m, sig, "k1")


def test_metamorphic_sign_then_verify_hmac() -> None:
    s = _mk(ALG_HMAC_SHA256)
    for m in (b"", b"x", b"byte", b"c" * 2048):
        sig = s.sign(m, "k1")
        s.verify(m, sig, "k1")


def test_metamorphic_determinism_ed25519() -> None:
    s = _mk(ALG_ED25519)
    sigs = {s.sign(b"same-msg", "k1") for _ in range(32)}
    assert len(sigs) == 1


def test_metamorphic_determinism_hmac() -> None:
    s = _mk(ALG_HMAC_SHA256)
    sigs = {s.sign(b"same-msg", "k1") for _ in range(32)}
    assert len(sigs) == 1


def test_metamorphic_bit_flip_invalidates_ed25519() -> None:
    s = _mk(ALG_ED25519)
    sig = s.sign(b"payload", "k1")
    for i in range(0, len(sig), max(1, len(sig) // 8)):
        flipped = bytearray(sig)
        flipped[i] ^= 0x01
        with pytest.raises(SignatureVerifierError):
            s.verify(b"payload", bytes(flipped), "k1")


def test_differential_all_algorithms_round_trip() -> None:
    for algorithm in (ALG_ED25519, ALG_ECDSA_P256, ALG_HMAC_SHA256):
        s = _mk(algorithm)
        sig = s.sign(b"diff", "k1")
        s.verify(b"diff", sig, "k1")


def test_differential_signatures_not_interchangeable() -> None:
    # A signature produced under one algorithm CANNOT verify under another,
    # even for the same (message, kid) — different anchors, different keys.
    s_ed = _mk(ALG_ED25519)
    s_hm = _mk(ALG_HMAC_SHA256)
    sig_ed = s_ed.sign(b"msg", "k1")
    with pytest.raises(SignatureVerifierError):
        s_hm.verify(b"msg", sig_ed, "k1")


def test_metamorphic_framing_identity() -> None:
    # The framing function is purely algebraic: same inputs MUST produce
    # identical bytes, and any field mutation MUST change the output.
    a = frame_message(b"body", key_id="k1", msg_type="t1")
    b = frame_message(b"body", key_id="k1", msg_type="t1")
    assert a == b
    assert a != frame_message(b"body!", key_id="k1", msg_type="t1")
    assert a != frame_message(b"body", key_id="k2", msg_type="t1")
    assert a != frame_message(b"body", key_id="k1", msg_type="t2")


def test_metamorphic_rotation_idempotence() -> None:
    # Adding a second kid MUST NOT change behavior under the first kid.
    anchor = TrustAnchor()
    sk1, pk1 = generate_ed25519_keypair()
    anchor.register("k1", ALG_ED25519, public_key=pk1, private_key=sk1)
    s = DetachedSigner(anchor, default_msg_type="rot")
    sig_before = s.sign(b"msg", "k1")
    # Rotation: add k2.
    sk2, pk2 = generate_ed25519_keypair()
    anchor.register("k2", ALG_ED25519, public_key=pk2, private_key=sk2)
    sig_after = s.sign(b"msg", "k1")
    # Ed25519 is deterministic — same sig before and after rotation.
    assert sig_before == sig_after
    # k2 produces a DIFFERENT signature for the same message.
    sig_k2 = s.sign(b"msg", "k2")
    assert sig_k2 != sig_before
