"""WP-17 — curated compose-data entries for the `auth` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === auth`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== auth
    "AuthorizationCodeFlow": (
        "Execute the OAuth 2.0 authorization-code grant with PKCE, enforcing state, nonce, redirect URI pinning, and single-use code exchange.",
        ["SessionStore", "TokenIntrospector", "CurrentPrincipal", "SecretsVault"],
        [
            (
                "Login handshake",
                ["SessionStore", "CurrentPrincipal"],
                "Successful code exchange mints a server-side session and resolves the principal — the access token never leaks to the browser.",
            ),
            (
                "Confidential client",
                ["SecretsVault", "TokenIntrospector"],
                "Client secret is fetched from the vault at exchange time, never baked into config; issued tokens are later introspected via the same trust chain.",
            ),
            (
                "Step-up to MFA",
                ["TotpVerifier", "WebAuthnAuthenticator"],
                "The flow hands off to a second-factor primitive before session elevation — the code grant alone is never sufficient for sensitive scopes.",
            ),
        ],
    ),
    "CurrentPrincipal": (
        "Read-only view of the authenticated identity for the active request, including subject id, tenant, roles, and auth method.",
        ["RequestGuard", "SessionStore", "TokenIntrospector", "RequestContext"],
        [
            (
                "Authn → authz handoff",
                ["SessionStore", "RequestGuard"],
                "SessionStore (or TokenIntrospector) produces the principal once; RequestGuard reads it as an immutable snapshot — no handler re-derives identity.",
            ),
            (
                "Auditable actor",
                ["AuditEvent", "AccessLog"],
                "Every audit and access record carries the principal id and auth method verbatim, so forensic trails never have to reconstruct 'who was logged in at the time'.",
            ),
            (
                "Per-tenant context",
                ["RequestContext", "RequestGuard"],
                "The principal includes tenant id; downstream authorization is scoped to that tenant — cross-tenant reads are a policy decision, not an oversight.",
            ),
        ],
    ),
    "RequestGuard": (
        "Enforce declarative, composable authorization: one decision point per route, audited centrally, with explicit allow/deny and no silent defaults.",
        ["CurrentPrincipal", "AuditEvent", "MiddlewarePipeline", "FeatureToggle"],
        [
            (
                "Route-level ABAC",
                ["CurrentPrincipal", "AuditEvent"],
                "Guard evaluates attributes of principal + resource and emits an audit event for every deny — 'who tried what and was refused' is never silent.",
            ),
            (
                "Feature-gated rollout",
                ["FeatureToggle", "CurrentPrincipal"],
                "A guard can require a toggle to be on for the caller's cohort; disabled cohorts see 404, not 403 — reducing feature-flag fingerprinting.",
            ),
            (
                "Pipeline-scoped policy",
                ["MiddlewarePipeline", "RouterPipeline"],
                "The guard is mounted once on the pipeline; routes inherit the policy — individual handlers cannot forget to call it.",
            ),
        ],
    ),
    "SessionStore": (
        "Issue, rotate, and revoke server-side session records keyed by high-entropy identifiers, with fixation protection and absolute/idle timeouts.",
        ["CurrentPrincipal", "CsrfGuard", "AuthorizationCodeFlow", "AuditEvent"],
        [
            (
                "Browser session",
                ["CsrfGuard", "CurrentPrincipal"],
                "Session id is httpOnly + secure; CsrfGuard binds state-changing requests to the same session — a stolen cookie alone is not sufficient for POST.",
            ),
            (
                "Rotation on privilege change",
                ["AuthorizationCodeFlow", "AuditEvent"],
                "Every login, MFA step-up, and logout rotates the session id and writes an audit event — fixation and replay are detectable on the timeline.",
            ),
            (
                "Revocation fan-out",
                ["AuditEvent", "BreachNotificationQueue"],
                "Security incident closes all sessions of impacted subjects and opens a breach incident with the actor list — containment and compliance in one stroke.",
            ),
        ],
    ),
    "TokenIntrospector": (
        "Validate access tokens by signature, issuer, audience, expiry, and not-before claims, with optional revocation check via RFC 7662.",
        ["SignatureVerifier", "CurrentPrincipal", "SecretsVault", "RequestGuard"],
        [
            (
                "Verify-then-admit",
                ["SignatureVerifier", "CurrentPrincipal"],
                "Signature verification precedes claim extraction; only after the full claim set is validated is a CurrentPrincipal published — no partial trust.",
            ),
            (
                "Rotating JWKS",
                ["SecretsVault", "KeyRotationSchedule"],
                "Signing keys come from the vault on a rotation cadence; overlap windows let old tokens verify until expiry without a big-bang cutover.",
            ),
            (
                "Opaque-token fallback",
                ["RequestGuard", "CircuitBreaker"],
                "RFC 7662 introspection sits behind a breaker so an IdP outage degrades to cached introspection rather than blanket denial.",
            ),
        ],
    ),
    "TotpVerifier": (
        "Generate and verify six-digit time-based one-time passwords per RFC 6238 with constant-time comparison and replay tracking per counter.",
        ["PasswordHasher", "AuthorizationCodeFlow", "AuditEvent", "SecretsVault"],
        [
            (
                "MFA step-up",
                ["AuthorizationCodeFlow", "AuditEvent"],
                "After primary auth, TOTP gate gates sensitive scopes; every success and every failed attempt is audited for velocity detection.",
            ),
            (
                "Seed custody",
                ["SecretsVault", "PasswordHasher"],
                "TOTP seeds are stored in the vault, never alongside the password hash — compromise of the credential store does not auto-compromise 2FA.",
            ),
            (
                "Replay lockout",
                ["AuditEvent", "RateLimiter"],
                "A counter is marked used on success; repeated failures rate-limit the subject and emit a high-severity audit event.",
            ),
        ],
    ),
    "TokenIntrospectorX": (
        "",
        [],
        [],
    ),  # placeholder removed
    "WebAuthnAuthenticator": (
        "Register and assert passkey credentials per the Web Authentication API, binding credentials to an RP id with origin and counter checks.",
        ["AuthorizationCodeFlow", "SessionStore", "SecretsVault", "AuditEvent"],
        [
            (
                "Passwordless login",
                ["SessionStore", "AuditEvent"],
                "A valid assertion mints a rotated session and audits the credential id and authenticator AAGUID — phishing-resistant primary auth.",
            ),
            (
                "Step-up without prompts",
                ["AuthorizationCodeFlow", "SessionStore"],
                "Platform authenticators allow silent step-up — the same user presence gesture satisfies MFA without an OTP round-trip.",
            ),
            (
                "Credential recovery",
                ["SecretsVault", "AuditEvent"],
                "Recovery keys are stored in the vault with per-use alerting; any recovery is an auditable out-of-band event, not a silent fallback.",
            ),
        ],
    ),
}
