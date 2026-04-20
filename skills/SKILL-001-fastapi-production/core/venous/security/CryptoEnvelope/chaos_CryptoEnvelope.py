"""Chaos / fault-injection tests for CryptoEnvelope.

Game-day scenarios: adversarial ciphertext, downgrade attempts, type confusion,
key deletion races, oversized input, Unicode aad, reused nonce injection, and
concurrent seal under rotation. The primitive MUST remain correct under each
and MUST NEVER leak plaintext or partial buffers.
"""

from __future__ import annotations

import secrets
import threading

import pytest

from CryptoEnvelope import (
    FORBIDDEN_ALGORITHMS,
    AeadEnvelope,
    CryptoEnvelopeError,
    Envelope,
    InMemoryKeyVault,
    register_adapter,
)


def _vault() -> InMemoryKeyVault:
    v = InMemoryKeyVault()
    v.register("k1", secrets.token_bytes(32))
    return v


def _env() -> AeadEnvelope:
    return AeadEnvelope(_vault())


def test_chaos_forbidden_algorithms_refused_at_registration() -> None:
    for bad in FORBIDDEN_ALGORITHMS:
        with pytest.raises(CryptoEnvelopeError):
            register_adapter(bad)
    # Unknown algorithm name also refused.
    for bad in ("ROT13", "aes-gcm", "", "AES-GCM\x00"):
        with pytest.raises(CryptoEnvelopeError):
            register_adapter(bad)


def test_chaos_downgrade_via_key_algorithm_mismatch() -> None:
    v = InMemoryKeyVault()
    v.register("k1", secrets.token_bytes(32), algorithm="ChaCha20-Poly1305")
    # Envelope configured for AES-GCM but vault's active key is ChaCha20 —
    # seal MUST raise (CRY-INV-04) rather than use the wrong cipher.
    env = AeadEnvelope(v, algorithm="AES-GCM")
    with pytest.raises(CryptoEnvelopeError):
        env.seal(b"x", b"a")


def test_chaos_wrong_key_size_refused() -> None:
    v = InMemoryKeyVault()
    for bad_len in (0, 1, 15, 17, 31, 33, 64):
        with pytest.raises(CryptoEnvelopeError):
            v.register(f"k-{bad_len}", secrets.token_bytes(bad_len))
    with pytest.raises(CryptoEnvelopeError):
        v.register("k-cc-bad", secrets.token_bytes(16), algorithm="ChaCha20-Poly1305")


def test_chaos_type_confusion_rejected() -> None:
    env = _env()
    for bad in (None, 42, 3.14, "string-not-bytes", [], {}):
        with pytest.raises(CryptoEnvelopeError):
            env.seal(bad, b"aad")  # type: ignore[arg-type]
        with pytest.raises(CryptoEnvelopeError):
            env.seal(b"pt", bad)  # type: ignore[arg-type]


def test_chaos_open_with_wrong_envelope_type_refused() -> None:
    env = _env()
    for bad in ("not-an-envelope", 42, None, {"key_id": "k1"}):
        with pytest.raises(CryptoEnvelopeError):
            env.open(bad, b"aad")  # type: ignore[arg-type]


def test_chaos_nonce_reuse_injection_detected() -> None:
    env = _env()
    sealed = env.seal(b"x", b"a")
    # Simulated fault: rng bug replays the same nonce under the same key. The
    # tracker MUST flag it immediately.
    with pytest.raises(CryptoEnvelopeError):
        env._nonces.check_and_record(sealed.key_id, sealed.nonce)  # noqa: SLF001 — CRY-INV-02: chaos harness probes tracker to simulate a buggy RNG.


def test_chaos_oversized_aad_still_round_trips() -> None:
    env = _env()
    big_aad = secrets.token_bytes(64 * 1024)
    sealed = env.seal(b"pt", big_aad)
    assert env.open(sealed, big_aad) == b"pt"


def test_chaos_unicode_aad_authenticated_verbatim() -> None:
    env = _env()
    aad = "record=🔐-ünïcôdé".encode()
    sealed = env.seal(b"pt", aad)
    assert env.open(sealed, aad) == b"pt"
    # Any mutation of the encoded aad breaks open.
    with pytest.raises(CryptoEnvelopeError):
        env.open(sealed, aad + b"?")


def test_chaos_concurrent_seal_no_corruption() -> None:
    env = _env()
    errors: list[BaseException] = []
    results: list[Envelope] = []
    lock = threading.Lock()

    def worker(tag: bytes) -> None:
        try:
            for _ in range(8):
                s = env.seal(tag, b"a")
                assert env.open(s, b"a") == tag
                with lock:
                    results.append(s)
        except BaseException as exc:  # noqa: BLE001 — CRY-INV-02: chaos harness records ANY thread failure so the test fails clearly rather than silently passing.
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"tag-{i}".encode(),)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Every nonce across all threads is unique.
    assert len({r.nonce for r in results}) == len(results)


def test_chaos_key_dropped_mid_flight_produces_error_not_garbage() -> None:
    v = InMemoryKeyVault()
    v.register("k1", secrets.token_bytes(32))
    env = AeadEnvelope(v)
    sealed = env.seal(b"pt", b"a")
    # Rotate and drop k1.
    v.register("k2", secrets.token_bytes(32))
    v.set_active("k2")
    v.drop("k1")
    with pytest.raises(CryptoEnvelopeError):
        env.open(sealed, b"a")


def test_chaos_truncated_ciphertext_refused() -> None:
    env = _env()
    sealed = env.seal(b"pt", b"a")
    for cut in (0, 1, 4, 15):
        short = Envelope(
            key_id=sealed.key_id, nonce=sealed.nonce,
            ciphertext=sealed.ciphertext[:cut], aad=sealed.aad,
        )
        with pytest.raises(CryptoEnvelopeError):
            env.open(short, b"a")


def test_chaos_empty_active_vault_refuses_seal() -> None:
    v = InMemoryKeyVault()
    env = AeadEnvelope(v)
    with pytest.raises(CryptoEnvelopeError):
        env.seal(b"pt", b"a")
