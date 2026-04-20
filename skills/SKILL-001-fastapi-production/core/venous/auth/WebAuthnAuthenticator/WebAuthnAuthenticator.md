# WebAuthnAuthenticator

## What it does (plain language)

WebAuthnAuthenticator is the FIDO2 passkey ceremony primitive. It issues a
single-use cryptographic challenge, verifies the authenticator's response
against the configured RP ID and origin, enforces user-verification when the
credential was registered as user-verifying, and detects cloned authenticators
by rejecting any sign-count that regresses. It is the one place in the code
where every passkey onboarding and login passes through — no service invents
its own broken variant.

## Purpose

Register and assert passkey credentials per the Web Authentication API,
binding credentials to an RP ID and verifying attestation, challenge, origin,
and signature counter.

## When to use and when NOT to use

- USE: any user-facing login that accepts passkeys or security keys; any
  step-up authentication backed by a FIDO2 credential.
- DO NOT USE: server-to-server auth (use the mTLS / OIDC primitives instead).
- DO NOT USE: password fallback. WebAuthn replaces phishable shared secrets;
  do not wrap it around a password check.

## API surface

The catalog `api_signature` in `WebAuthnAuthenticator.contract.json` is the
authority. Callers:

1. `begin_registration(user_id, user_name)` — returns options to hand to the
   browser; the primitive issues and tracks the challenge.
2. `finish_registration(challenge, response)` — validates origin, RP ID hash,
   UP / UV flags, then binds the new credential to the user.
3. `begin_assertion(credential_ids)` — returns options for the login ceremony.
4. `finish_assertion(challenge, response, stored_public_key, stored_sign_count)`
   — runs WEBAUTHN-INV-02, -03, -05, -06 and enforces WEBAUTHN-INV-04 counter
   monotonicity. Returns the new sign_count that the RP MUST persist.

## Invariants

| ID | Rule |
|---|---|
| WEBAUTHN_INV_01 | Challenges MUST be >=16 bytes from a CSPRNG and MUST be single-use; replaying a challenge SHALL reject the response. |
| WEBAUTHN_INV_02 | The origin in clientDataJSON MUST exactly match the configured RP origin; subdomain or scheme mismatch CANNOT be accepted. |
| WEBAUTHN_INV_03 | The RP ID hash in authenticatorData MUST equal SHA-256(rp_id); mismatch MUST fail verification. |
| WEBAUTHN_INV_04 | finish_assertion() MUST reject when the new sign_count is <= the stored sign_count, except when the authenticator always returns 0. |
| WEBAUTHN_INV_05 | The user-verification flag MUST be enforced for authenticators registered as user-verifying; absence SHALL fail the assertion. |
| WEBAUTHN_INV_06 | Credential public keys MUST be stored bound to (user_id, credential_id) and NEVER shared across users. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `ChallengeStore` serialises `issue()` / `consume()` under a single lock so
  concurrent replay attempts see exactly one winner.
- `CredentialStore` serialises `register()` / `get()` / `update_sign_count()`
  under a single lock; cross-user re-binding is rejected atomically.
- `ReferenceWebAuthnAuthenticator` itself is stateless aside from those two
  stores, so multiple workers SHOULD share one instance per RP rather than
  constructing per-request.

## Operational characteristics (for SRE)

- CSPRNG: `secrets.token_bytes(32)` — 256 bits of entropy, well above the
  WEBAUTHN-INV-01 lower bound of 128 bits.
- Failure mode: every rejection raises `WebAuthnInvariantError` with the
  invariant ID in the message; log the exception and return HTTP 400.
- Self-observability: `webauthn.registrations`, `webauthn.assertions`,
  `webauthn.assertion.latency`, `webauthn.counter.regressions`. A sustained
  rise in `counter.regressions` is the primary symptom of cloned
  authenticators in the wild — page on-call.

## Security considerations

- The origin check is byte-identity equality. Any normalization (lowercasing,
  trailing-slash collapse, port stripping) would widen the attack surface;
  explicitly FORBIDDEN.
- The sign-count special case (authenticator always returns 0) matches the
  WebAuthn spec. Downstream policies MAY tighten this by refusing all zero
  counters for credentials registered with AAGUIDs known to implement real
  counters — configure via the attestation-statement verifier registry.
- The public key carried in `stored_public_key` MUST come from the server's
  own credential store, NEVER from the client response. The primitive
  additionally cross-checks with its registered binding to defend against
  call-site mistakes (WEBAUTHN_INV_06).
- Attestation format verifiers plug in through the extension contract
  (packed, fido-u2f, tpm, android-key, apple). Each verifier MUST return an
  AAGUID and a trust path rooted in a configured FIDO Metadata Service.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - W3C WebAuthn Level 3 Recommendation — Section 7.1 Registering a New
    Credential; Section 7.2 Verifying an Authentication Assertion.
  - OWASP ASVS 4.0.3 — V2.7 Out of Band Verifier Requirements; V2.9
    Cryptographic Software and Devices.

## Alternatives considered and rejected

- Vendor SDK per platform — fragments RP ID policy and challenge storage.
- Delegate to hosted passkey provider — loses control of credential export
  and silent migration.
- Stay on TOTP — retains the phishable shared-secret model the FIDO stack
  replaces.

## Extension contract

Attestation formats register as attestation-statement verifiers (packed,
fido-u2f, tpm, android-key, apple) implementing a verifier Protocol. The
registry refuses to bind a statement type unless it returns an AAGUID and a
trust path rooted in a configured metadata service.

## Schema of `WebAuthnAuthenticator.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
auth = ReferenceWebAuthnAuthenticator(
    rp_id="passkeys.example.com",
    origin="https://passkeys.example.com",
)

# Registration
opts = auth.begin_registration(user_id=b"alice", user_name="alice")
result = auth.finish_registration(challenge=opts["challenge"], response=browser_response)
persist(result.credential_id, result.public_key, result.sign_count)

# Login
opts = auth.begin_assertion([stored_credential_id])
new_count = auth.finish_assertion(
    challenge=opts["challenge"],
    response=browser_response,
    stored_public_key=db.public_key_for(user_id, stored_credential_id),
    stored_sign_count=db.sign_count_for(stored_credential_id),
)
db.update_sign_count(stored_credential_id, new_count)
```

## Compose with:

- **Passwordless login** → `SessionStore` + `AuditEvent`
  A valid assertion mints a rotated session and audits the credential id and authenticator AAGUID — phishing-resistant primary auth.

- **Step-up without prompts** → `AuthorizationCodeFlow` + `SessionStore`
  Platform authenticators allow silent step-up — the same user presence gesture satisfies MFA without an OTP round-trip.

- **Credential recovery** → `SecretsVault` + `AuditEvent`
  Recovery keys are stored in the vault with per-use alerting; any recovery is an auditable out-of-band event, not a silent fallback.
