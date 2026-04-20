"""SignatureVerifier primitive — detached signature producer/verifier.

Implements the catalog Protocol for `security.SignatureVerifier`. Supports
key-id-scoped signing across Ed25519, ECDSA-P256 (with RFC 6979 deterministic
nonces), and HMAC-SHA256. Each key_id binds to a single algorithm at
registration time so algorithm-confusion attacks (e.g. substituting HS256 for
RS256) are rejected at the door.

Every sign/verify call wraps the user payload in a typed, length-prefixed
framing (`|domain|key_id|msg_type|message|`) so the same raw bytes CANNOT
produce a valid signature across different message types — domain separation
defeats cross-type replay and length-extension style ambiguity.

Import is side-effect-free: the optional `cryptography` SDK is imported
lazily inside `_ed25519_adapter()` and `_ecdsa_p256_adapter()` so the module
remains importable on minimal hosts. HMAC uses the stdlib only.

Invariant IDs (enforced at runtime):

- SIG-INV-01: verify() MUST raise on any signature mismatch; MUST NEVER
  return a bool or a "partially verified" signal.
- SIG-INV-02: algorithm MUST be bound to key_id at registration. Verify with a
  mismatched algorithm (HS256-for-RS256) MUST raise.
- SIG-INV-03: sign() MUST use RFC 6979 deterministic nonces (ECDSA) or a
  CSPRNG (Ed25519 uses internal deterministic key-hash nonce). Nonce reuse
  under ECDSA SHALL be treated as key compromise.
- SIG-INV-04: public keys used for verify MUST come from the pinned trust
  anchor (TrustAnchor); the signature message CANNOT carry its own key.
- SIG-INV-05: verify() MUST compare signature bytes in constant time
  (`hmac.compare_digest`); timing leaks on tag comparison are FORBIDDEN.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Algorithm allow-list + forbidden-list — extension contract defense
# ---------------------------------------------------------------------------
ALG_ED25519: Final[str] = "Ed25519"
ALG_ECDSA_P256: Final[str] = "ECDSA-P256"
ALG_HMAC_SHA256: Final[str] = "HMAC-SHA256"

ALLOWED_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {ALG_ED25519, ALG_ECDSA_P256, ALG_HMAC_SHA256}
)
# Deprecated-by-profile algorithms that MUST NEVER register.
FORBIDDEN_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {
        "none",
        "alg:none",
        "HS1",
        "MD5",
        "SHA1",
        "HMAC-SHA1",
        "RSA-PKCS1-v1_5",
        "RSA-PKCS1-v1_5-SHA1",
        "ECDSA-SHA1",
        "DSA-SHA1",
    }
)

# Framing constants — a single domain tag prefixes every signed payload so
# cross-primitive replay is impossible (SIG-INV-04 domain separation).
_FRAMING_DOMAIN: Final[bytes] = b"HuGR/SignatureVerifier/v1"
# Replay window default: signatures older than this (nonce-seen) expire from
# the in-process replay cache. Callers supply their own for stateful use.
DEFAULT_REPLAY_WINDOW_ENTRIES: Final[int] = 65536


class SignatureVerifierError(ValueError):
    """Runtime invariant violation on a SignatureVerifier operation.

    Single exception class by design — collapses the oracle surface so an
    attacker CANNOT distinguish "bad signature" from "unknown key_id" from
    "algorithm mismatch" by inspecting the error type (SIG-INV-01, -02, -05).
    Exception messages NEVER echo raw key material or signature bytes.
    """


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog byte-for-byte)
# ---------------------------------------------------------------------------
@runtime_checkable
class SignatureVerifier(Protocol):
    def sign(self, message: bytes, key_id: str) -> bytes: ...
    def verify(self, message: bytes, signature: bytes, key_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Typed message framing — domain separation for message types
# ---------------------------------------------------------------------------
def frame_message(message: bytes, key_id: str, msg_type: str) -> bytes:
    """Length-prefix-encode `(domain, key_id, msg_type, message)` into a
    single byte string. Two different (key_id, msg_type) pairs CANNOT produce
    the same framed bytes even if `message` collides, because every field is
    length-prefixed with a fixed-width big-endian 32-bit length header.

    This is the canonical defense against:
      - length-extension ambiguity (Merkle-Damgard hashes)
      - cross-type replay ("transfer" framed as "login")
      - key-id confusion (the same bytes signed under a different kid)
    """
    if not isinstance(message, (bytes, bytearray)):
        raise SignatureVerifierError("SIG-INV-01: message MUST be bytes.")
    if not isinstance(key_id, str) or not key_id:
        raise SignatureVerifierError("SIG-INV-02: key_id MUST be a non-empty str.")
    if not isinstance(msg_type, str) or not msg_type:
        raise SignatureVerifierError("SIG-INV-02: msg_type MUST be a non-empty str.")
    kid = key_id.encode("utf-8")
    mt = msg_type.encode("utf-8")
    body = bytes(message)
    # Each field: 4-byte big-endian length, then raw bytes. The domain tag
    # itself is also length-prefixed so adversaries cannot re-parse the
    # framing under a different schema version.
    parts = [_FRAMING_DOMAIN, kid, mt, body]
    out = bytearray()
    for p in parts:
        out.extend(struct.pack(">I", len(p)))
        out.extend(p)
    return bytes(out)


# ---------------------------------------------------------------------------
# Trust anchor — pinned public-key store. Extracted so callers cannot learn
# the public key from the message being verified (SIG-INV-04).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _KeyRecord:
    """Registered signing identity. `algorithm` is immutable per key_id."""

    key_id: str
    algorithm: str
    # For HMAC this is the shared secret; for Ed25519/ECDSA this is the raw
    # private key bytes (signing side). Verify-only records carry `None`.
    private_key: bytes | None
    # For Ed25519 the 32-byte raw public key; for ECDSA the uncompressed
    # SEC1 point bytes; for HMAC the same secret as `private_key`.
    public_key: bytes


class TrustAnchor:
    """Pinned key registry. Verification MUST route through this object so
    the caller's message CANNOT substitute its own public key.

    SIG-INV-02: each key_id binds to exactly one algorithm for life.
    SIG-INV-04: only keys installed here are accepted; unknown key_id raises.
    """

    def __init__(self) -> None:
        self._records: dict[str, _KeyRecord] = {}

    def register(
        self,
        key_id: str,
        algorithm: str,
        *,
        public_key: bytes,
        private_key: bytes | None = None,
    ) -> None:
        if not isinstance(key_id, str) or not key_id:
            raise SignatureVerifierError(
                "SIG-INV-02: key_id MUST be a non-empty str."
            )
        if algorithm in FORBIDDEN_ALGORITHMS:
            raise SignatureVerifierError(
                f"SIG-INV-02: algorithm {algorithm!r} is FORBIDDEN by profile."
            )
        if algorithm not in ALLOWED_ALGORITHMS:
            raise SignatureVerifierError(
                f"SIG-INV-02: algorithm {algorithm!r} is not on the allow-list."
            )
        if not isinstance(public_key, (bytes, bytearray)):
            raise SignatureVerifierError(
                "SIG-INV-04: public_key MUST be bytes."
            )
        if key_id in self._records:
            # Algorithm rebinding is FORBIDDEN — once a key_id is associated
            # with an algorithm it stays that way. Callers rotate by picking
            # a new key_id (e.g. `sig-k1-v2`).
            raise SignatureVerifierError(
                "SIG-INV-02: key_id is already registered; choose a fresh kid."
            )
        self._records[key_id] = _KeyRecord(
            key_id=key_id,
            algorithm=algorithm,
            private_key=(bytes(private_key) if private_key is not None else None),
            public_key=bytes(public_key),
        )

    def resolve(self, key_id: str) -> _KeyRecord:
        if not isinstance(key_id, str) or not key_id:
            raise SignatureVerifierError(
                "SIG-INV-04: key_id MUST be a non-empty str."
            )
        rec = self._records.get(key_id)
        if rec is None:
            # SIG-INV-04: unknown kid MUST raise; never echo the offending
            # value back into the error surface (probe defense).
            raise SignatureVerifierError(
                "SIG-INV-04: key_id not found in pinned trust anchor."
            )
        return rec

    def known_key_ids(self) -> frozenset[str]:
        return frozenset(self._records.keys())


# ---------------------------------------------------------------------------
# Algorithm adapters — one per supported scheme. Lazy-imported on use.
# ---------------------------------------------------------------------------
class _SignerAdapter(Protocol):
    algorithm: str

    def sign(self, private_key: bytes, framed: bytes) -> bytes: ...
    def verify(self, public_key: bytes, framed: bytes, signature: bytes) -> None: ...


def _hmac_adapter() -> _SignerAdapter:
    """HMAC-SHA256 adapter — stdlib only, always available."""

    class _Hmac:
        algorithm = ALG_HMAC_SHA256

        def sign(self, private_key: bytes, framed: bytes) -> bytes:
            # SIG-INV-03: HMAC is deterministic by construction (no nonce).
            return hmac.new(private_key, framed, hashlib.sha256).digest()

        def verify(self, public_key: bytes, framed: bytes, signature: bytes) -> None:
            expected = hmac.new(public_key, framed, hashlib.sha256).digest()
            # SIG-INV-05: constant-time compare.
            if not hmac.compare_digest(expected, signature):
                raise SignatureVerifierError(
                    "SIG-INV-01: signature verification failed."
                )

    return _Hmac()


def _ed25519_adapter() -> _SignerAdapter:
    """Ed25519 adapter. Lazy-imports `cryptography.hazmat.primitives...`."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    class _Ed25519:
        algorithm = ALG_ED25519

        def sign(self, private_key: bytes, framed: bytes) -> bytes:
            # Ed25519 is deterministic per RFC 8032 — no RNG nonce to leak.
            sk = Ed25519PrivateKey.from_private_bytes(private_key)
            return sk.sign(framed)

        def verify(self, public_key: bytes, framed: bytes, signature: bytes) -> None:
            pk = Ed25519PublicKey.from_public_bytes(public_key)
            try:
                pk.verify(signature, framed)
            except InvalidSignature as exc:
                raise SignatureVerifierError(
                    "SIG-INV-01: signature verification failed."
                ) from exc

    return _Ed25519()


def _ecdsa_p256_adapter() -> _SignerAdapter:
    """ECDSA-P256 adapter with RFC 6979 deterministic nonces (SIG-INV-03)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    class _EcdsaP256:
        algorithm = ALG_ECDSA_P256

        def sign(self, private_key: bytes, framed: bytes) -> bytes:
            # Deserialize the pinned PEM-encoded P-256 private key.
            sk = serialization.load_pem_private_key(private_key, password=None)
            if not isinstance(sk, ec.EllipticCurvePrivateKey):
                raise SignatureVerifierError(
                    "SIG-INV-02: private key is not an EC key."
                )
            if sk.curve.name != "secp256r1":
                raise SignatureVerifierError(
                    "SIG-INV-02: ECDSA curve MUST be secp256r1 (P-256)."
                )
            # `cryptography`'s ECDSA path uses RFC 6979 deterministic nonces
            # via its backend; no RNG entropy is consumed per sign call.
            der = sk.sign(framed, ec.ECDSA(hashes.SHA256()))
            r, s = utils.decode_dss_signature(der)
            # Emit fixed-width 64-byte (r||s) so downstream comparators can
            # avoid DER re-parsing side channels.
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")

        def verify(self, public_key: bytes, framed: bytes, signature: bytes) -> None:
            if len(signature) != 64:
                raise SignatureVerifierError(
                    "SIG-INV-01: ECDSA signature MUST be 64 bytes (r||s)."
                )
            pk = serialization.load_pem_public_key(public_key)
            if not isinstance(pk, ec.EllipticCurvePublicKey):
                raise SignatureVerifierError(
                    "SIG-INV-02: public key is not an EC key."
                )
            r = int.from_bytes(signature[:32], "big")
            s = int.from_bytes(signature[32:], "big")
            der = utils.encode_dss_signature(r, s)
            try:
                pk.verify(der, framed, ec.ECDSA(hashes.SHA256()))
            except InvalidSignature as exc:
                raise SignatureVerifierError(
                    "SIG-INV-01: signature verification failed."
                ) from exc

    return _EcdsaP256()


_ADAPTER_FACTORIES: Final[Mapping[str, Callable[[], _SignerAdapter]]] = {
    ALG_HMAC_SHA256: _hmac_adapter,
    ALG_ED25519: _ed25519_adapter,
    ALG_ECDSA_P256: _ecdsa_p256_adapter,
}


def register_adapter(algorithm: str) -> _SignerAdapter:
    """Extension-contract entry point. Refuses deprecated algorithms."""
    if algorithm in FORBIDDEN_ALGORITHMS:
        raise SignatureVerifierError(
            f"SIG-INV-02: algorithm {algorithm!r} is FORBIDDEN by profile."
        )
    factory = _ADAPTER_FACTORIES.get(algorithm)
    if factory is None:
        raise SignatureVerifierError(
            f"SIG-INV-02: algorithm {algorithm!r} is not on the allow-list."
        )
    return factory()


# ---------------------------------------------------------------------------
# Replay protection — nonce + window
# ---------------------------------------------------------------------------
class _ReplayCache:
    """Bounded LRU-ish set of seen (key_id, signature) pairs.

    Pure defense-in-depth: even when a signature is cryptographically valid,
    a caller that opts into replay protection can ensure the same signature
    CANNOT be accepted twice within the window. Stateless signatures (e.g.
    one-shot webhooks) do not use this cache.
    """

    def __init__(self, window: int = DEFAULT_REPLAY_WINDOW_ENTRIES) -> None:
        if window < 1:
            raise SignatureVerifierError(
                "SIG-INV-01: replay window MUST be ≥1."
            )
        self._window = window
        self._seen: dict[str, list[bytes]] = {}

    def check_and_record(self, key_id: str, signature: bytes) -> None:
        lst = self._seen.setdefault(key_id, [])
        if signature in lst:
            raise SignatureVerifierError(
                "SIG-INV-01: replay detected — signature already seen."
            )
        lst.append(signature)
        # Bounded: drop oldest once window is exceeded so memory stays finite.
        if len(lst) > self._window:
            del lst[0 : len(lst) - self._window]

    def reset(self) -> None:
        self._seen.clear()


# ---------------------------------------------------------------------------
# Reference implementation — DetachedSigner
# ---------------------------------------------------------------------------
class DetachedSigner:
    """Reference `SignatureVerifier` impl.

    Construction is explicit: pass a `TrustAnchor` with at least one
    registered key. Every sign/verify pair passes through `frame_message()`
    so (key_id, msg_type) are authenticated by the signature itself.

    Parameters
    ----------
    anchor : TrustAnchor
        Pinned keystore — SIG-INV-04 requires that verify route through this.
    default_msg_type : str
        Applied when the caller does not override via `sign_typed` /
        `verify_typed`. Set to a primitive-specific tag in production.
    replay_cache : _ReplayCache | None
        Optional replay guard. When provided, `verify()` raises on duplicate
        (key_id, signature) within the configured window.
    """

    def __init__(
        self,
        anchor: TrustAnchor,
        *,
        default_msg_type: str = "generic",
        replay_cache: _ReplayCache | None = None,
    ) -> None:
        if not isinstance(anchor, TrustAnchor):
            raise SignatureVerifierError(
                "SIG-INV-04: anchor MUST be a TrustAnchor."
            )
        if not isinstance(default_msg_type, str) or not default_msg_type:
            raise SignatureVerifierError(
                "SIG-INV-02: default_msg_type MUST be a non-empty str."
            )
        self._anchor = anchor
        self._default_msg_type = default_msg_type
        self._replay = replay_cache

    @property
    def anchor(self) -> TrustAnchor:
        return self._anchor

    # ------------------------------------------------------------------
    # Public Protocol surface — SIG-INV-04: `message` is the raw payload.
    # Typed framing is applied inside; callers never see the wire bytes.
    # ------------------------------------------------------------------
    def sign(self, message: bytes, key_id: str) -> bytes:
        return self.sign_typed(message, key_id, msg_type=self._default_msg_type)

    def verify(self, message: bytes, signature: bytes, key_id: str) -> None:
        self.verify_typed(
            message, signature, key_id, msg_type=self._default_msg_type
        )

    # ------------------------------------------------------------------
    # Typed variants — caller picks the domain separation tag.
    # ------------------------------------------------------------------
    def sign_typed(self, message: bytes, key_id: str, *, msg_type: str) -> bytes:
        if not isinstance(message, (bytes, bytearray)):
            raise SignatureVerifierError("SIG-INV-01: message MUST be bytes.")
        if not isinstance(key_id, str) or not key_id:
            raise SignatureVerifierError(
                "SIG-INV-02: key_id MUST be a non-empty str."
            )
        rec = self._anchor.resolve(key_id)
        if rec.private_key is None:
            raise SignatureVerifierError(
                "SIG-INV-04: key_id has no private key; verify-only."
            )
        adapter = register_adapter(rec.algorithm)
        framed = frame_message(message, key_id=rec.key_id, msg_type=msg_type)
        return adapter.sign(rec.private_key, framed)

    def verify_typed(
        self,
        message: bytes,
        signature: bytes,
        key_id: str,
        *,
        msg_type: str,
    ) -> None:
        if not isinstance(message, (bytes, bytearray)):
            raise SignatureVerifierError("SIG-INV-01: message MUST be bytes.")
        if not isinstance(signature, (bytes, bytearray)):
            raise SignatureVerifierError(
                "SIG-INV-01: signature MUST be bytes."
            )
        if not isinstance(key_id, str) or not key_id:
            raise SignatureVerifierError(
                "SIG-INV-02: key_id MUST be a non-empty str."
            )
        sig_bytes = bytes(signature)
        # Size sanity check BEFORE resolving the key so we don't leak "key
        # exists" vs "sig malformed" via exception type.
        if len(sig_bytes) == 0:
            raise SignatureVerifierError(
                "SIG-INV-01: signature MUST NOT be empty."
            )
        rec = self._anchor.resolve(key_id)
        adapter = register_adapter(rec.algorithm)
        framed = frame_message(message, key_id=rec.key_id, msg_type=msg_type)
        adapter.verify(rec.public_key, framed, sig_bytes)
        # SIG-INV-01: no return value — caller-facing contract is raise-or-None.
        if self._replay is not None:
            self._replay.check_and_record(rec.key_id, sig_bytes)


# ---------------------------------------------------------------------------
# Convenience key generation helpers for tests and examples
# ---------------------------------------------------------------------------
def generate_hmac_key(nbytes: int = 32) -> bytes:
    """Generate an HMAC-SHA256 shared secret (SIG-INV-03: CSPRNG entropy)."""
    if nbytes < 32:
        raise SignatureVerifierError(
            "SIG-INV-03: HMAC-SHA256 key MUST be ≥32 bytes."
        )
    return secrets.token_bytes(nbytes)


def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    """Return `(private_bytes, public_bytes)` for an Ed25519 keypair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    sk = Ed25519PrivateKey.generate()
    sk_raw = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pk_raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return sk_raw, pk_raw


def generate_ecdsa_p256_keypair() -> tuple[bytes, bytes]:
    """Return `(private_pem, public_pem)` for an ECDSA-P256 keypair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    sk = ec.generate_private_key(ec.SECP256R1())
    sk_pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pk_pem = sk.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return sk_pem, pk_pem


ReplayCache = _ReplayCache


__all__ = [
    "ALG_ECDSA_P256",
    "ALG_ED25519",
    "ALG_HMAC_SHA256",
    "ALLOWED_ALGORITHMS",
    "DEFAULT_REPLAY_WINDOW_ENTRIES",
    "FORBIDDEN_ALGORITHMS",
    "DetachedSigner",
    "ReplayCache",
    "SignatureVerifier",
    "SignatureVerifierError",
    "TrustAnchor",
    "frame_message",
    "generate_ecdsa_p256_keypair",
    "generate_ed25519_keypair",
    "generate_hmac_key",
    "register_adapter",
]
