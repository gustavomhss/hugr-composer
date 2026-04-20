# PasswordHasher

## What it does (plain language)

PasswordHasher turns a user-supplied password into a stored verifier string
that can be checked later without ever keeping the original password on disk.
It uses a memory-hard key derivation function (Argon2id or scrypt), a unique
per-credential salt, and a constant-time comparison so timing does not leak
information. The stored string is self-describing: algorithm, cost, salt, and
digest are embedded so future cost increases can be rolled out gradually via
`needs_rehash`.

## Purpose

Derive a verifier from a user-supplied secret using a memory-hard KDF with
per-credential salt, tunable cost, and constant-time comparison.

## When to use and when NOT to use

- USE: password-based authentication, API key storage at rest, step-up
  credential verification.
- DO NOT USE: high-entropy machine-to-machine tokens (use `SignatureVerifier`
  or `TokenIntrospector`), short-lived OTP values (use `TotpVerifier`).
- DO NOT USE: session identifiers (see `SessionStore`).

## API surface

The catalog `api_signature` is authoritative; see `PasswordHasher.contract.json`.
The module ships two implementations:

- `Argon2idHasher` — production default. Requires `argon2-cffi`.
- `ScryptHasher` — stdlib-only fallback. Memory-hard per OWASP.

Both honor the same `PasswordHasher` Protocol: `hash`, `verify`, `needs_rehash`.

## Invariants

| ID | Rule |
|---|---|
| PWD_INV_01 | Stored verifier MUST encode algorithm identifier, cost parameters, salt, and digest so rotation is self-describing. |
| PWD_INV_02 | verify() MUST run in constant time with respect to digest bytes and NEVER branch on character-by-character equality. |
| PWD_INV_03 | Salt MUST be drawn from a CSPRNG, be at least 16 bytes, and MUST NEVER be reused across credentials. |
| PWD_INV_04 | hash() MUST use a memory-hard function (Argon2id or scrypt) and SHALL NEVER use raw SHA-2, MD5, or PBKDF2-SHA1. |
| PWD_INV_05 | needs_rehash() MUST return True when stored cost parameters are below the configured floor. |
| PWD_INV_06 | Plaintext MUST NEVER be logged, serialized, or included in exceptions raised by this primitive. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

Both hasher implementations are stateless between calls; every `hash()`
invocation generates a fresh salt from `secrets.token_bytes`. Concurrent
callers do not share mutable state. The `hashlib.scrypt` and `argon2-cffi`
primitives are safe to call from multiple threads.

## Operational characteristics (for SRE)

- Hashing is deliberately expensive; a single `hash()` call takes ≥10ms at
  the OWASP floor. Keep verify throughput under the CPU budget; rate-limit
  authentication endpoints via `RateLimiter`.
- Cost bump procedure: raise `cost_floor`, redeploy, call `needs_rehash()`
  on every successful login, and re-hash in the same request. The stored
  format is self-describing so old and new verifiers coexist.
- Failure mode: a call to `verify()` on a malformed stored value raises
  `PasswordHasherError` — surface as 401, never as 500.

## Security considerations

- Plaintext is never logged or surfaced in exceptions; PWD_INV_06 is
  enforced by redacting the value from every error path.
- Salts are drawn from `secrets.token_bytes` (CSPRNG). `random` is FORBIDDEN
  and is not imported at all.
- Comparisons use `hmac.compare_digest`. `==` on bytes is FORBIDDEN and
  does not appear in this module.
- Forbidden algorithm tags (`md5`, `sha1`, `sha256`, `pbkdf1`, `crypt`) are
  rejected by `parse_stored()` before any KDF runs; a downgrade attack that
  replaces the algorithm tag in a stored verifier surfaces as an error.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - OWASP ASVS 4.0.3 V2.4 Credential Storage Requirements.
  - NIST SP 800-63B §5.1.1.2 Memorized Secret Verifiers.
  - OWASP Top 10 2021 A02 Cryptographic Failures.

## Alternatives considered and rejected

- Per-tool bcrypt with hardcoded cost — drifts over time, blocks coordinated
  migration.
- Pluggable cryptography library passed as dependency — leaks algorithm
  choice into every call site.
- Database-side hashing via pgcrypto — couples auth to a specific data
  backend and loses constant-time verify.

## Extension contract

Downstream tools register alternative KDF adapters that implement the
Protocol. The adapter declares algorithm id, cost vector, and encoding
prefix. The registry refuses to bind an algorithm that lacks constant-time
verify or writable cost parameters.

## Usage

```python
def authenticate(email: str, plaintext: str, hasher: PasswordHasher, repo) -> bool:
    record = repo.get_credential(email)
    if record is None:
        return False
    if not hasher.verify(plaintext, record.digest):
        return False
    if hasher.needs_rehash(record.digest):
        repo.update_digest(email, hasher.hash(plaintext))
    return True
```

## Compose with:

- **Credential storage** → `SecretsVault` + `AuditEvent`
  Pepper is served from the vault; every verify emits an audit event — brute-force signals are immediate, not reconstructed.

- **Upgrade on login** → `AuthorizationCodeFlow` + `AuditEvent`
  When parameters are below the current baseline, the hasher rehashes on successful login — migration is lazy and leaves an audit trail.

- **Step-up readiness** → `TotpVerifier` + `WebAuthnAuthenticator`
  Password is never the only factor for sensitive scopes; the hasher is one leg of a multi-factor flow, not the whole story.
