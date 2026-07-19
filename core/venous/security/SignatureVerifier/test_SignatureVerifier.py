"""Unit tests for SignatureVerifier — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import time

import pytest
from SignatureVerifier import (
    ALG_ECDSA_P256,
    ALG_ED25519,
    ALG_HMAC_SHA256,
    FORBIDDEN_ALGORITHMS,
    DetachedSigner,
    ReplayCache,
    SignatureVerifierError,
    TrustAnchor,
    frame_message,
    generate_ecdsa_p256_keypair,
    generate_ed25519_keypair,
    generate_hmac_key,
    register_adapter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _anchor_with_all_algorithms() -> TrustAnchor:
    anchor = TrustAnchor()
    sk_ed, pk_ed = generate_ed25519_keypair()
    anchor.register("ed-k1", ALG_ED25519, public_key=pk_ed, private_key=sk_ed)
    sk_ec, pk_ec = generate_ecdsa_p256_keypair()
    anchor.register("ec-k1", ALG_ECDSA_P256, public_key=pk_ec, private_key=sk_ec)
    hk = generate_hmac_key()
    anchor.register("hm-k1", ALG_HMAC_SHA256, public_key=hk, private_key=hk)
    return anchor


def _signer() -> DetachedSigner:
    return DetachedSigner(_anchor_with_all_algorithms(), default_msg_type="unit")


# ---------------------------------------------------------------------------
# SIG_INV_01 — verify() MUST raise on mismatch (never return bool)
# ---------------------------------------------------------------------------
def test_inv_raise_on_mismatch_confirms() -> None:
    s = _signer()
    for kid in ("ed-k1", "ec-k1", "hm-k1"):
        sig = s.sign(b"hello", kid)
        # Legit verify returns None (raise-or-None contract).
        assert s.verify(b"hello", sig, kid) is None


def test_inv_raise_on_mismatch_prevents() -> None:
    s = _signer()
    sig = s.sign(b"hello", "ed-k1")
    # Mutated message MUST raise — never return False or None silently.
    with pytest.raises(SignatureVerifierError):
        s.verify(b"hellp", sig, "ed-k1")
    # Mutated signature MUST raise.
    tampered = bytearray(sig)
    tampered[0] ^= 0x01
    with pytest.raises(SignatureVerifierError):
        s.verify(b"hello", bytes(tampered), "ed-k1")
    # Empty signature rejected.
    with pytest.raises(SignatureVerifierError):
        s.verify(b"hello", b"", "ed-k1")


def test_inv_raise_on_mismatch_under_failure() -> None:
    s = _signer()
    # HMAC branch — flipping the last byte of the tag MUST raise.
    sig = s.sign(b"payload", "hm-k1")
    flipped = bytearray(sig)
    flipped[-1] ^= 0xFF
    with pytest.raises(SignatureVerifierError):
        s.verify(b"payload", bytes(flipped), "hm-k1")
    # ECDSA branch — random 64 zero bytes is NOT a valid signature.
    with pytest.raises(SignatureVerifierError):
        s.verify(b"payload", b"\x00" * 64, "ec-k1")


# ---------------------------------------------------------------------------
# SIG_INV_02 — algorithm bound to key_id; no algorithm confusion
# ---------------------------------------------------------------------------
def test_inv_algorithm_binding_confirms() -> None:
    anchor = _anchor_with_all_algorithms()
    # Each key_id exposes exactly one algorithm (look up by inspecting the
    # registered record via `resolve`).
    assert anchor.resolve("ed-k1").algorithm == ALG_ED25519
    assert anchor.resolve("ec-k1").algorithm == ALG_ECDSA_P256
    assert anchor.resolve("hm-k1").algorithm == ALG_HMAC_SHA256


def test_inv_algorithm_binding_prevents() -> None:
    # FORBIDDEN algorithms MUST NEVER register.
    anchor = TrustAnchor()
    for bad in FORBIDDEN_ALGORITHMS:
        with pytest.raises(SignatureVerifierError):
            anchor.register("x", bad, public_key=b"\x00" * 32)
    # register_adapter() also refuses.
    for bad in FORBIDDEN_ALGORITHMS:
        with pytest.raises(SignatureVerifierError):
            register_adapter(bad)
    # Rebinding a key_id to a second algorithm is rejected.
    anchor2 = TrustAnchor()
    hk = generate_hmac_key()
    anchor2.register("k1", ALG_HMAC_SHA256, public_key=hk, private_key=hk)
    with pytest.raises(SignatureVerifierError):
        anchor2.register("k1", ALG_ED25519, public_key=b"\x00" * 32)


def test_inv_algorithm_binding_under_failure() -> None:
    # Cross-algorithm forgery: sign with HMAC under kid-A, then attempt to
    # verify as if it belonged to kid-B bound to Ed25519. MUST raise rather
    # than accept an HMAC tag on the Ed25519 code path.
    s = _signer()
    hmac_sig = s.sign(b"msg", "hm-k1")
    with pytest.raises(SignatureVerifierError):
        s.verify(b"msg", hmac_sig, "ed-k1")
    # Ed25519 signature is 64 bytes but is not a valid ECDSA signature under
    # the ECDSA key — verify MUST raise.
    ed_sig = s.sign(b"msg", "ed-k1")
    with pytest.raises(SignatureVerifierError):
        s.verify(b"msg", ed_sig, "ec-k1")


# ---------------------------------------------------------------------------
# SIG_INV_03 — deterministic signing OR CSPRNG nonce; ECDSA nonce reuse CANNOT occur
# ---------------------------------------------------------------------------
def test_inv_deterministic_or_csprng_nonce_confirms() -> None:
    s = _signer()
    # Ed25519 is deterministic — same (key, message) MUST produce identical sigs.
    a = s.sign(b"msg", "ed-k1")
    b = s.sign(b"msg", "ed-k1")
    assert a == b
    # HMAC is deterministic by construction.
    a2 = s.sign(b"msg", "hm-k1")
    b2 = s.sign(b"msg", "hm-k1")
    assert a2 == b2


def test_inv_deterministic_or_csprng_nonce_prevents() -> None:
    # HMAC key below the stdlib strength floor MUST be refused.
    with pytest.raises(SignatureVerifierError):
        generate_hmac_key(nbytes=16)


def test_inv_deterministic_or_csprng_nonce_under_failure() -> None:
    # ECDSA with RFC 6979: two signatures over the same message are both
    # valid even though they may differ by backend implementation details;
    # both MUST verify round-trip. (Deterministic nonce means no RNG failure
    # can cause nonce reuse.)
    s = _signer()
    for _ in range(4):
        sig = s.sign(b"ecdsa-check", "ec-k1")
        assert len(sig) == 64
        s.verify(b"ecdsa-check", sig, "ec-k1")


# ---------------------------------------------------------------------------
# SIG_INV_04 — public keys from pinned trust anchor; cannot be learned from msg
# ---------------------------------------------------------------------------
def test_inv_pinned_trust_anchor_confirms() -> None:
    anchor = _anchor_with_all_algorithms()
    known = anchor.known_key_ids()
    assert {"ed-k1", "ec-k1", "hm-k1"} <= known


def test_inv_pinned_trust_anchor_prevents() -> None:
    anchor = TrustAnchor()
    with pytest.raises(SignatureVerifierError):
        anchor.resolve("never-registered")
    # Empty / wrong-type key_ids rejected up-front.
    for bad in ("", None, 42):
        with pytest.raises(SignatureVerifierError):
            anchor.resolve(bad)  # type: ignore[arg-type]


def test_inv_pinned_trust_anchor_under_failure() -> None:
    # Forge a verify call under a key_id that does not exist — MUST raise,
    # not silently fetch a public key from the caller's payload.
    s = _signer()
    sig = s.sign(b"m", "ed-k1")
    with pytest.raises(SignatureVerifierError):
        s.verify(b"m", sig, "ghost-key")


# ---------------------------------------------------------------------------
# SIG_INV_05 — constant-time compare on verify
# ---------------------------------------------------------------------------
def test_inv_constant_time_compare_confirms() -> None:
    # Probe the HMAC path for timing independence: forged signatures that
    # match the first byte vs. not MUST not diverge in wall time in a way
    # that is statistically measurable at this test's scale. We assert the
    # weaker runtime property: `hmac.compare_digest` is used (observable via
    # the fact that a 1-byte-matching forgery and a 0-byte-matching forgery
    # take the same order-of-magnitude time).
    s = _signer()
    real = s.sign(b"payload", "hm-k1")
    forgery_matching = bytearray(real)
    forgery_matching[-1] ^= 0x01  # all but 1 byte match
    forgery_diff = b"\x00" * len(real)  # nothing matches

    def _time(sig: bytes) -> float:
        t0 = time.perf_counter()
        for _ in range(200):
            try:
                s.verify(b"payload", sig, "hm-k1")
            except SignatureVerifierError:
                pass
        return time.perf_counter() - t0

    t_match = _time(bytes(forgery_matching))
    t_diff = _time(forgery_diff)
    # Both should be comparable to within 10x — constant-time compare avoids
    # byte-by-byte short-circuit divergence. This is a weak check by design;
    # stronger stats live in chaos_SignatureVerifier.py.
    assert 0.1 < (t_match / max(t_diff, 1e-9)) < 10.0


def test_inv_constant_time_compare_prevents() -> None:
    # The impl MUST route HMAC verify through `hmac.compare_digest`. A non-
    # constant-time Python `==` path would short-circuit on the first
    # mismatching byte — we sanity-check by ensuring distinct forgeries all
    # raise the SAME error class, giving attackers no type-based oracle.
    s = _signer()
    forgeries = [b"\x00" * 32, b"\xff" * 32, b"A" * 32]
    errors: list[type[BaseException]] = []
    for f in forgeries:
        try:
            s.verify(b"m", f, "hm-k1")
        except SignatureVerifierError as e:
            errors.append(type(e))
    assert len(errors) == len(forgeries)
    assert len(set(errors)) == 1


def test_inv_constant_time_compare_under_failure() -> None:
    # Replay cache path: a correct signature replayed raises the SAME error
    # class (SignatureVerifierError) as a bad-tag failure, so an attacker
    # cannot tell "signature valid but replayed" from "signature invalid" by
    # exception type.
    anchor = TrustAnchor()
    hk = generate_hmac_key()
    anchor.register("k1", ALG_HMAC_SHA256, public_key=hk, private_key=hk)
    replay = ReplayCache(window=4)
    s = DetachedSigner(anchor, default_msg_type="unit", replay_cache=replay)
    sig = s.sign(b"m", "k1")
    s.verify(b"m", sig, "k1")  # first time OK
    with pytest.raises(SignatureVerifierError):
        s.verify(b"m", sig, "k1")  # replay — same error class
    with pytest.raises(SignatureVerifierError):
        s.verify(b"m", b"\x00" * 32, "k1")  # bad tag — same error class


# ---------------------------------------------------------------------------
# Sanity / framing
# ---------------------------------------------------------------------------
def test_framing_domain_separation_across_msg_types() -> None:
    # The same raw bytes framed under two different msg_types MUST produce
    # different framed bytes. Equality collision is impossible by construction
    # (length-prefix encoding) so the signature under one msg_type CANNOT
    # verify under another.
    a = frame_message(b"body", key_id="k1", msg_type="login")
    b = frame_message(b"body", key_id="k1", msg_type="transfer")
    assert a != b


def test_framing_domain_separation_across_key_ids() -> None:
    a = frame_message(b"body", key_id="k1", msg_type="t")
    b = frame_message(b"body", key_id="k2", msg_type="t")
    assert a != b


def test_sign_requires_private_key_material() -> None:
    # verify-only record: register with public_key but no private_key.
    anchor = TrustAnchor()
    _, pk = generate_ed25519_keypair()
    anchor.register("verify-only", ALG_ED25519, public_key=pk, private_key=None)
    s = DetachedSigner(anchor, default_msg_type="unit")
    with pytest.raises(SignatureVerifierError):
        s.sign(b"m", "verify-only")


def test_protocol_runtime_checkable() -> None:
    from SignatureVerifier import SignatureVerifier as ProtoCls

    s = _signer()
    assert isinstance(s, ProtoCls)
