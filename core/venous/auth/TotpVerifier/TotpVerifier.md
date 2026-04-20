# TotpVerifier

## What it does (plain language)

TotpVerifier is the shared MFA primitive for six-digit time-based one-time
passwords (the rolling codes users read from Google Authenticator, Authy,
1Password, etc.). It generates provisioning URIs for enrollment and verifies
submitted codes per RFC 6238 — with constant-time comparison, a bounded
clock-skew window, and replay-step tracking so a code is accepted at most
once per user.

## Purpose

Generate and verify six-digit time-based one-time passwords per RFC 6238 with
constant-time comparison, clock-skew tolerance, and replay prevention.

## When to use and when NOT to use

- USE: MFA step-up on login, sensitive actions (payouts, email changes), or
  any second factor where the user already has an authenticator app.
- DO NOT USE: high-assurance authentication — prefer `WebAuthnAuthenticator`
  (passkeys) for that use case; TOTP is phishable.
- DO NOT USE: SMS or email delivery — TOTP is the authenticator-app factor;
  SMS-OTP is a different (and deprecated) primitive.

## API surface

The catalog `api_signature` in `TotpVerifier.contract.json` is authoritative.
The `verify()` method returns the `int` step number the caller MUST persist
(`user.last_totp_step = step`); the next call MUST pass that integer back
through `last_used_step` or the primitive cannot detect a cross-request
replay.

```python
def confirm_mfa(totp: TotpVerifier, user, submitted_code: str) -> None:
    next_step = totp.verify(
        secret=user.totp_secret,
        code=submitted_code,
        last_used_step=user.last_totp_step,
    )
    user.last_totp_step = next_step
    repo.save(user)
```

## Invariants

| ID | Rule |
|---|---|
| TOTP_INV_01 | Shared secrets MUST be >=160 bits drawn from a CSPRNG; the verifier REJECTS shorter secrets and NEVER transmits secret material outside the enrollment channel. |
| TOTP_INV_02 | `verify()` MUST compare codes in constant time via `hmac.compare_digest` and SHALL NEVER short-circuit on prefix match. |
| TOTP_INV_03 | Accepted clock skew MUST be bounded to +/-1 step (+/-30s); larger windows CANNOT be configured through the public surface. |
| TOTP_INV_04 | A successfully used step number MUST be recorded and the same step CANNOT be accepted again for the same secret; replay attempts SHALL be rejected. |
| TOTP_INV_05 | Codes SHALL be six decimal digits per RFC 4226; alternative digit counts MUST be explicitly opted in via `allow_nonstandard_digits=True`. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## State machine (for TOTP_INV_04)

The reference implementation models the "used-steps set" described in the
TLA+ spec (`TotpVerifier.tla`). For each secret the verifier maintains an
in-memory set of `(secret_fingerprint, step)` pairs so concurrent verify
calls within the same process cannot both win. The caller ALWAYS supplies
the persisted `last_used_step`, which is authoritative across restarts and
shared deployments.

- States: `clock in Steps`, `used \subseteq Steps`, `last_persisted in Steps U {-1}`.
- Safety (machine-checked): `ReplayFree == \forall s in used: s <= last_persisted`.
- Skew (machine-checked): any accepted `s` satisfies `|s - clock| <= MaxSkew = 1`.

## Thread and async safety

- `StandardTotpVerifier.verify` serialises the in-memory replay cache behind
  a lock. The constant-time `hmac.compare_digest` loop runs outside the lock
  because the HOTP derivation is pure.
- Concurrent calls from 32+ threads with the SAME `(secret, code)` produce
  exactly one winner (TOTP_INV_04).
- Different secrets are independent — no cross-secret interference.

## Operational characteristics (for SRE)

- Self-observability: `totp.verify.total` (counter, `result` label),
  `totp.replay.rejections` (counter, `result` label),
  `totp.verify.duration` (histogram, ms).
- A sustained rise in `totp.replay.rejections` is either a user reusing a
  code (benign) or a replay attack (incident). Alert if
  `replay.rejections / verify.total > 0.1` over 5 minutes.
- No I/O at import. The primitive is safe to construct per request or per
  process.

## Security considerations

- Secrets MUST be persisted encrypted at rest. The primitive NEVER logs the
  raw secret; the in-memory replay cache uses a SHA-256 fingerprint.
- `provision_uri` encodes the secret as base32 per RFC 6238; transmit the
  resulting URI only over the enrollment channel (HTTPS-authenticated
  account page, never email).
- `verify()` does not return information that discloses where in the +/-1
  window the match occurred; the candidate loop iterates over every step
  and only returns the matched step after processing all three.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - RFC 6238 — TOTP: Time-Based One-Time Password Algorithm, Sections 4-5.
  - NIST SP 800-63B — Section 5.1.4 Single-Factor OTP.
  - OWASP ASVS 4.0.3 — V2.8 One Time Verifier Requirements.

## Alternatives considered and rejected

- SMS OTP only — phishable and deprecated for high-assurance in SP 800-63B.
- Email magic link — couples MFA to mailbox security and adds latency.
- Per-service TOTP library call — no shared replay protection; each team
  reinvents the `last_used_step` check and the skew window.

## Extension contract

Alternative TOTP schemes (SHA-256, 8-digit codes, custom step sizes) register
as verifier adapters through `TotpAdapterRegistry`. Every adapter MUST
implement the Protocol AND declare its digest + period. The registry
REJECTS adapters that cannot produce a step number from `verify()` — replay
persistence is not optional.

## Schema of `TotpVerifier.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from TotpVerifier import StandardTotpVerifier, generate_secret

# Enrollment
secret = generate_secret()               # 160-bit CSPRNG secret
totp = StandardTotpVerifier()
uri = totp.provision_uri(
    account="alice@example.com",
    issuer="Acme Corp",
    secret=secret,
)
# render `uri` as a QR code; user scans into their authenticator app

# Verification
def confirm(user, submitted: str) -> None:
    step = totp.verify(
        secret=user.totp_secret,
        code=submitted,
        last_used_step=user.last_totp_step,
    )
    user.last_totp_step = step
```

## Compose with:

- **MFA step-up** → `AuthorizationCodeFlow` + `AuditEvent`
  After primary auth, TOTP gate gates sensitive scopes; every success and every failed attempt is audited for velocity detection.

- **Seed custody** → `SecretsVault` + `PasswordHasher`
  TOTP seeds are stored in the vault, never alongside the password hash — compromise of the credential store does not auto-compromise 2FA.

- **Replay lockout** → `AuditEvent` + `RateLimiter`
  A counter is marked used on success; repeated failures rate-limit the subject and emit a high-severity audit event.
