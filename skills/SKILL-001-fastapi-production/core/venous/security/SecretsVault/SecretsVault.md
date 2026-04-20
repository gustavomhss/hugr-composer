# SecretsVault

## What it does (plain language)

SecretsVault is the single door every service uses to fetch, rotate, and
invalidate application secrets. It turns "where do I get the JWT signing
key?" into one call — `vault.get("jwt-signing-key")` — and takes care of
caching (so you don't hammer the KMS), rotation (so yesterday's key is no
longer the active one), and audit (so every access is recorded with the
caller identity). If the backing KMS goes down, cold reads **fail closed**
and warmed entries past TTL are **not served stale** — the vault tells the
caller the truth rather than pretending everything is fine.

## Purpose

Fetch, cache, rotate, and audit application secrets through a named-secret
interface backed by an external key management or secrets service.

## When to use and when NOT to use

- USE: any service that reads credentials, signing keys, API tokens, or
  database passwords from a shared source of truth.
- USE: places where you would otherwise scatter `os.environ` lookups with
  no rotation path and no audit trail.
- DO NOT USE: per-request session tokens (see `SessionStore`); CSRF tokens
  (see `CsrfGuard`); password verifiers (see `PasswordHasher`).
- DO NOT USE: as an encryption primitive — pair with `CryptoEnvelope` for
  at-rest encryption (vault gives you the key; envelope uses it).

## API surface

The catalog `api_signature` is authoritative; see
`SecretsVault.contract.json`. The module ships:

- `SecretsVault` — the `Protocol` everything depends on
  (`get`, `rotate`, `invalidate`).
- `CachingSecretsVault` — reference implementation with TTL-bounded cache,
  caller-identity audit, and scope enforcement.
- `InMemoryBackend` — reference `SecretBackend` for tests and dev.
- `register_aws_secrets_manager_backend` / `register_gcp_secret_manager_backend`
  / `register_azure_key_vault_backend` — lazy-import factories for cloud
  KMS adapters.

## Key terms

- **Secret name**: opaque handle (`"jwt-signing-key"`) that the backend
  resolves to live material.
- **Version**: monotonically increasing integer. `rotate()` advances it;
  `get()` returns the current version.
- **Audit event**: structured record emitted on every get / rotate /
  invalidate. Carries secret_name + caller_identity but NEVER the material.
- **Scope**: allow-list of secret names a caller identity may read.
  Undeclared identities are unrestricted; declared ones are explicit-allow.
- **Fail closed**: during a backend outage, unknown secrets raise instead
  of serving whatever happens to be in cache; cached entries past their
  TTL are also refused.

## Invariants

| ID | Rule |
|---|---|
| SV_INV_01 | Secret material MUST NEVER be logged, included in tracebacks, or serialized to telemetry. |
| SV_INV_02 | get() MUST honor a time-bounded cache; cached material MUST NEVER outlive not_after or the configured max-age. |
| SV_INV_03 | rotate() MUST produce a strictly increasing version and MUST NEVER return the same material for a different version. |
| SV_INV_04 | Every get()/rotate() call SHALL emit a structured audit event naming the secret (not the material) and the caller identity. |
| SV_INV_05 | When the underlying backend is unavailable, the vault MUST fail closed for cold secrets and CANNOT surface stale material past its cache TTL. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

`CachingSecretsVault` and `InMemoryBackend` are safe across threads: the
cache and backend both use a lock for the read-modify-write paths. The
caller identity is a `threading.local` — async callers MUST bind identity
inside the same task (a nested `with caller_identity(...)` block works
around event-loop coroutine switches).

## Operational characteristics (for SRE)

- Cache hit path is a dict lookup + two timestamp comparisons; p50 under
  1 µs per call.
- Cache miss path hits the backend (network-bound) + one lock acquisition
  + one audit emit. Bound the miss rate by tuning `max_age_s` per secret.
- Failure modes:
  - Backend outage → `SecretBackendUnavailableError` (SV-INV-05).
  - Scope violation → `SecretScopeError`; the offending secret NAME is
    withheld from the error text.
  - Unknown name → `SecretNotFoundError`.
  - Rotation returning non-monotonic version → `SecretsVaultError`.
- Rotation procedure: call `vault.rotate(name)`. Old cache entries are
  replaced atomically; subsequent `get()` sees the new version.
- Alert if `secrets_vault.backend.unavailable` > 0 for more than 60 s —
  the vault is correctly failing closed; callers are not getting secrets.

## Security considerations

- Secret material is NEVER placed in exceptions, log lines, or `repr()`.
  The `AuditEvent` dataclass has no `material` field by design.
- Secret names are printable-ASCII only. This keeps log lines safe and
  prevents names carrying control chars from bleeding into terminal
  sessions or grafana labels.
- Callers are bound to an identity via a context manager; the identity
  appears on every audit event. Anonymous calls are allowed but flagged.
- Scope enforcement is allow-list only — a declared scope that omits a
  name denies access; an undeclared caller is unrestricted. Declare scopes
  for every production identity.
- Plaintext material returned by `get()` is an immutable `bytes`. Callers
  that need zeroization should allocate a `bytearray`, copy the material
  into it, and pass it to `zeroize()` when done.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - OWASP ASVS 4.0.3 V6.4 Secret Management.
  - NIST SP 800-63B §5.1.1.2 — authenticator secret protection.

## Alternatives considered and rejected

- Env vars injected at deploy — no rotation, no audit, leaks into crash
  dumps.
- Per-service SDK call — inconsistent caching and blast-radius controls.
- Encrypted config file checked into repo — key management problem
  reappears one level down.

## Extension contract

Backends register as vault adapters implementing the `SecretBackend`
Protocol. An adapter is refused if it cannot produce a monotonically
increasing version identifier or does not support rotation callbacks
(`validate_adapter` enforces this at registration time). To add a new
backend, implement `fetch(name) -> (version, material, not_after)` and
`rotate(name) -> (version, material, not_after)` — the vault layers its
cache + audit on top.

## Usage

```python
from SecretsVault import (
    CachingSecretsVault, InMemoryAuditSink, InMemoryBackend, caller_identity,
)

backend = InMemoryBackend()
backend.register("jwt-signing-key", b"initial-jwt-material")

audit = InMemoryAuditSink()  # in production: wire structlog/OTel logger.
vault = CachingSecretsVault(backend, audit=audit, max_age_s=300.0)
vault.declare_scope("auth-service", {"jwt-signing-key"})


def load_signing_key(v):
    with caller_identity("auth-service"):
        version = v.get("jwt-signing-key")
    return version.material, version.version
```

## Compose with:

- **Zero-secret deploys** → `KeyRotationSchedule` + `AuditEvent`
  Secrets never enter the image; rotation is a vault event with an audit trail — credential churn is ops, not redeploy.

- **Signing + envelope keys** → `CryptoEnvelope` + `SignatureVerifier`
  KMS keys front data-encryption and signing; application code sees named secrets, not raw material.

- **Graceful provider loss** → `CircuitBreaker` + `LifecycleHook`
  Startup hooks warm caches; a breaker fails fast on vault outages with bounded-stale material — outages degrade, not down.
