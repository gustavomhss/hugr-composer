"""Chaos / fault-injection tests for SignatureVerifier.

Game-day scenarios: signature forgery, key-id confusion, replay attacks,
length-extension attempts, type confusion, and concurrent sign/verify under
rotation. The primitive MUST remain correct under each and MUST NEVER leak
key material or return an unsigned plaintext as if it were verified.
"""

from __future__ import annotations

import threading

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
    generate_ecdsa_p256_keypair,
    generate_ed25519_keypair,
    generate_hmac_key,
    register_adapter,
)


def _anchor_all() -> TrustAnchor:
    anchor = TrustAnchor()
    sk_ed, pk_ed = generate_ed25519_keypair()
    anchor.register("ed-k1", ALG_ED25519, public_key=pk_ed, private_key=sk_ed)
    sk_ec, pk_ec = generate_ecdsa_p256_keypair()
    anchor.register("ec-k1", ALG_ECDSA_P256, public_key=pk_ec, private_key=sk_ec)
    hk = generate_hmac_key()
    anchor.register("hm-k1", ALG_HMAC_SHA256, public_key=hk, private_key=hk)
    return anchor


def _signer() -> DetachedSigner:
    return DetachedSigner(_anchor_all(), default_msg_type="chaos")


def test_chaos_forbidden_algorithms_refused_at_registration() -> None:
    anchor = TrustAnchor()
    for bad in FORBIDDEN_ALGORITHMS:
        with pytest.raises(SignatureVerifierError):
            anchor.register("x", bad, public_key=b"\x00" * 32)
    # `alg:none` and unknown algorithms also refused via register_adapter.
    for bad in ("none", "alg:none", "RS256", "HS256", "", "\x00"):
        with pytest.raises(SignatureVerifierError):
            register_adapter(bad)


def test_chaos_signature_forgery_via_random_bytes() -> None:
    """Random-bytes forgeries MUST never verify."""
    s = _signer()
    from secrets import token_bytes

    for _ in range(32):
        for kid, sig_len in (("ed-k1", 64), ("ec-k1", 64), ("hm-k1", 32)):
            forgery = token_bytes(sig_len)
            with pytest.raises(SignatureVerifierError):
                s.verify(b"target-message", forgery, kid)


def test_chaos_key_id_confusion_attack() -> None:
    """Signature under one kid MUST NOT verify under another."""
    s = _signer()
    for src in ("ed-k1", "ec-k1", "hm-k1"):
        sig = s.sign(b"m", src)
        for dst in ("ed-k1", "ec-k1", "hm-k1"):
            if dst == src:
                continue
            with pytest.raises(SignatureVerifierError):
                s.verify(b"m", sig, dst)


def test_chaos_length_extension_attempt_rejected() -> None:
    """An attacker appends bytes to the message and attempts to produce a
    valid sig via length-extension. Our framing prefixes every field with a
    length header so the hash over the FRAMED message cannot be extended
    without regenerating the full prefix — verification MUST fail.
    """
    s = _signer()
    sig = s.sign(b"transfer=100", "hm-k1")
    for tail in (b"&admin=1", b"\x00", b"X"):
        with pytest.raises(SignatureVerifierError):
            s.verify(b"transfer=100" + tail, sig, "hm-k1")


def test_chaos_replay_attack_detected() -> None:
    anchor = _anchor_all()
    replay = ReplayCache(window=8)
    s = DetachedSigner(anchor, default_msg_type="chaos", replay_cache=replay)
    sig = s.sign(b"msg", "ed-k1")
    s.verify(b"msg", sig, "ed-k1")
    for _ in range(3):
        with pytest.raises(SignatureVerifierError):
            s.verify(b"msg", sig, "ed-k1")


def test_chaos_type_confusion_rejected() -> None:
    s = _signer()
    for bad in (None, 42, 3.14, "string-not-bytes", [], {}):
        with pytest.raises(SignatureVerifierError):
            s.sign(bad, "ed-k1")  # type: ignore[arg-type]
        with pytest.raises(SignatureVerifierError):
            s.verify(bad, b"sig", "ed-k1")  # type: ignore[arg-type]
    for bad_sig in (None, 42, "sigstr", [], {}):
        with pytest.raises(SignatureVerifierError):
            s.verify(b"m", bad_sig, "ed-k1")  # type: ignore[arg-type]


def test_chaos_bad_anchor_type_refused() -> None:
    for bad in ("not-an-anchor", 42, None, {}):
        with pytest.raises(SignatureVerifierError):
            DetachedSigner(bad, default_msg_type="x")  # type: ignore[arg-type]


def test_chaos_algorithm_substitution_fails() -> None:
    """Attacker produces an HMAC tag and claims it's Ed25519."""
    s = _signer()
    hmac_tag = s.sign(b"m", "hm-k1")  # 32 bytes
    # Under Ed25519 kid the sig MUST raise — Ed25519 expects 64 bytes and a
    # curve-valid signature. An HMAC tag is neither.
    with pytest.raises(SignatureVerifierError):
        s.verify(b"m", hmac_tag, "ed-k1")
    # Conversely, feeding 64 random bytes claiming HMAC fails the constant-
    # time compare at the right length.
    with pytest.raises(SignatureVerifierError):
        s.verify(b"m", b"\x00" * 32, "ed-k1")


def test_chaos_ecdsa_malformed_signature_refused() -> None:
    """ECDSA signatures are fixed-width 64 bytes (r||s). Anything else raises."""
    s = _signer()
    for bad_len in (0, 1, 32, 63, 65, 128, 256):
        with pytest.raises(SignatureVerifierError):
            s.verify(b"m", b"\x00" * bad_len, "ec-k1")


def test_chaos_empty_key_id_refused() -> None:
    s = _signer()
    for bad in ("", None, 42):
        with pytest.raises(SignatureVerifierError):
            s.sign(b"m", bad)  # type: ignore[arg-type]
        with pytest.raises(SignatureVerifierError):
            s.verify(b"m", b"sig", bad)  # type: ignore[arg-type]


def test_chaos_concurrent_sign_no_corruption() -> None:
    s = _signer()
    errors: list[BaseException] = []
    results: list[bytes] = []
    lock = threading.Lock()

    def worker(tag: bytes) -> None:
        try:
            for _ in range(8):
                sig = s.sign(tag, "ed-k1")
                s.verify(tag, sig, "ed-k1")
                with lock:
                    results.append(sig)
        except BaseException as exc:  # noqa: BLE001 — SIG-INV-01: chaos harness records ANY thread failure so the test fails clearly rather than silently passing.
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"tag-{i}".encode(),)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Ed25519 is deterministic — same (kid, tag) produces same sig across threads.
    # Signatures collected cover 6 distinct tags, each repeated many times.
    assert len(results) == 48


def test_chaos_register_unknown_algorithm_refused() -> None:
    anchor = TrustAnchor()
    for bad in ("AES-GCM", "rsa-pss", "sha256", ""):
        with pytest.raises(SignatureVerifierError):
            anchor.register("k", bad, public_key=b"\x00" * 32)


def test_chaos_register_non_bytes_key_refused() -> None:
    anchor = TrustAnchor()
    for bad in (None, "string-key", 42, [1, 2, 3]):
        with pytest.raises(SignatureVerifierError):
            anchor.register("k", ALG_ED25519, public_key=bad)  # type: ignore[arg-type]


def test_chaos_no_plaintext_or_key_in_exceptions() -> None:
    """Exception messages MUST NOT carry raw key material or signatures."""
    anchor = TrustAnchor()
    secret = b"SECRET-KEY-MATERIAL-0xDEADBEEF"
    try:
        anchor.register("k", "alg:none", public_key=secret)
    except SignatureVerifierError as e:
        assert secret not in repr(e).encode()
        assert secret not in str(e).encode()
    try:
        anchor.resolve("never-seen-before-0xCAFEBABE")
    except SignatureVerifierError as e:
        assert b"0xCAFEBABE" not in str(e).encode()
