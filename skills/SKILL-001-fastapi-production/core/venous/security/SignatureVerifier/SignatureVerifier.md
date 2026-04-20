# SignatureVerifier

## What it does (plain language)

SignatureVerifier produces and verifies detached digital signatures over a
byte payload. Callers pick a signer by `key_id`; the primitive binds each
key to exactly one algorithm (Ed25519, ECDSA-P256 with RFC 6979, or
HMAC-SHA256) and wraps every payload in a typed, length-prefixed framing so
the same raw bytes CANNOT produce a valid signature across two different
message types or two different keys. Verification MUST raise on mismatch —
there is no boolean return, no partial-verification signal, and no oracle
surface for attackers to probe.

## Purpose

Produce and verify detached digital signatures with key-id selection, typed
message framing, and refusal of weak or unannounced algorithms.

## When to use and when NOT to use

- USE: webhook signing, signed URLs, JWT-alternative token formats, audit
  event signing, inter-service message integrity, API-request signing.
- USE: any surface where "alg: none" has ever been a risk, or where a mass
  algorithm migration (HMAC to Ed25519) is on the roadmap.
- DO NOT USE: at-rest encryption (see `CryptoEnvelope`); password storage
  (see `PasswordHasher`); TLS channel integrity (use your web server).
- DO NOT USE: JWT parsing/validation directly — wrap this primitive in a
  token-format layer that also binds claims, audience, and expiry.

## API surface

The catalog `api_signature` is authoritative; see
`SignatureVerifier.contract.json`. The Protocol shape:

```python
class SignatureVerifier(Protocol):
    def sign(self, message: bytes, key_id: str) -> bytes: ...
    def verify(self, message: bytes, signature: bytes, key_id: str) -> None: ...
```

The module ships one reference implementation:

- `DetachedSigner` — production default. Routes sign/verify through a pinned
  `TrustAnchor`, applies typed framing, supports optional replay defense.

## Key terms

- **Detached signature**: signature bytes carried alongside the message
  (not embedded). `sign()` returns just the signature; the caller stores or
  transmits it separately.
- **Key ID (kid)**: opaque handle that the `TrustAnchor` resolves to a
  `(algorithm, public_key, optional private_key)` record.
- **Typed framing**: every payload is length-prefixed as
  `|domain|key_id|msg_type|message|` before signing, so a signature under
  `msg_type="login"` CANNOT verify under `msg_type="transfer"`.
- **RFC 6979**: deterministic ECDSA nonce derivation — eliminates RNG failure
  as an attack vector.
- **Pinned trust anchor**: the verifier MUST fetch public keys from a
  separate, pre-configured store. The message being verified CANNOT carry
  its own key.

## Invariants

| ID | Rule |
|---|---|
| SIG_INV_01 | verify() MUST raise on signature mismatch and MUST NEVER return a boolean indicating partial verification. |
| SIG_INV_02 | Accepted algorithms MUST be declared per key_id; algorithm confusion (substituting HS256 for RS256) CANNOT occur. |
| SIG_INV_03 | sign() MUST use deterministic signing (RFC 6979 for ECDSA) or a CSPRNG nonce; ECDSA nonce reuse SHALL be treated as key compromise. |
| SIG_INV_04 | Public keys used for verify MUST be fetched from a pinned trust anchor and MUST NEVER be learned from the same message being verified. |
| SIG_INV_05 | verify() MUST be constant-time with respect to the signature bytes; timing leaks on tag comparison are FORBIDDEN. |

## Invariant to test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

`DetachedSigner` and `TrustAnchor` are safe to read from multiple threads:
the trust anchor is a read-mostly dict guarded by the GIL for lookups.
Registrations should happen during application startup. The optional
`ReplayCache` uses a per-kid list with bounded size; for strictly linearizable
replay protection, wrap the cache in your own lock.

## Operational characteristics (for SRE)

- Ed25519 sign and verify each cost ~70 microseconds on a modern x86 core.
  ECDSA-P256 is ~5 to 10x slower. HMAC-SHA256 is the fastest path at a few
  microseconds.
- Typed framing adds a 16-byte overhead (4 length headers + 1 domain tag
  reference) plus the kid and msg_type byte counts.
- Failure modes: every verification failure (bad signature, wrong kid,
  algorithm mismatch, replay) surfaces a single `SignatureVerifierError`
  class by design (SIG-INV-01, -05, oracle defense).
- Rotation procedure: `anchor.register(new_kid, alg, public_key=..., private_key=...)`
  with a fresh kid. Old kids keep verifying while callers drain. Kids are
  immutable — rebinding an existing kid to a new algorithm is refused.
- Alert if `signature_verifier.replay.detections` > 0 or if
  `signature_verifier.verify.rejections` spikes (possible forgery campaign).

## Security considerations

- `TrustAnchor.register()` refuses FORBIDDEN algorithms: `alg:none`, `HS1`,
  `MD5`, `SHA1`, `HMAC-SHA1`, `RSA-PKCS1-v1_5`, `RSA-PKCS1-v1_5-SHA1`,
  `ECDSA-SHA1`, `DSA-SHA1`.
- Typed framing defeats length-extension ambiguity (the domain tag and
  every field are length-prefixed; Merkle-Damgard extension bytes do not
  compose into a valid frame).
- Ed25519 is deterministic per RFC 8032 — no RNG leak path.
- ECDSA-P256 uses the backend's RFC 6979 deterministic nonces — a repeat of
  the `(key, message)` pair produces the SAME signature, CANNOT leak the
  private key via nonce collision.
- HMAC verify compares via `hmac.compare_digest` (SIG-INV-05). Ed25519 and
  ECDSA verify route through `cryptography`'s constant-time backend.
- Exception messages NEVER echo raw signature bytes, key material, or the
  offending kid. Probe attackers learn nothing from the error surface.

## Wire format

A sealed signature is the raw bytes returned by `sign()`:

| Algorithm     | Signature size | Encoding                     |
|---------------|---------------:|------------------------------|
| Ed25519       | 64 bytes       | raw R || S                   |
| ECDSA-P256    | 64 bytes       | raw r || s (32 bytes each)   |
| HMAC-SHA256   | 32 bytes       | raw tag                      |

Callers own serialization of `(kid, signature)` onto the wire; the
primitive does not prescribe a base64 / hex / JSON envelope.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - OWASP ASVS 4.0.3 V6.2 Algorithms (V6.2.7 asymmetric algorithms).
  - OWASP Top 10 2021 A02 Cryptographic Failures.
  - RFC 8032 (Ed25519), RFC 6979 (ECDSA deterministic nonces).

## Alternatives considered and rejected

- Raw library call per call-site — algorithm-confusion bugs stay endemic.
- HMAC-only for all signing — does not meet non-repudiation for outbound
  signatures (no public / private key separation).
- Gateway-terminated signatures only — leaves internal services vulnerable
  if the gateway is bypassed or misconfigured.

## Extension contract

New signature schemes register as signer adapters implementing the adapter
shape `(algorithm, sign, verify)` and declare their key handle format. The
registry (`register_adapter`) refuses to bind adapters for algorithms
deprecated by the profile (RSA-PKCS1-v1_5, ECDSA with SHA-1). To add a new
scheme, add an entry to `_ADAPTER_FACTORIES` returning a `_SignerAdapter`-
shaped object and extend `ALLOWED_ALGORITHMS`.

## Usage

```python
from SignatureVerifier import (
    ALG_ED25519, DetachedSigner, TrustAnchor,
    generate_ed25519_keypair,
)

anchor = TrustAnchor()
sk, pk = generate_ed25519_keypair()
anchor.register("api-sig-2025", ALG_ED25519, public_key=pk, private_key=sk)

signer = DetachedSigner(anchor, default_msg_type="webhook.v1")

# Sender: sign the payload.
body = b'{"event":"payment.succeeded"}'
sig = signer.sign(body, "api-sig-2025")

# Receiver: verify (reads the public key from its own pinned anchor).
signer.verify(body, sig, "api-sig-2025")  # returns None; raises on mismatch
```

## Compose with:

- **Webhook authentication** → `IdempotentConsumer` + `AuditEvent`
  Incoming webhooks are verified, then dedup'd — replay attacks lose on signature freshness and on idempotency at the same time.

- **Encrypt-then-sign** → `CryptoEnvelope` + `SecretsVault`
  Envelope protects confidentiality; verifier binds the ciphertext to a trusted key — tampering is detected before decryption is even attempted.

- **Key rotation survival** → `KeyRotationSchedule` + `SecretsVault`
  Old kids keep verifying through the overlap window; the verifier never fetches a key from the message it is verifying.
