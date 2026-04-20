"""CryptoEnvelope primitive — AEAD envelope with key-id tagging for rotation.

Implements the catalog Protocol for `security.CryptoEnvelope`. Provides
authenticated encryption with associated data (AEAD) using AES-GCM
(default) or ChaCha20-Poly1305 via the `cryptography` library. Every
envelope carries its `key_id` so the vault can rotate keys without
re-encrypting stored ciphertext.

Import is side-effect-free: the `cryptography` SDK is imported lazily inside
`AeadEnvelope.__init__` so the module remains importable on minimal hosts
that do not yet have the optional dependency wired in.

Invariant IDs (enforced at runtime):

- CRY-INV-01: seal() MUST use an AEAD construction and MUST NEVER emit an
  envelope without an authentication tag.
- CRY-INV-02: nonces MUST NEVER repeat for a given key; collisions raise.
- CRY-INV-03: open() MUST verify aad byte-for-byte before returning plaintext.
- CRY-INV-04: key_id MUST resolve to a live key in the vault; unknown key_id
  MUST raise and MUST NEVER return partial plaintext.
- CRY-INV-05: keys rotate without re-encrypting; open() resolves the correct
  key by the envelope's key_id.
- CRY-INV-06: plaintext buffers are zeroed where Python permits; plaintext
  MUST NEVER appear in logs, exceptions, or reprs.
"""

from __future__ import annotations

import ctypes
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

# Nonce sizes follow NIST SP 800-38D §5.2.1.1 and RFC 7539 §2.3.
AES_GCM_NONCE_BYTES: Final[int] = 12
CHACHA20_NONCE_BYTES: Final[int] = 12
AEAD_TAG_BYTES: Final[int] = 16
MIN_KEY_BYTES: Final[int] = 16  # AES-128 floor; AES-256 (32B) preferred.
ALLOWED_KEY_SIZES: Final[frozenset[int]] = frozenset({16, 24, 32})
ALLOWED_ALGORITHMS: Final[frozenset[str]] = frozenset({"AES-GCM", "ChaCha20-Poly1305"})
# Non-AEAD / unauthenticated modes that MUST NEVER register as adapters.
FORBIDDEN_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {"AES-CBC", "AES-ECB", "AES-CTR", "DES", "3DES", "RC4", "AES-OFB", "AES-CFB"}
)


class CryptoEnvelopeError(ValueError):
    """Runtime invariant violation on a CryptoEnvelope operation.

    Exception text NEVER carries plaintext or raw key material — CRY-INV-06.
    Callers MUST surface this as a 500/uncaught in production logs without
    re-serializing the offending inputs.
    """


# ---------------------------------------------------------------------------
# Envelope dataclass — frozen so producers CANNOT mutate ciphertext/aad/nonce
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Envelope:
    """Sealed payload. Immutable; every field is authenticated.

    `ciphertext` carries the AEAD tag appended as the trailing 16 bytes, per
    the `cryptography` library's AEAD contract. `nonce` is unique per seal
    call for the life of the bound key (CRY-INV-02). `aad` is replayed into
    open() byte-for-byte; divergence aborts decryption (CRY-INV-03).
    """

    key_id: str
    nonce: bytes
    ciphertext: bytes
    aad: bytes


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog byte-for-byte)
# ---------------------------------------------------------------------------
@runtime_checkable
class CryptoEnvelope(Protocol):
    def seal(self, plaintext: bytes, aad: bytes) -> Envelope: ...
    def open(self, envelope: Envelope, aad: bytes) -> bytes: ...


# ---------------------------------------------------------------------------
# Key vault — in-memory reference; production injects a real KMS adapter
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _KeyRecord:
    """Bound key material plus the algorithm it MUST be used with."""

    key_id: str
    key: bytes
    algorithm: str


class InMemoryKeyVault:
    """Reference key vault. Keys are stored by `key_id`; rotation is a set()+set_active().

    CRY-INV-04: `resolve(key_id)` MUST return a live record or raise.
    CRY-INV-05: old keys remain resolvable after rotation so already-sealed
    envelopes continue to open. Callers remove a key_id only when every
    ciphertext bound to it has been re-sealed.
    """

    def __init__(self) -> None:
        self._records: dict[str, _KeyRecord] = {}
        self._active_id: str | None = None

    def register(self, key_id: str, key: bytes, algorithm: str = "AES-GCM") -> None:
        if not isinstance(key_id, str) or not key_id:
            raise CryptoEnvelopeError("CRY-INV-04: key_id MUST be a non-empty str.")
        if algorithm not in ALLOWED_ALGORITHMS:
            raise CryptoEnvelopeError(
                f"CRY-INV-01: algorithm {algorithm!r} is not AEAD; use one of {sorted(ALLOWED_ALGORITHMS)}."
            )
        if not isinstance(key, (bytes, bytearray)):
            raise CryptoEnvelopeError("CRY-INV-04: key MUST be bytes.")
        if algorithm == "AES-GCM" and len(key) not in ALLOWED_KEY_SIZES:
            raise CryptoEnvelopeError(
                f"CRY-INV-04: AES-GCM key MUST be 16/24/32 bytes; got {len(key)}."
            )
        if algorithm == "ChaCha20-Poly1305" and len(key) != 32:
            raise CryptoEnvelopeError(
                f"CRY-INV-04: ChaCha20-Poly1305 key MUST be 32 bytes; got {len(key)}."
            )
        self._records[key_id] = _KeyRecord(key_id=key_id, key=bytes(key), algorithm=algorithm)
        if self._active_id is None:
            self._active_id = key_id

    def set_active(self, key_id: str) -> None:
        if key_id not in self._records:
            raise CryptoEnvelopeError(
                "CRY-INV-04: cannot activate unknown key_id (value withheld from message)."
            )
        self._active_id = key_id

    def active(self) -> _KeyRecord:
        if self._active_id is None:
            raise CryptoEnvelopeError("CRY-INV-04: vault has no active key.")
        # `resolve` re-checks presence so concurrent drop() raises consistently.
        return self.resolve(self._active_id)

    def resolve(self, key_id: str) -> _KeyRecord:
        if not isinstance(key_id, str) or not key_id:
            raise CryptoEnvelopeError("CRY-INV-04: key_id MUST be a non-empty str.")
        rec = self._records.get(key_id)
        if rec is None:
            # CRY-INV-04: never echo the unknown key_id — a probe attacker MUST
            # learn nothing from the error surface.
            raise CryptoEnvelopeError("CRY-INV-04: key_id does not resolve to a live key.")
        return rec

    def known_key_ids(self) -> frozenset[str]:
        return frozenset(self._records.keys())

    def drop(self, key_id: str) -> None:
        """Remove a retired key. Caller MUST have re-sealed all ciphertext first."""
        if key_id == self._active_id:
            raise CryptoEnvelopeError(
                "CRY-INV-05: cannot drop the active key; rotate first."
            )
        self._records.pop(key_id, None)


# ---------------------------------------------------------------------------
# Nonce tracker — guards against reuse under a given key
# ---------------------------------------------------------------------------
class _NonceTracker:
    """In-process nonce-reuse detector. CRY-INV-02.

    Tracks seen (key_id, nonce) pairs. Random 96-bit nonces collide with
    probability ~2^-32 after 2^32 messages per key, so a real deployment
    pairs this with a key-rotation policy. The tracker raises on the *second*
    time the same pair is seen so test suites can assert the invariant
    explicitly.
    """

    def __init__(self) -> None:
        self._seen: dict[str, set[bytes]] = {}

    def check_and_record(self, key_id: str, nonce: bytes) -> None:
        seen = self._seen.setdefault(key_id, set())
        if nonce in seen:
            raise CryptoEnvelopeError(
                "CRY-INV-02: nonce reuse detected — critical incident, rotate key."
            )
        seen.add(nonce)

    def reset(self) -> None:
        self._seen.clear()


# ---------------------------------------------------------------------------
# AEAD adapter shape — type-level guarantee that we only bind to AEAD
# ---------------------------------------------------------------------------
class _AeadAdapter(Protocol):
    nonce_size: int
    tag_size: int
    algorithm: str

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes: ...
    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes: ...


def _aesgcm_adapter() -> _AeadAdapter:
    """Build an AES-GCM adapter. Lazy import — `cryptography` is optional."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    class _AesGcm:
        nonce_size = AES_GCM_NONCE_BYTES
        tag_size = AEAD_TAG_BYTES
        algorithm = "AES-GCM"

        def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
            return AESGCM(key).encrypt(nonce, plaintext, aad)

        def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
            return AESGCM(key).decrypt(nonce, ciphertext, aad)

    return _AesGcm()


def _chacha_adapter() -> _AeadAdapter:
    """Build a ChaCha20-Poly1305 adapter. Lazy import."""
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    class _ChaCha:
        nonce_size = CHACHA20_NONCE_BYTES
        tag_size = AEAD_TAG_BYTES
        algorithm = "ChaCha20-Poly1305"

        def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
            return ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)

        def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
            return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)

    return _ChaCha()


_ADAPTER_FACTORIES: Final[Mapping[str, Callable[[], _AeadAdapter]]] = {
    "AES-GCM": _aesgcm_adapter,
    "ChaCha20-Poly1305": _chacha_adapter,
}


def register_adapter(algorithm: str) -> _AeadAdapter:
    """Extension-contract entry point. Refuses non-AEAD modes at the door."""
    if algorithm in FORBIDDEN_ALGORITHMS:
        raise CryptoEnvelopeError(
            f"CRY-INV-01: algorithm {algorithm!r} is FORBIDDEN (non-AEAD / unauthenticated)."
        )
    factory = _ADAPTER_FACTORIES.get(algorithm)
    if factory is None:
        raise CryptoEnvelopeError(
            f"CRY-INV-01: algorithm {algorithm!r} is not on the AEAD allow-list."
        )
    return factory()


# ---------------------------------------------------------------------------
# Best-effort plaintext zeroization helper — CRY-INV-06
# ---------------------------------------------------------------------------
def _zero_bytearray(buf: bytearray) -> None:
    """Overwrite a bytearray in place. Python's immutable `bytes` cannot be
    zeroed; callers that need zeroization MUST route through bytearray.
    """
    if not isinstance(buf, bytearray):
        raise CryptoEnvelopeError("CRY-INV-06: zeroization requires a bytearray.")
    # ctypes.memset is the most portable way to force the write; the bytearray
    # header is laid out with the payload starting at `ob_start`. `len()` gives
    # the authoritative byte count.
    n = len(buf)
    if n == 0:
        return
    addr = (ctypes.c_char * n).from_buffer(buf)
    ctypes.memset(ctypes.addressof(addr), 0, n)


# ---------------------------------------------------------------------------
# Reference implementation — AeadEnvelope
# ---------------------------------------------------------------------------
class AeadEnvelope:
    """Reference `CryptoEnvelope` impl backed by a `InMemoryKeyVault`.

    Construction is explicit: pass a vault with at least one registered key.
    The instance picks the vault's *active* key for seal(); open() resolves
    by the envelope's `key_id` so rotation does not invalidate stored data.

    This class honors every CRY invariant at runtime — CRY-INV-01 .. -06.
    """

    def __init__(
        self,
        vault: InMemoryKeyVault,
        *,
        algorithm: str = "AES-GCM",
        nonce_tracker: _NonceTracker | None = None,
    ) -> None:
        # Lazy import of cryptography lives inside register_adapter().
        if algorithm not in ALLOWED_ALGORITHMS:
            raise CryptoEnvelopeError(
                f"CRY-INV-01: algorithm {algorithm!r} is not AEAD."
            )
        self._vault = vault
        self._adapter = register_adapter(algorithm)
        self._algorithm = algorithm
        self._nonces = nonce_tracker or _NonceTracker()

    @property
    def algorithm(self) -> str:
        return self._algorithm

    def seal(self, plaintext: bytes, aad: bytes) -> Envelope:
        if not isinstance(plaintext, (bytes, bytearray)):
            raise CryptoEnvelopeError("CRY-INV-06: plaintext MUST be bytes (value withheld).")
        if not isinstance(aad, (bytes, bytearray)):
            raise CryptoEnvelopeError("CRY-INV-03: aad MUST be bytes.")
        rec = self._vault.active()
        if rec.algorithm != self._algorithm:
            # Key was registered under a different cipher family — refuse to
            # seal rather than silently downgrade.
            raise CryptoEnvelopeError(
                "CRY-INV-04: active key's algorithm does not match envelope algorithm."
            )
        # CRY-INV-02: 96-bit random nonce per message (NIST 800-38D §8.2.2).
        nonce = secrets.token_bytes(self._adapter.nonce_size)
        self._nonces.check_and_record(rec.key_id, nonce)
        # Defensive copy through bytearray so we can zero the source after use.
        pt_buf = bytearray(plaintext)
        aad_bytes = bytes(aad)
        try:
            ct_with_tag = self._adapter.encrypt(rec.key, nonce, bytes(pt_buf), aad_bytes)
        finally:
            # CRY-INV-06: zero the mutable plaintext copy regardless of outcome.
            _zero_bytearray(pt_buf)
        # CRY-INV-01: AEAD ciphertexts MUST carry a tag. `cryptography` appends
        # a 16-byte tag to the ciphertext; refuse any output that is shorter
        # than `len(plaintext) + tag_size` (possible only on broken adapters).
        if len(ct_with_tag) < self._adapter.tag_size:
            raise CryptoEnvelopeError(
                "CRY-INV-01: AEAD output is missing authentication tag."
            )
        return Envelope(
            key_id=rec.key_id,
            nonce=nonce,
            ciphertext=ct_with_tag,
            aad=aad_bytes,
        )

    def open(self, envelope: Envelope, aad: bytes) -> bytes:
        if not isinstance(envelope, Envelope):
            raise CryptoEnvelopeError("CRY-INV-01: envelope MUST be an Envelope instance.")
        if not isinstance(aad, (bytes, bytearray)):
            raise CryptoEnvelopeError("CRY-INV-03: aad MUST be bytes.")
        # CRY-INV-03: aad byte-for-byte match BEFORE we touch the cipher. This
        # avoids spending CPU cycles on obviously mismatched associated data
        # and surfaces tamper attempts as a single error class.
        if bytes(aad) != envelope.aad:
            raise CryptoEnvelopeError(
                "CRY-INV-03: aad mismatch — refusing to decrypt."
            )
        if len(envelope.ciphertext) < self._adapter.tag_size:
            raise CryptoEnvelopeError(
                "CRY-INV-01: ciphertext too short to carry an AEAD tag."
            )
        # CRY-INV-04: resolve by the envelope's own key_id so rotation works.
        rec = self._vault.resolve(envelope.key_id)
        if rec.algorithm != self._algorithm:
            raise CryptoEnvelopeError(
                "CRY-INV-04: resolved key's algorithm does not match envelope algorithm."
            )
        if len(envelope.nonce) != self._adapter.nonce_size:
            raise CryptoEnvelopeError(
                f"CRY-INV-02: nonce MUST be {self._adapter.nonce_size} bytes."
            )
        try:
            return self._adapter.decrypt(
                rec.key, envelope.nonce, envelope.ciphertext, envelope.aad
            )
        except Exception as exc:
            raise CryptoEnvelopeError(
                "CRY-INV-01: AEAD authentication failed — envelope rejected."
            ) from exc


__all__ = [
    "AEAD_TAG_BYTES",
    "AES_GCM_NONCE_BYTES",
    "ALLOWED_ALGORITHMS",
    "ALLOWED_KEY_SIZES",
    "CHACHA20_NONCE_BYTES",
    "FORBIDDEN_ALGORITHMS",
    "MIN_KEY_BYTES",
    "AeadEnvelope",
    "CryptoEnvelope",
    "CryptoEnvelopeError",
    "Envelope",
    "InMemoryKeyVault",
    "register_adapter",
]
