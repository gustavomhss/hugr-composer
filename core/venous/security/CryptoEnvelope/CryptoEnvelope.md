# CryptoEnvelope

## What it does (plain language)

CryptoEnvelope turns a plaintext byte buffer into a self-describing sealed
envelope using authenticated encryption (AEAD). Every envelope carries the
`key_id` used to seal it, a unique 96-bit nonce, and associated data (`aad`)
that is authenticated but not encrypted. On read, the envelope's `key_id`
routes decryption to the correct key in the vault — so rotating keys never
invalidates already-stored ciphertext. Business value: even if your database
is stolen, the attacker cannot read PII without also stealing every key
material still referenced by a live `key_id`.

## Purpose

Encrypt and decrypt payloads with authenticated encryption, key-id-tagged
ciphertext, and deterministic header framing that enables key rotation
without re-encryption on read.

## When to use and when NOT to use

- USE: at-rest encryption of PII, credentials, tokens, audit payloads; any
  field whose confidentiality + integrity MUST both survive a DB leak.
- USE: envelope encryption as the app-layer complement to a KMS data-key
  hierarchy (wrap the per-record key with KMS; seal the payload with it).
- DO NOT USE: password storage (see `PasswordHasher`); JWT/token signing
  (see `SignatureVerifier`); TLS channel crypto (use your web server).
- DO NOT USE: when plaintext length itself is sensitive — ciphertext length
  equals plaintext length plus a 16-byte tag.

## API surface

The catalog `api_signature` is authoritative; see `CryptoEnvelope.contract.json`.
The module ships one reference implementation:

- `AeadEnvelope` — production default. Uses AES-GCM (default) or
  ChaCha20-Poly1305 via the `cryptography` library (lazy import).

Both honor the `CryptoEnvelope` Protocol: `seal(plaintext, aad) -> Envelope`
and `open(envelope, aad) -> bytes`.

## Key terms

- **AEAD**: Authenticated Encryption with Associated Data. Produces
  ciphertext + tag in one step; decrypt rejects a ciphertext whose tag does
  not match.
- **Nonce**: a number used once per (key, message). 96-bit random nonces
  under AES-GCM are safe up to ~2^32 messages per key.
- **AAD (Associated Data)**: plaintext context (e.g. `record_id=42`) that is
  authenticated by the tag but not encrypted.
- **Key ID**: opaque handle that the vault resolves to live key material.

## Invariants

| ID | Rule |
|---|---|
| CRY_INV_01 | seal() MUST use an AEAD construction (AES-GCM, ChaCha20-Poly1305) and CANNOT emit an envelope without an authentication tag. |
| CRY_INV_02 | Nonces MUST NEVER repeat for a given key; nonce reuse under AES-GCM SHALL be treated as a critical incident. |
| CRY_INV_03 | open() MUST verify aad byte-for-byte; mismatched aad MUST abort before returning plaintext. |
| CRY_INV_04 | key_id MUST resolve to a live key in the vault; decryption with an unknown key_id CANNOT return partial plaintext. |
| CRY_INV_05 | Keys MUST be rotatable without re-encrypting stored ciphertext; open() MUST resolve the correct key by key_id from the envelope. |
| CRY_INV_06 | Plaintext buffers SHALL be zeroed where the runtime allows after use; plaintext MUST NEVER be logged. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

`AeadEnvelope` and `InMemoryKeyVault` are safe to use across threads for
read-mostly workloads: `seal()` and `open()` only mutate the nonce tracker
(guarded by Python's GIL for set insertion on small values). Production
deployments that need hard linearizability should wrap the vault in a
single-writer pool or move the key state to an external KMS.

## Operational characteristics (for SRE)

- AES-GCM at a 32-byte key encrypts ~1 GiB/s per core on modern x86. Expect
  p50 `seal()` latency under 20µs for payloads <1 KiB.
- Memory: each envelope holds `plaintext_bytes + 16` of ciphertext plus a
  12-byte nonce and a 96-byte `_NonceTracker` entry per seal. Rotate keys
  to keep the tracker bounded.
- Failure modes: authentication failure (bad tag / bad aad / unknown key)
  surfaces a SINGLE `CryptoEnvelopeError` class by design (CRY-INV-01,
  oracle defense). Surface as 400 for caller error or 500 for integrity
  breach depending on context; never as 200.
- Rotation procedure: `vault.register(new_id, new_key); vault.set_active(new_id)`.
  Old envelopes keep opening. Drop the old key only after every dependent
  ciphertext has been re-sealed.
- Alert if `crypto_envelope.nonce.collisions` > 0 — this is a critical
  incident (CRY-INV-02).

## Security considerations

- `AeadEnvelope` rejects non-AEAD modes (CBC, ECB, CTR-without-MAC) at the
  adapter door; FORBIDDEN_ALGORITHMS is a frozenset allow-list negation.
- Nonces are drawn from `secrets.token_bytes` (CSPRNG). The `_NonceTracker`
  raises on the second observation of a `(key_id, nonce)` pair so a buggy
  RNG cannot silently void the GCM security proof.
- Keys are stored in bytes inside `_KeyRecord`; the Envelope does NOT carry
  key material, and exceptions NEVER echo key_id from the failure path
  (CRY-INV-04: error messages withhold the offending value).
- Plaintext is copied into a `bytearray` and zeroed in the `finally` of
  `seal()` (CRY-INV-06). Callers that need zeroization of their source
  buffer must pass a bytearray they control and zero it themselves.
- Decryption failures collapse to one error class to prevent tag-vs-aad-vs-key
  oracles from timing or exception-type inspection.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - OWASP ASVS 4.0.3 V6.2 Algorithms (V6.2.4, V6.2.5); V6.3 Random Values.
  - OWASP Top 10 2021 A02 Cryptographic Failures — algorithm and mode
    selection.
  - NIST SP 800-38D §5.2.1.1 and §8.2.2 on GCM nonce construction.

## Alternatives considered and rejected

- Raw AES-CBC with HMAC composition — easy to mis-pair; padding-oracle risk.
- pgcrypto `pgp_sym_encrypt` — opaque to app-layer rotation and audit.
- Field-level cryptography library per model — scatters key policy across
  schemas and blocks coordinated rotation.

## Extension contract

AEAD algorithms register as cipher adapters implementing the Protocol and
declaring `nonce_size`, `tag_size`, and key handle type. The registry
(`register_adapter`) refuses to bind an adapter that exposes non-AEAD modes
(CBC without HMAC, ECB) or allows nonce reuse. To add a new AEAD, add an
entry to `_ADAPTER_FACTORIES` returning a `_AeadAdapter`-shaped object.

## Usage

```python
from CryptoEnvelope import AeadEnvelope, InMemoryKeyVault
import secrets

vault = InMemoryKeyVault()
vault.register("k-prod-1", secrets.token_bytes(32))  # 256-bit AES-GCM key

env = AeadEnvelope(vault)

def store_pii(record_id: str, pii: bytes) -> None:
    sealed = env.seal(plaintext=pii, aad=record_id.encode())
    repo.save(
        record_id=record_id,
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        key_id=sealed.key_id,
    )

def read_pii(record_id: str) -> bytes:
    row = repo.load(record_id)
    envelope = Envelope(
        key_id=row.key_id, nonce=row.nonce,
        ciphertext=row.ciphertext, aad=record_id.encode(),
    )
    return env.open(envelope, aad=record_id.encode())
```

## Compose with:

- **Encrypt-then-sign** → `SignatureVerifier` + `SecretsVault`
  Envelope seals the payload; signer binds it to a key; verifier rejects tampering — the two primitives cover confidentiality and integrity in order.

- **Versioned ciphertext** → `KeyRotationSchedule` + `EncryptionPolicy`
  Key version rides with the ciphertext; rotation installs a new DEK without re-encrypting old records — overlap makes migration lazy and safe.

- **Compliance-grade at-rest** → `DataResidencyPolicy` + `PiiClassification`
  Sensitive classes traverse the envelope before storage; residency policy chooses the KMS — 'encrypted with the right key in the right region' is mechanical.
