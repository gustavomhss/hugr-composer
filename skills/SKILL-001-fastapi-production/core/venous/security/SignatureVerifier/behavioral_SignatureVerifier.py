"""Behavioral end-to-end scenarios for SignatureVerifier.

Each scenario exercises the Protocol surface through a realistic workflow
(JWT-style token, webhook, cross-signer verification, algorithm migration,
replay defense). The scenarios prove SIG invariants hold at runtime — not
just in unit fixtures.
"""

from __future__ import annotations

import pytest

from SignatureVerifier import (
    ALG_ECDSA_P256,
    ALG_ED25519,
    ALG_HMAC_SHA256,
    DetachedSigner,
    ReplayCache,
    SignatureVerifierError,
    TrustAnchor,
    generate_ecdsa_p256_keypair,
    generate_ed25519_keypair,
    generate_hmac_key,
)


def _multi_kid_anchor() -> TrustAnchor:
    anchor = TrustAnchor()
    sk_ed, pk_ed = generate_ed25519_keypair()
    anchor.register("api-edsig-2025", ALG_ED25519, public_key=pk_ed, private_key=sk_ed)
    sk_ec, pk_ec = generate_ecdsa_p256_keypair()
    anchor.register("api-ecdsa-2025", ALG_ECDSA_P256, public_key=pk_ec, private_key=sk_ec)
    shared = generate_hmac_key()
    anchor.register("internal-hmac-2025", ALG_HMAC_SHA256, public_key=shared, private_key=shared)
    return anchor


def test_scenario_issue_and_validate_webhook_signature() -> None:
    """A webhook sender signs the body; receiver validates under its pinned kid."""
    anchor = _multi_kid_anchor()
    sender = DetachedSigner(anchor, default_msg_type="webhook.v1")
    receiver = DetachedSigner(anchor, default_msg_type="webhook.v1")
    body = b'{"event":"payment.succeeded","id":"evt_123"}'
    sig = sender.sign(body, "api-edsig-2025")
    # Round-trip — receiver MUST accept the signature for the same payload.
    receiver.verify(body, sig, "api-edsig-2025")
    # Tampered body MUST be rejected.
    with pytest.raises(SignatureVerifierError):
        receiver.verify(body + b"!", sig, "api-edsig-2025")


def test_scenario_multiple_signers_pick_by_key_id() -> None:
    """An anchor carries several kids; sign() picks the right one."""
    anchor = _multi_kid_anchor()
    s = DetachedSigner(anchor, default_msg_type="generic")
    body = b"audit-log-line-17"
    sig_ed = s.sign(body, "api-edsig-2025")
    sig_ec = s.sign(body, "api-ecdsa-2025")
    sig_hm = s.sign(body, "internal-hmac-2025")
    # Each sig round-trips only under its own kid; cross-kid MUST fail.
    s.verify(body, sig_ed, "api-edsig-2025")
    s.verify(body, sig_ec, "api-ecdsa-2025")
    s.verify(body, sig_hm, "internal-hmac-2025")
    with pytest.raises(SignatureVerifierError):
        s.verify(body, sig_ed, "api-ecdsa-2025")
    with pytest.raises(SignatureVerifierError):
        s.verify(body, sig_hm, "api-edsig-2025")


def test_scenario_cross_message_type_replay_fails() -> None:
    """A signature issued under msg_type='login' MUST NOT verify as 'transfer'."""
    anchor = _multi_kid_anchor()
    s = DetachedSigner(anchor, default_msg_type="login")
    auth_body = b"user=alice;nonce=abc"
    sig = s.sign_typed(auth_body, "api-edsig-2025", msg_type="login")
    # Same bytes in a different message type MUST NOT verify — domain separation.
    with pytest.raises(SignatureVerifierError):
        s.verify_typed(auth_body, sig, "api-edsig-2025", msg_type="transfer")
    # But it DOES verify under the original type.
    s.verify_typed(auth_body, sig, "api-edsig-2025", msg_type="login")


def test_scenario_key_id_confusion_attack_fails() -> None:
    """Attacker swaps kid in an effort to verify under a different key.

    SIG-INV-04 — verify MUST raise because the framing authenticates kid.
    """
    anchor = _multi_kid_anchor()
    s = DetachedSigner(anchor, default_msg_type="generic")
    payload = b"refund=1000"
    sig_under_a = s.sign(payload, "api-edsig-2025")
    # Attacker attempts to claim this sig was issued under the HMAC kid.
    with pytest.raises(SignatureVerifierError):
        s.verify(payload, sig_under_a, "internal-hmac-2025")


def test_scenario_algorithm_migration_without_downtime() -> None:
    """Rotate from HMAC-SHA256 to Ed25519 via fresh kid; old kid keeps working
    until drained. The primitive supports long-overlap rotation windows."""
    anchor = TrustAnchor()
    hk = generate_hmac_key()
    anchor.register("sig-v1", ALG_HMAC_SHA256, public_key=hk, private_key=hk)
    sk, pk = generate_ed25519_keypair()
    anchor.register("sig-v2", ALG_ED25519, public_key=pk, private_key=sk)
    s = DetachedSigner(anchor, default_msg_type="api")
    old_sig = s.sign(b"msg", "sig-v1")
    new_sig = s.sign(b"msg", "sig-v2")
    # Both keep verifying during the rotation window.
    s.verify(b"msg", old_sig, "sig-v1")
    s.verify(b"msg", new_sig, "sig-v2")
    # Old sig under new kid fails.
    with pytest.raises(SignatureVerifierError):
        s.verify(b"msg", old_sig, "sig-v2")


def test_scenario_replay_defense_stops_double_spend() -> None:
    """Stateful verifier rejects replayed signatures in its window."""
    anchor = _multi_kid_anchor()
    replay = ReplayCache(window=16)
    s = DetachedSigner(anchor, default_msg_type="tx", replay_cache=replay)
    sig = s.sign(b"transfer:100->bob", "api-ecdsa-2025")
    s.verify(b"transfer:100->bob", sig, "api-ecdsa-2025")
    with pytest.raises(SignatureVerifierError):
        s.verify(b"transfer:100->bob", sig, "api-ecdsa-2025")


def test_scenario_verify_only_service_cannot_forge() -> None:
    """A downstream verifier receives only the public key; it MUST NOT sign."""
    sk, pk = generate_ed25519_keypair()
    # Writer anchor carries the private key.
    writer = TrustAnchor()
    writer.register("shared-kid", ALG_ED25519, public_key=pk, private_key=sk)
    writer_signer = DetachedSigner(writer, default_msg_type="pub")
    sig = writer_signer.sign(b"announcement", "shared-kid")
    # Reader anchor carries ONLY the public key.
    reader = TrustAnchor()
    reader.register("shared-kid", ALG_ED25519, public_key=pk, private_key=None)
    reader_signer = DetachedSigner(reader, default_msg_type="pub")
    reader_signer.verify(b"announcement", sig, "shared-kid")
    # Reader CANNOT sign — has no private key for the kid.
    with pytest.raises(SignatureVerifierError):
        reader_signer.sign(b"forged-announcement", "shared-kid")


def test_scenario_bit_flipped_signature_fails_with_same_error() -> None:
    """Bit flips in the signature all collapse to SignatureVerifierError."""
    anchor = _multi_kid_anchor()
    s = DetachedSigner(anchor, default_msg_type="generic")
    sig = s.sign(b"payload", "api-edsig-2025")
    for i in range(0, len(sig), 8):
        flipped = bytearray(sig)
        flipped[i] ^= 0x01
        with pytest.raises(SignatureVerifierError):
            s.verify(b"payload", bytes(flipped), "api-edsig-2025")
