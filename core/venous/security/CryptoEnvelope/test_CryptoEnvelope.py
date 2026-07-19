"""Unit tests for CryptoEnvelope — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import secrets
import threading

import pytest
from CryptoEnvelope import (
    AEAD_TAG_BYTES,
    AES_GCM_NONCE_BYTES,
    FORBIDDEN_ALGORITHMS,
    AeadEnvelope,
    CryptoEnvelopeError,
    Envelope,
    InMemoryKeyVault,
    register_adapter,
)


def _vault_with_key(
    key_id: str = "k1",
    algorithm: str = "AES-GCM",
    key_bytes: int = 32,
) -> InMemoryKeyVault:
    v = InMemoryKeyVault()
    v.register(key_id, secrets.token_bytes(key_bytes), algorithm=algorithm)
    return v


def _env() -> AeadEnvelope:
    return AeadEnvelope(_vault_with_key())


# ---------------------------------------------------------------------------
# CRY_INV_01 — AEAD tag is produced and enforced
# ---------------------------------------------------------------------------
def test_inv_aead_tag_confirms() -> None:
    env = _env()
    sealed = env.seal(b"hello world", b"context=unit-test")
    # Ciphertext MUST carry the 16-byte AEAD tag appended to the body.
    assert len(sealed.ciphertext) >= len(b"hello world") + AEAD_TAG_BYTES
    # Round-trip proves tag was valid.
    assert env.open(sealed, b"context=unit-test") == b"hello world"


def test_inv_aead_tag_prevents() -> None:
    # Non-AEAD / unauthenticated algorithms MUST NEVER register as adapters.
    for bad in FORBIDDEN_ALGORITHMS:
        with pytest.raises(CryptoEnvelopeError):
            register_adapter(bad)
    with pytest.raises(CryptoEnvelopeError):
        register_adapter("ROT13")


def test_inv_aead_tag_under_failure() -> None:
    env = _env()
    sealed = env.seal(b"payload", b"aad")
    # Flip a bit inside the tag region — open() MUST refuse.
    tampered_ct = bytearray(sealed.ciphertext)
    tampered_ct[-1] ^= 0x01
    tampered = Envelope(
        key_id=sealed.key_id,
        nonce=sealed.nonce,
        ciphertext=bytes(tampered_ct),
        aad=sealed.aad,
    )
    with pytest.raises(CryptoEnvelopeError):
        env.open(tampered, b"aad")


# ---------------------------------------------------------------------------
# CRY_INV_02 — nonces NEVER repeat for a given key
# ---------------------------------------------------------------------------
def test_inv_nonce_uniqueness_confirms() -> None:
    env = _env()
    seen: set[bytes] = set()
    for _ in range(64):
        sealed = env.seal(b"x", b"a")
        assert len(sealed.nonce) == AES_GCM_NONCE_BYTES
        seen.add(sealed.nonce)
    assert len(seen) == 64  # 64/64 unique 96-bit CSPRNG nonces


def test_inv_nonce_uniqueness_prevents() -> None:
    # Reject any envelope whose nonce length is wrong — guards against
    # downgrade to a cipher mode that accepts shorter nonces.
    env = _env()
    good = env.seal(b"x", b"a")
    short = Envelope(
        key_id=good.key_id,
        nonce=good.nonce[:8],
        ciphertext=good.ciphertext,
        aad=good.aad,
    )
    with pytest.raises(CryptoEnvelopeError):
        env.open(short, b"a")


def test_inv_nonce_uniqueness_under_failure() -> None:
    # Inject a duplicate nonce via the internal tracker — the second attempt
    # MUST raise (critical incident signal for monitoring).
    env = _env()
    sealed = env.seal(b"x", b"a")
    # Replay the exact nonce under the same key_id via the tracker.
    with pytest.raises(CryptoEnvelopeError):
        env._nonces.check_and_record(sealed.key_id, sealed.nonce)  # noqa: SLF001 — test harness probes tracker state per CRY-INV-02.


# ---------------------------------------------------------------------------
# CRY_INV_03 — aad byte-for-byte; mismatched aad aborts BEFORE plaintext
# ---------------------------------------------------------------------------
def test_inv_aad_binding_confirms() -> None:
    env = _env()
    sealed = env.seal(b"secret-record", b"record_id=42")
    assert env.open(sealed, b"record_id=42") == b"secret-record"


def test_inv_aad_binding_prevents() -> None:
    env = _env()
    sealed = env.seal(b"secret-record", b"record_id=42")
    with pytest.raises(CryptoEnvelopeError):
        env.open(sealed, b"record_id=43")


def test_inv_aad_binding_under_failure() -> None:
    env = _env()
    sealed = env.seal(b"secret", b"aad-original")
    # Even when the envelope's .aad has been mutated to match a forged caller
    # aad, the AEAD tag will fail because it authenticated the ORIGINAL aad.
    forged = Envelope(
        key_id=sealed.key_id,
        nonce=sealed.nonce,
        ciphertext=sealed.ciphertext,
        aad=b"aad-forged",
    )
    with pytest.raises(CryptoEnvelopeError):
        env.open(forged, b"aad-forged")


# ---------------------------------------------------------------------------
# CRY_INV_04 — unknown key_id MUST NOT return partial plaintext
# ---------------------------------------------------------------------------
def test_inv_key_resolution_confirms() -> None:
    vault = InMemoryKeyVault()
    vault.register("k1", secrets.token_bytes(32))
    env = AeadEnvelope(vault)
    sealed = env.seal(b"p", b"a")
    assert sealed.key_id == "k1"
    rec = vault.resolve("k1")
    assert rec.key_id == "k1"


def test_inv_key_resolution_prevents() -> None:
    vault = InMemoryKeyVault()
    with pytest.raises(CryptoEnvelopeError):
        vault.resolve("never-registered")
    vault.register("k1", secrets.token_bytes(32))
    with pytest.raises(CryptoEnvelopeError):
        vault.resolve("k2")  # unknown key_id


def test_inv_key_resolution_under_failure() -> None:
    vault = InMemoryKeyVault()
    vault.register("k1", secrets.token_bytes(32))
    env = AeadEnvelope(vault)
    sealed = env.seal(b"p", b"a")
    # Forge an envelope pointing at an unknown key_id — open MUST raise.
    forged = Envelope(
        key_id="ghost-key",
        nonce=sealed.nonce,
        ciphertext=sealed.ciphertext,
        aad=sealed.aad,
    )
    with pytest.raises(CryptoEnvelopeError):
        env.open(forged, b"a")


# ---------------------------------------------------------------------------
# CRY_INV_05 — rotation works without re-encrypting stored ciphertext
# ---------------------------------------------------------------------------
def test_inv_key_rotation_confirms() -> None:
    vault = InMemoryKeyVault()
    vault.register("k1", secrets.token_bytes(32))
    env = AeadEnvelope(vault)
    sealed_old = env.seal(b"legacy", b"aad")
    # Rotate: new active key, but old key still resolvable.
    vault.register("k2", secrets.token_bytes(32))
    vault.set_active("k2")
    sealed_new = env.seal(b"fresh", b"aad")
    assert sealed_new.key_id == "k2"
    # Old ciphertext STILL opens — rotation did not invalidate it.
    assert env.open(sealed_old, b"aad") == b"legacy"
    assert env.open(sealed_new, b"aad") == b"fresh"


def test_inv_key_rotation_prevents() -> None:
    vault = InMemoryKeyVault()
    vault.register("k1", secrets.token_bytes(32))
    # Cannot drop the active key — caller MUST rotate first.
    with pytest.raises(CryptoEnvelopeError):
        vault.drop("k1")


def test_inv_key_rotation_under_failure() -> None:
    vault = InMemoryKeyVault()
    vault.register("k1", secrets.token_bytes(32))
    env = AeadEnvelope(vault)
    sealed = env.seal(b"data", b"aad")
    vault.register("k2", secrets.token_bytes(32))
    vault.set_active("k2")
    # Retiring the OLD key makes its ciphertext unopenable — open MUST raise
    # rather than return garbage plaintext.
    vault.drop("k1")
    with pytest.raises(CryptoEnvelopeError):
        env.open(sealed, b"aad")


# ---------------------------------------------------------------------------
# CRY_INV_06 — plaintext NEVER logged/leaked in exceptions
# ---------------------------------------------------------------------------
def test_inv_no_plaintext_leak_confirms() -> None:
    env = _env()
    secret = b"TOP-SECRET-LEAK-CANARY-0xDEADBEEF"
    sealed = env.seal(secret, b"aad")
    # Serialized envelope representation MUST NOT echo plaintext bytes.
    assert secret not in sealed.ciphertext
    assert secret not in sealed.nonce
    assert secret not in repr(sealed).encode("utf-8", "ignore")


def test_inv_no_plaintext_leak_prevents() -> None:
    env = _env()
    canary = b"NEVER-IN-EXCEPTION-0xCAFEBABE"
    try:
        env.seal(canary.decode(), b"aad")  # type: ignore[arg-type]
    except CryptoEnvelopeError as e:
        assert canary not in str(e).encode()
        assert canary not in repr(e).encode()


def test_inv_no_plaintext_leak_under_failure() -> None:
    env = _env()
    canary = b"NEVER-IN-LOGS-0xBADC0DE"
    # Force decrypt failure (bad aad) — the resulting exception MUST NOT carry
    # the plaintext or the aad bytes.
    sealed = env.seal(canary, b"aad-1")
    msgs: list[str] = []
    try:
        env.open(sealed, b"aad-2")
    except CryptoEnvelopeError as e:
        msgs.append(str(e))
        msgs.append(repr(e))
    for m in msgs:
        assert canary not in m.encode()


# ---------------------------------------------------------------------------
# Performance / sanity
# ---------------------------------------------------------------------------
def test_seal_open_roundtrip_many_sizes() -> None:
    env = _env()
    for n in (0, 1, 16, 255, 4096):
        pt = secrets.token_bytes(n)
        sealed = env.seal(pt, b"aad")
        assert env.open(sealed, b"aad") == pt


def test_concurrent_seal_no_nonce_collision() -> None:
    env = _env()
    seen: list[bytes] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(8):
            s = env.seal(b"x", b"a")
            with lock:
                seen.append(s.nonce)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == len(set(seen))
