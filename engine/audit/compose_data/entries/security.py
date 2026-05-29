"""WP-17 — curated compose-data entries for the `security` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === security`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== security
    "ContentSecurityPolicy": (
        "Compose, serialize, and enforce a Content Security Policy header that constrains script, style, frame, and connect sources.",
        ["CorsPolicy", "CsrfGuard", "OutputEncoder", "RouterPipeline"],
        [
            (
                "Defense-in-depth rendering",
                ["OutputEncoder", "CorsPolicy"],
                "Encoder neutralizes inline injections; CSP blocks anything that slips through at the browser; CORS limits who can even reach the endpoint.",
            ),
            (
                "Report + enforce",
                ["AuditEvent", "StructuredLogger"],
                "Report-only rollout logs violations; enforce mode blocks; the transition is a policy-version bump, not a code change.",
            ),
            (
                "Trusted types",
                ["OutputEncoder", "InputValidator"],
                "CSP requires typed sinks; encoder and validator are the only ways to produce them — raw string → DOM is a compile-time error.",
            ),
        ],
    ),
    "CryptoEnvelope": (
        "Encrypt and decrypt payloads with authenticated encryption, key-id-tagged ciphertext, and deterministic nonce discipline.",
        ["KeyRotationSchedule", "SecretsVault", "SignatureVerifier", "EncryptionPolicy"],
        [
            (
                "Encrypt-then-sign",
                ["SignatureVerifier", "SecretsVault"],
                "Envelope seals the payload; signer binds it to a key; verifier rejects tampering — the two primitives cover confidentiality and integrity in order.",
            ),
            (
                "Versioned ciphertext",
                ["KeyRotationSchedule", "EncryptionPolicy"],
                "Key version rides with the ciphertext; rotation installs a new DEK without re-encrypting old records — overlap makes migration lazy and safe.",
            ),
            (
                "Compliance-grade at-rest",
                ["DataResidencyPolicy", "PiiClassification"],
                "Sensitive classes traverse the envelope before storage; residency policy chooses the KMS — 'encrypted with the right key in the right region' is mechanical.",
            ),
        ],
    ),
    "CsrfGuard": (
        "Bind state-changing HTTP requests to the authenticated session through per-session tokens validated on the server side.",
        ["SessionStore", "CorsPolicy", "RequestGuard", "ContentSecurityPolicy"],
        [
            (
                "Browser write safety",
                ["SessionStore", "CorsPolicy"],
                "Session cookie + CSRF token together authorize state change; neither alone is sufficient — cross-origin forgery requires both to leak.",
            ),
            (
                "Pipeline-mounted",
                ["RouterPipeline", "RequestGuard"],
                "The browser pipeline mounts CSRF uniformly; individual handlers never remember to call it — one seam, one audit.",
            ),
            (
                "Defense in depth",
                ["ContentSecurityPolicy", "AuditEvent"],
                "CSP prevents token exfil; CSRF prevents forgery; every rejection audits the principal — three layers, one decision.",
            ),
        ],
    ),
    "InputValidator": (
        "Parse and constrain inbound payloads against a declared schema with typed coercion, length/range caps, and rejection reasons.",
        ["ValueTransform", "OutputEncoder", "ValueObject", "RequestGuard"],
        [
            (
                "Parse-don't-validate",
                ["ValueTransform", "ValueObject"],
                "Schema coercion produces typed value objects; the domain never sees a dict — invalid shapes are unrepresentable past the validator.",
            ),
            (
                "Round-trip safety",
                ["OutputEncoder", "ContentSecurityPolicy"],
                "Inbound validation + outbound encoding form the canonical-form contract; XSS and smuggling are closed at both edges.",
            ),
            (
                "Authorization-ready",
                ["RequestGuard", "CurrentPrincipal"],
                "Validated payloads carry principal-scoped identifiers; the guard authorizes the typed action, not the raw request.",
            ),
        ],
    ),
    "OutputEncoder": (
        "Encode untrusted values for a named sink using sink-specific escaping rules per OWASP ASVS V5.3 and CheatSheet guidance.",
        ["InputValidator", "ContentSecurityPolicy", "PiiClassification", "ValueTransform"],
        [
            (
                "Sink-aware escaping",
                ["ContentSecurityPolicy", "InputValidator"],
                "HTML, JS, URL, and CSS sinks each have their encoder; CSP enforces that untyped strings never reach the DOM.",
            ),
            (
                "PII-masked output",
                ["PiiClassification", "AccessLog"],
                "Classification-driven mask runs before encoding; the access log records what was seen by whom — 'PII leaked because the encoder forgot' is prevented structurally.",
            ),
            (
                "Round-trip contract",
                ["InputValidator", "ValueTransform"],
                "Inbound parse and outbound encode share canonical forms; the service's on-the-wire vocabulary is tight by construction.",
            ),
        ],
    ),
    "PasswordHasher": (
        "Derive a verifier from a user-supplied secret using a memory-hard KDF with per-credential salt and tunable cost parameters.",
        ["SecretsVault", "AuditEvent", "TotpVerifier", "AuthorizationCodeFlow"],
        [
            (
                "Credential storage",
                ["SecretsVault", "AuditEvent"],
                "Pepper is served from the vault; every verify emits an audit event — brute-force signals are immediate, not reconstructed.",
            ),
            (
                "Upgrade on login",
                ["AuthorizationCodeFlow", "AuditEvent"],
                "When parameters are below the current baseline, the hasher rehashes on successful login — migration is lazy and leaves an audit trail.",
            ),
            (
                "Step-up readiness",
                ["TotpVerifier", "WebAuthnAuthenticator"],
                "Password is never the only factor for sensitive scopes; the hasher is one leg of a multi-factor flow, not the whole story.",
            ),
        ],
    ),
    "SecretsVault": (
        "Fetch, cache, rotate, and audit application secrets through a named-secret interface backed by an external provider.",
        ["KeyRotationSchedule", "CryptoEnvelope", "SignatureVerifier", "AuditEvent"],
        [
            (
                "Zero-secret deploys",
                ["KeyRotationSchedule", "AuditEvent"],
                "Secrets never enter the image; rotation is a vault event with an audit trail — credential churn is ops, not redeploy.",
            ),
            (
                "Signing + envelope keys",
                ["CryptoEnvelope", "SignatureVerifier"],
                "KMS keys front data-encryption and signing; application code sees named secrets, not raw material.",
            ),
            (
                "Graceful provider loss",
                ["CircuitBreaker", "LifecycleHook"],
                "Startup hooks warm caches; a breaker fails fast on vault outages with bounded-stale material — outages degrade, not down.",
            ),
        ],
    ),
    "SignatureVerifier": (
        "Verify HMAC / Ed25519 / ECDSA signatures with domain separation, pinned trust anchors, and constant-time comparison.",
        ["CryptoEnvelope", "SecretsVault", "IdempotentConsumer", "AuditEvent"],
        [
            (
                "Webhook authentication",
                ["IdempotentConsumer", "AuditEvent"],
                "Incoming webhooks are verified, then dedup'd — replay attacks lose on signature freshness and on idempotency at the same time.",
            ),
            (
                "Encrypt-then-sign",
                ["CryptoEnvelope", "SecretsVault"],
                "Envelope protects confidentiality; verifier binds the ciphertext to a trusted key — tampering is detected before decryption is even attempted.",
            ),
            (
                "Key rotation survival",
                ["KeyRotationSchedule", "SecretsVault"],
                "Old kids keep verifying through the overlap window; the verifier never fetches a key from the message it is verifying.",
            ),
        ],
    ),
}
