"""One-shot builder for §B1.1 (engine/primitives_by_concern.yaml) and §B1.2
(append `## Compose with:` section to each production primitive `.md`).

Data is curated in this file: a senior-engineer call on which 2-5 siblings
each primitive naturally pairs with, plus 3 concrete composition patterns
per .md.

Run once:
    python -m engine.audit._build_compose
"""

from __future__ import annotations

import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS = SKILL_ROOT / "core" / "venous"
REGISTRY = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"


# ---------------------------------------------------------------------------
# Concern mapping  (namespace → concern, with data split)
# ---------------------------------------------------------------------------
# Fixed taxonomy: auth, data.persistence, data.modelling, data.schema,
# events, observability, resiliency, security, compliance, policy, llm,
# cost, jobs, cache, api, flags, extras.

CONCERN_BY_NS = {
    "api": "api",
    "auth": "auth",
    "cache": "cache",
    "compliance": "compliance",
    "events": "events",
    "extras": "extras",
    "flags": "flags",
    "jobs": "jobs",
    "llm": "llm",
    "obs": "observability",
    "policy": "policy",
    "resiliency": "resiliency",
    "security": "security",
}

# Data namespace splits across persistence / modelling / schema.
DATA_CONCERN = {
    # data.persistence — storage mechanics, transaction semantics, caching
    "Repository": "data.persistence",
    "UnitOfWork": "data.persistence",
    "IdentityMap": "data.persistence",
    "DataMapper": "data.persistence",
    "TransactionalBatch": "data.persistence",
    "ChangeDataCapture": "data.persistence",
    "MaterializedView": "data.persistence",
    # data.modelling — DDD tactical/strategic patterns
    "Aggregate": "data.modelling",
    "ValueObject": "data.modelling",
    "Specification": "data.modelling",
    "BoundedContext": "data.modelling",
    "AntiCorruptionLayer": "data.modelling",
    # data.schema — typed bindings, classification, wiring
    "ConfigBinding": "data.schema",
    "DiContainer": "data.schema",
    "LifetimeScope": "data.schema",
    "PiiClassification": "data.schema",
    "LegalHold": "data.schema",
}


# ---------------------------------------------------------------------------
# Curated purpose + compose_with + compose patterns per primitive
# ---------------------------------------------------------------------------
#
# Entry shape:
#   (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
# ---------------------------------------------------------------------------

E: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== api
    "CommandQuerySeparator": (
        "Partitions the API into write commands that mutate state and read queries that observe it so each side evolves independently.",
        ["RouterPipeline", "MiddlewarePipeline", "RequestContext", "ValueTransform"],
        [
            (
                "Write-side pipeline",
                ["RouterPipeline", "MiddlewarePipeline", "ValueTransform"],
                "Commands flow through a write-only router group whose middleware enforces validation and UoW boundaries before any handler runs.",
            ),
            (
                "Read-side projection",
                ["RouterPipeline", "RequestContext"],
                "Queries ride a distinct pipeline carrying only the caller's principal and correlation context, so read paths never inherit write-side transactions.",
            ),
            (
                "Typed command coercion",
                ["ValueTransform", "RequestContext"],
                "Inbound payloads are coerced to typed command DTOs before the domain sees them; RequestContext captures the caller identity for authorization, never raw storage args.",
            ),
        ],
    ),
    "ContextMap": (
        "Catalogs every BoundedContext and the integration relationship so upstream/downstream teams agree on a single translation contract.",
        ["BoundedContext", "AntiCorruptionLayer", "OutboundBinding", "DomainEvent"],
        [
            (
                "Customer/supplier integration",
                ["BoundedContext", "AntiCorruptionLayer"],
                "ContextMap declares the relationship; the ACL enforces it at runtime so upstream vocabulary never leaks into the downstream model.",
            ),
            (
                "Published-language contract",
                ["DomainEvent", "OutboundBinding"],
                "The map names which contexts publish vs consume domain events; OutboundBinding is the single adapter surface honoring that direction.",
            ),
            (
                "Conformist drift detection",
                ["BoundedContext", "AntiCorruptionLayer"],
                "When an upstream context changes its schema, the ACL is the one seam that fails fast — the context map tells you which downstream teams to page.",
            ),
        ],
    ),
    "MiddlewarePipeline": (
        "Ordered chain of components that each transform the RequestContext and decide whether to call the next stage or short-circuit the response.",
        ["RouterPipeline", "RequestContext", "RequestGuard", "CorrelationContext"],
        [
            (
                "Edge security chain",
                ["RequestGuard", "CsrfGuard", "RequestContext"],
                "Authn → authz → CSRF runs in a fixed order; downstream handlers receive a RequestContext already stamped with principal and verified origin.",
            ),
            (
                "Observability wrapping",
                ["CorrelationContext", "StructuredLogger", "Tracer"],
                "The outermost middleware stamps a correlation id and opens the root span so every log line and child span in the pipeline is automatically joined.",
            ),
            (
                "Resiliency envelope",
                ["TimeoutBudget", "LoadShedder", "CircuitBreaker"],
                "Pipeline entry computes the deadline and enqueues the request under a priority class; inner middleware inherits the remaining budget — no handler gets more time than the ingress contract promised.",
            ),
        ],
    ),
    "RequestContext": (
        "Per-request bag that carries identity, headers, correlation id, and free-form assigns through the handler chain.",
        ["MiddlewarePipeline", "CurrentPrincipal", "CorrelationContext", "RequestShape"],
        [
            (
                "Principal propagation",
                ["CurrentPrincipal", "RequestGuard"],
                "Authn middleware resolves the principal once and stamps the context; downstream RequestGuard reads the same frozen identity — no re-validation, no drift.",
            ),
            (
                "Cross-cutting correlation",
                ["CorrelationContext", "StructuredLogger"],
                "Every log line emitted inside a handler inherits the request's correlation id via the context, so a single grep stitches the whole call graph.",
            ),
            (
                "Deadline-aware handlers",
                ["RequestShape", "TimeoutBudget"],
                "The context carries the remaining budget and priority class; handlers query it before issuing downstream calls rather than racing an invisible timer.",
            ),
        ],
    ),
    "RouterPipeline": (
        "Named bundle of middleware that a route joins with `pipe_through` so groups share edge policy without re-declaring it.",
        ["MiddlewarePipeline", "CommandQuerySeparator", "RequestGuard", "CorsPolicy"],
        [
            (
                "Browser vs API split",
                ["MiddlewarePipeline", "CsrfGuard", "CorsPolicy"],
                "The 'browser' pipeline enforces CSRF and session cookies; the 'api' pipeline enforces bearer tokens and CORS — one route cannot accidentally inherit the wrong edge.",
            ),
            (
                "Read/write separation",
                ["CommandQuerySeparator", "MiddlewarePipeline"],
                "Query pipelines skip UoW and write-locks; command pipelines mount them — the router is the single place this contract lives.",
            ),
            (
                "Tenanted edge",
                ["RequestGuard", "CurrentPrincipal"],
                "Per-tenant pipelines stamp tenant id into the context before authorization runs, so downstream handlers never need to re-extract it from headers.",
            ),
        ],
    ),
    "ValueTransform": (
        "Strongly-typed parse/validate step that converts a raw inbound argument into the domain type or rejects the request with a precise error.",
        ["InputValidator", "RequestContext", "MiddlewarePipeline", "ValueObject"],
        [
            (
                "Schema-to-domain coercion",
                ["InputValidator", "ValueObject"],
                "Raw JSON is validated by the schema then coerced into frozen value objects before the handler sees it — domain code never touches a dict.",
            ),
            (
                "Typed path/query params",
                ["MiddlewarePipeline", "RequestContext"],
                "Each route declares transforms for its params; a failure raises one well-typed exception the pipeline maps to 400 — handlers never check types.",
            ),
            (
                "Canonical on-the-wire",
                ["InputValidator", "OutputEncoder"],
                "Inbound ValueTransform + outbound OutputEncoder form a round-trip contract: the same canonical form crosses the edge in both directions.",
            ),
        ],
    ),
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
    # ======================================================== cache
    "DistributedLock": (
        "Give workers a single contract for rare, sequential, cross-process work such as leader-only cron, serialized migrations, and exclusive file IO.",
        ["KeyValueBucket", "CircuitBreaker", "TimeoutBudget", "WorkflowRun"],
        [
            (
                "Leader-only cron",
                ["WorkflowRun", "TimeoutBudget"],
                "Only the lock holder runs the scheduled job; the lease is shorter than the budget so a stalled leader loses leadership before it can run twice.",
            ),
            (
                "Safe migration fence",
                ["KeyValueBucket", "AuditEvent"],
                "A data migration acquires the lock and writes a revision record to the KV bucket; concurrent deploys observe the fence and abort cleanly.",
            ),
            (
                "Fault-tolerant acquisition",
                ["CircuitBreaker", "RetryPolicy"],
                "Lock acquisition wraps the Redis/etcd call in a breaker so a backend outage fails fast rather than queuing a thundering herd.",
            ),
        ],
    ),
    "KeyValueBucket": (
        "Provide one small contract over optimistic concurrency (create/update/delete with revision) plus a capped read-through cache.",
        ["DistributedLock", "IdentityMap", "CircuitBreaker", "MetricMeter"],
        [
            (
                "Lost-update prevention",
                ["DistributedLock", "AuditEvent"],
                "Updates carry a revision; on mismatch the caller re-reads instead of overwriting, and the conflict is audited — two writers cannot silently clobber each other.",
            ),
            (
                "Read-through cache",
                ["IdentityMap", "MetricMeter"],
                "Identity-map-like semantics per process plus bucket-level TTL keep hot keys in memory; cache hit ratio is a first-class metric, not a guess.",
            ),
            (
                "Graceful degradation",
                ["CircuitBreaker", "LoadShedder"],
                "When the KV backend is unhealthy the bucket returns stale-on-error under a breaker, while the shedder rejects low-priority writes — availability over freshness.",
            ),
        ],
    ),
    # ======================================================== compliance
    "AuditEvent": (
        "Emit a tamper-evident, append-only record of a security-relevant action with actor, subject, action verb, and outcome.",
        ["TamperEvidentAuditLog", "CurrentPrincipal", "CorrelationContext", "AccessLog"],
        [
            (
                "Non-repudiable action trail",
                ["TamperEvidentAuditLog", "CurrentPrincipal"],
                "Every write is sealed into a hash-chained log keyed by the principal — auditors can verify 'this sequence of actions was not edited after the fact'.",
            ),
            (
                "Correlated incident forensics",
                ["CorrelationContext", "StructuredLogger"],
                "Audit events carry the same correlation id as ops logs so 'show me everything this request touched' is one query across two streams.",
            ),
            (
                "Read vs write separation",
                ["AccessLog", "TamperEvidentAuditLog"],
                "Audit records security events; AccessLog records reads of classified data — HIPAA accounting-of-disclosures stays readable when audit volume is low.",
            ),
        ],
    ),
    "BreachNotificationQueue": (
        "Track suspected and confirmed personal-data incidents with the GDPR Article 33 72-hour clock and enforced closure evidence.",
        ["AuditEvent", "DataSubjectRequest", "TamperEvidentAuditLog", "PiiClassification"],
        [
            (
                "72-hour containment",
                ["AuditEvent", "TamperEvidentAuditLog"],
                "Incident lifecycle events are sealed and timestamped; the supervisory clock cannot be retroactively edited once `confirm` is called.",
            ),
            (
                "Impacted-subject notification",
                ["DataSubjectRequest", "PiiClassification"],
                "Impacted subjects are derived from the incident scope and the PII classification map; each subject's DSR can reference the breach for Art 34 disclosures.",
            ),
            (
                "Evidence-gated closure",
                ["TamperEvidentAuditLog", "AuditEvent"],
                "`close` requires either a supervisory notification reference or a documented no-notification-required basis — you cannot silently archive an incident.",
            ),
        ],
    ),
    "ConsentLedger": (
        "Record, revoke, and prove consent grants with a per-purpose, per-subject, timestamped ledger that satisfies GDPR accountability.",
        ["DataSubjectRequest", "ProcessingRecord", "AuditEvent", "TamperEvidentAuditLog"],
        [
            (
                "Lawful-basis enforcement",
                ["ProcessingRecord", "DataSubjectRequest"],
                "Every processing activity declares its lawful basis; when the basis is consent, the ledger is the single source of truth a DSR can query.",
            ),
            (
                "Withdraw-and-erase",
                ["DataSubjectRequest", "AuditEvent"],
                "Revocation opens an erasure DSR automatically and emits an audit event — no silent revocation and no ignored revocation.",
            ),
            (
                "Proof-of-grant",
                ["TamperEvidentAuditLog", "AuditEvent"],
                "Consent grants are sealed into the audit chain so 'show me the exact consent as granted on 2024-03-01' is cryptographically answerable.",
            ),
        ],
    ),
    "DataSubjectRequest": (
        "Coordinate the GDPR access/portability/erasure/rectification lifecycle with a 30-day clock and per-store artifact manifest.",
        ["ConsentLedger", "RetentionPolicy", "LegalHold", "PiiClassification"],
        [
            (
                "Erasure cascade",
                ["RetentionPolicy", "LegalHold"],
                "Erasure walks every store declared in the classification map; LegalHold.covers() is consulted first so lawful holds survive the request.",
            ),
            (
                "Portability export",
                ["PiiClassification", "ConsentLedger"],
                "Access/portability exports are scoped by classification; consent records travel with the export so the recipient inherits the original lawful basis.",
            ),
            (
                "Closure evidence",
                ["AuditEvent", "TamperEvidentAuditLog"],
                "A DSR cannot close until every registered store attaches a per-store artifact, and each artifact is sealed into the audit chain.",
            ),
        ],
    ),
    "ProcessingRecord": (
        "Generate GDPR Article 30 Records of Processing Activities from handler decorators so the ROPA stays byte-for-byte diffable across releases.",
        ["ConsentLedger", "DataResidencyPolicy", "RetentionPolicy", "PiiClassification"],
        [
            (
                "Code-first ROPA",
                ["PiiClassification", "RetentionPolicy"],
                "Every handler declares data classes, retention ref, and purposes; the registry composes them into an Article-30 document without a parallel spreadsheet.",
            ),
            (
                "Lawful-basis binding",
                ["ConsentLedger", "DataResidencyPolicy"],
                "Each activity names its lawful basis and the regions its data may enter — residency and consent are one declaration, not two.",
            ),
            (
                "Diffable across releases",
                ["AuditEvent", "TamperEvidentAuditLog"],
                "ROPA hashes are sealed on each release; auditors diff two hashes to see exactly what changed between engagements.",
            ),
        ],
    ),
    "RetentionPolicy": (
        "Implement GDPR storage limitation and PCI retention controls in code: each data class declares a TTL and a post-TTL action.",
        ["DataSubjectRequest", "LegalHold", "PiiClassification", "ProcessingRecord"],
        [
            (
                "Automated sweep",
                ["LegalHold", "AuditEvent"],
                "Retention sweeper consults LegalHold.covers() before every delete; every retained-past-TTL record is audited with the covering hold id.",
            ),
            (
                "DSR-aware erasure",
                ["DataSubjectRequest", "PiiClassification"],
                "An erasure DSR is a retention override scoped to one subject; the same classification map drives both automated sweep and ad-hoc erasure.",
            ),
            (
                "Policy evidence",
                ["ProcessingRecord", "TamperEvidentAuditLog"],
                "The retention_ref in the ROPA points to the executable policy; auditors verify runtime behavior matches the document — not a screenshot.",
            ),
        ],
    ),
    "TamperEvidentAuditLog": (
        "Provide one signed, chain-verified evidence stream so SOC 2 non-repudiation and HIPAA audit-control requirements are answered with cryptography.",
        ["AuditEvent", "SignatureVerifier", "SecretsVault", "AccessLog"],
        [
            (
                "Hash-chained evidence",
                ["SignatureVerifier", "SecretsVault"],
                "Each entry signs the previous head; the signing key is vault-issued — a forged entry invalidates the chain from its insertion point forward.",
            ),
            (
                "Dual-stream auditing",
                ["AuditEvent", "AccessLog"],
                "Security events and data reads hash-chain into the same sealed log without sharing a topic, so query volume never drowns security signal.",
            ),
            (
                "Compliance export",
                ["ConsentLedger", "DataSubjectRequest"],
                "DSR and consent artifacts are sealed into the chain so 'prove this record was not altered after we sent it to the auditor' is one verify() call.",
            ),
        ],
    ),
    # ======================================================== data
    "Aggregate": (
        "Define a consistency boundary around a cluster of entities and value objects governed by a single root that enforces invariants.",
        ["Repository", "UnitOfWork", "ValueObject", "DomainEvent"],
        [
            (
                "Transactional consistency",
                ["Repository", "UnitOfWork"],
                "All mutations to the aggregate flow through the root and commit atomically through the UoW — no child entity can be modified outside the root's invariants.",
            ),
            (
                "Immutable inner model",
                ["ValueObject", "Specification"],
                "Aggregate state is composed of value objects; selection predicates are Specifications — the internal structure never leaks as ORM types.",
            ),
            (
                "Event-sourced commits",
                ["DomainEvent", "TransactionalOutbox"],
                "Each aggregate change emits a domain event; the outbox guarantees the event ships if and only if the state change committed.",
            ),
        ],
    ),
    "AntiCorruptionLayer": (
        "Translate between a local model and a foreign or legacy model so upstream semantics cannot leak into the downstream domain.",
        ["BoundedContext", "ContextMap", "OutboundBinding", "ValueObject"],
        [
            (
                "Upstream translation",
                ["ContextMap", "OutboundBinding"],
                "The ACL owns the inbound mapping declared by the context map; upstream schema churn stays contained to one adapter file.",
            ),
            (
                "Conformist escape hatch",
                ["BoundedContext", "ValueObject"],
                "Foreign DTOs are turned into local value objects at the boundary — downstream code never imports upstream types.",
            ),
            (
                "Legacy strangulation",
                ["OutboundBinding", "CircuitBreaker"],
                "Calls to the legacy system go through the ACL behind a breaker so the new context degrades predictably when the legacy is down.",
            ),
        ],
    ),
    "BoundedContext": (
        "Declare the explicit linguistic and model boundary within which one ubiquitous language and one set of invariants apply.",
        ["ContextMap", "AntiCorruptionLayer", "Aggregate", "DomainEvent"],
        [
            (
                "Language isolation",
                ["Aggregate", "ValueObject"],
                "Inside the context, one term means one thing; aggregates and value objects are named in the context's ubiquitous language without qualifiers.",
            ),
            (
                "Explicit integration",
                ["ContextMap", "AntiCorruptionLayer"],
                "Every cross-context call routes through an ACL named in the context map — silent cross-context imports are prevented at the module boundary.",
            ),
            (
                "Published events",
                ["DomainEvent", "TopicBus"],
                "Events emitted by a context form its published language; other contexts subscribe through the bus and translate via their own ACL.",
            ),
        ],
    ),
    "ChangeDataCapture": (
        "Publish an ordered stream of row-level changes from a source database so downstream systems can consume mutations without double-writing.",
        ["EventStream", "TransactionalOutbox", "MaterializedView", "IdempotentConsumer"],
        [
            (
                "Log-based outbox alternative",
                ["TransactionalOutbox", "EventStream"],
                "CDC reads the DB commit log as the single source of truth; downstream consumers see the same order as the database — no application-level outbox poller.",
            ),
            (
                "Derived read model",
                ["MaterializedView", "IdempotentConsumer"],
                "A view subscribes to CDC and rebuilds itself idempotently from a snapshot + ongoing stream; reprocessing never produces drift.",
            ),
            (
                "Cross-store replication",
                ["EventStream", "AntiCorruptionLayer"],
                "CDC feeds a downstream context through its ACL so the target schema never has to mirror the source schema.",
            ),
        ],
    ),
    "ConfigBinding": (
        "Bind a namespaced slice of runtime configuration to a typed record, validated at startup so misconfiguration fails fast, not at request time.",
        ["DiContainer", "SecretsVault", "LifetimeScope", "FeatureToggle"],
        [
            (
                "Fail-fast startup",
                ["DiContainer", "LifetimeScope"],
                "DI resolution requires every declared binding; a missing or mistyped value crashes boot instead of surfacing as a 500 under load.",
            ),
            (
                "Secrets vs config split",
                ["SecretsVault", "FeatureToggle"],
                "ConfigBinding holds non-secret, per-env shape; secrets come from the vault at request time; feature toggles drive per-cohort behavior — three distinct lifecycles, three distinct tools.",
            ),
            (
                "Typed reload",
                ["LifetimeScope", "AuditEvent"],
                "Hot-reload of config rebinds the typed record and emits an audit event with a diff — no operator 'maybe I changed that flag' ambiguity.",
            ),
        ],
    ),
    "DataMapper": (
        "Move state between in-memory domain objects and rows in storage while keeping both ignorant of each other's shape.",
        ["Repository", "UnitOfWork", "IdentityMap", "ValueObject"],
        [
            (
                "Classic mapper sandwich",
                ["Repository", "UnitOfWork"],
                "Repository is the collection-style façade; DataMapper is the translation layer; UoW is the transaction — each seam does exactly one job.",
            ),
            (
                "Identity-preserving load",
                ["IdentityMap", "Repository"],
                "Loaded aggregates register in the identity map; a second load returns the same instance — mapper output is cached by identity, not duplicated.",
            ),
            (
                "Value-object hydration",
                ["ValueObject", "Specification"],
                "Rows become frozen value objects at hydration; Specifications translate into storage queries — the domain never sees raw columns.",
            ),
        ],
    ),
    "DiContainer": (
        "Registry that resolves a typed request for a dependency into a constructed instance obeying the declared lifetime scope.",
        ["LifetimeScope", "ConfigBinding", "Repository", "UnitOfWork"],
        [
            (
                "Scoped per-request wiring",
                ["LifetimeScope", "UnitOfWork"],
                "Request-scoped UoW and repositories are resolved once per request and disposed at pipeline exit — handlers never 'new' a transaction.",
            ),
            (
                "Typed configuration graph",
                ["ConfigBinding", "LifetimeScope"],
                "Config records are singleton bindings; their consumers are request-scoped — hot-reload rewires consumers without rebooting singletons.",
            ),
            (
                "Testable seams",
                ["Repository", "OutboundBinding"],
                "Every integration is a registered interface; tests swap in fakes without touching production wiring — integration seams are mockable by construction.",
            ),
        ],
    ),
    "IdentityMap": (
        "Cache loaded domain objects by identity inside one session so the same row is never represented twice and in-memory mutations are visible.",
        ["Repository", "UnitOfWork", "DataMapper", "Aggregate"],
        [
            (
                "Consistent-read guarantee",
                ["Repository", "UnitOfWork"],
                "Within one UoW, two `get(id)` calls return the same instance — mutations applied to one reference are visible to all readers.",
            ),
            (
                "No lost updates",
                ["DataMapper", "UnitOfWork"],
                "Mapper flushes only tracked instances; mutations applied outside the map are rejected at commit rather than silently skipped.",
            ),
            (
                "Aggregate coherence",
                ["Aggregate", "Repository"],
                "The map holds aggregate roots; child entities are reached through the root — the same root is shared across all child accesses in the session.",
            ),
        ],
    ),
    "LegalHold": (
        "Suspend retention-driven deletion and erasure cascades for records covered by a litigation or regulatory hold.",
        ["RetentionPolicy", "DataSubjectRequest", "AuditEvent", "TamperEvidentAuditLog"],
        [
            (
                "Hold-first delete",
                ["RetentionPolicy", "AuditEvent"],
                "Every retention sweep calls `covers(record_id)` before deleting; a covered record stays and a deferred-delete audit is emitted with the hold id.",
            ),
            (
                "DSR survival",
                ["DataSubjectRequest", "AuditEvent"],
                "An erasure DSR on a held subject produces a documented deferral instead of a deletion; the subject is notified the hold exists (where lawful).",
            ),
            (
                "Hold lifecycle",
                ["TamperEvidentAuditLog", "AuditEvent"],
                "Open, extend, and release events are sealed into the audit chain so 'show me who released this hold and when' is one signed query.",
            ),
        ],
    ),
    "LifetimeScope": (
        "Typed enumeration that fixes how long a resolved instance lives: the whole process, one request, or one operation.",
        ["DiContainer", "ConfigBinding", "UnitOfWork", "RequestContext"],
        [
            (
                "Per-request UoW",
                ["DiContainer", "UnitOfWork"],
                "Request scope owns the UoW; entering the pipeline creates it, exiting disposes it — handlers never leak transactions across requests.",
            ),
            (
                "Singleton config",
                ["ConfigBinding", "DiContainer"],
                "Typed config is singleton; request-scoped consumers re-read it without re-parsing — hot-reload of config is O(1) per request.",
            ),
            (
                "Operation-scoped tracing",
                ["RequestContext", "Tracer"],
                "Operation scope matches span scope; spawned spans inherit request context without handlers threading anything by hand.",
            ),
        ],
    ),
    "MaterializedView": (
        "Maintain a pre-computed query result kept up to date by an incremental feed so read queries never recompute the whole source.",
        ["ChangeDataCapture", "EventStream", "IdempotentConsumer", "Specification"],
        [
            (
                "CDC-driven rebuild",
                ["ChangeDataCapture", "IdempotentConsumer"],
                "View subscribes to CDC; rebuilds are idempotent — a replay from snapshot produces a byte-identical view without double-applying effects.",
            ),
            (
                "CQRS read model",
                ["EventStream", "Specification"],
                "Commands mutate aggregates; a projector subscribes to the event stream and maintains the view; Specifications are the only query surface — no SQL leaks.",
            ),
            (
                "Stale-bounded reads",
                ["MetricMeter", "HealthProbe"],
                "View freshness is a first-class metric; readiness probe goes unhealthy if lag exceeds SLO — stale reads are a visible failure mode.",
            ),
        ],
    ),
    "PiiClassification": (
        "Tag every persisted field with a sensitivity class so serialization goes through one central mask that redacts above the audience's cap.",
        ["RetentionPolicy", "DataSubjectRequest", "DataResidencyPolicy", "OutputEncoder"],
        [
            (
                "Mask-at-the-edge",
                ["OutputEncoder", "AccessLog"],
                "Outbound responses pass through mask(audience); the read is then accounted in the access log with the audience — de-identification is mechanical, not a review item.",
            ),
            (
                "Classification-driven residency",
                ["DataResidencyPolicy", "RetentionPolicy"],
                "Class declares TTL and allowed regions; a single tag drives storage limitation and cross-border transfer rules.",
            ),
            (
                "DSR scope",
                ["DataSubjectRequest", "LegalHold"],
                "Erasure walks every store holding a given class; LegalHold overrides deletion where lawful — one map drives both.",
            ),
        ],
    ),
    "Repository": (
        "Mediate between the domain model and the data-mapping layer with a collection-like interface scoped to one aggregate root.",
        ["UnitOfWork", "IdentityMap", "Specification", "Aggregate"],
        [
            (
                "DDD persistence sandwich",
                ["UnitOfWork", "IdentityMap"],
                "Repo enlists every mutation with the active UoW and consults the identity map first on reads — no silent direct writes and no stale in-memory copies.",
            ),
            (
                "Query via Specification",
                ["Specification", "Aggregate"],
                "find() accepts a Specification and returns only aggregate roots; ORM syntax never crosses the boundary.",
            ),
            (
                "Aggregate-only surface",
                ["Aggregate", "DomainEvent"],
                "One repo per root; child entities are reached through navigation; mutations emit domain events the outbox relays — the repo stays pure.",
            ),
        ],
    ),
    "Specification": (
        "Encapsulate a predicate over a domain object so selection, validation, and criteria share one executable definition.",
        ["Repository", "Aggregate", "ValueObject", "DataMapper"],
        [
            (
                "Query + validate twins",
                ["Repository", "Aggregate"],
                "The same Specification filters `find()` results and validates admission to an aggregate invariant — server-side and in-memory checks cannot drift.",
            ),
            (
                "Composable predicates",
                ["ValueObject", "DataMapper"],
                "Spec composition (and/or/not) builds a new value object; the mapper translates the tree to the storage dialect on the fly.",
            ),
            (
                "Domain-only vocabulary",
                ["Repository", "AntiCorruptionLayer"],
                "Specifications speak only domain terms; foreign filters are translated by the ACL before the repo ever sees them.",
            ),
        ],
    ),
    "TransactionalBatch": (
        "Offer cross-key atomicity against one state store without application-level two-phase commit or compensating transactions.",
        ["UnitOfWork", "KeyValueBucket", "TransactionalOutbox", "IdempotentConsumer"],
        [
            (
                "All-or-nothing writes",
                ["KeyValueBucket", "UnitOfWork"],
                "Multiple keys commit atomically; optimistic revisions on each key turn conflicts into explicit retries rather than partial application.",
            ),
            (
                "State + outbox together",
                ["TransactionalOutbox", "UnitOfWork"],
                "The batch includes the outbox row; the downstream event ships if and only if the state change committed — no phantom events.",
            ),
            (
                "Idempotent retry",
                ["IdempotentConsumer", "RetryPolicy"],
                "Batch ids act as idempotency keys so a retried commit is a no-op on the second apply — safe to retry without bookkeeping.",
            ),
        ],
    ),
    "UnitOfWork": (
        "Track object changes during a business transaction and flush them to storage as one atomic commit or rollback.",
        ["Repository", "IdentityMap", "TransactionalOutbox", "LifetimeScope"],
        [
            (
                "Transactional consistency",
                ["Repository", "IdentityMap"],
                "Every mutation enlists with the active UoW; the identity map holds the in-flight graph; a rollback leaves memory and storage aligned.",
            ),
            (
                "Outbox in the same tx",
                ["TransactionalOutbox", "DomainEvent"],
                "Domain events written to the outbox commit with the state change; the relay publishes them out-of-band — at-least-once delivery without dual writes.",
            ),
            (
                "Request-scoped lifetime",
                ["LifetimeScope", "DiContainer"],
                "UoW is resolved per request by the container; pipeline exit triggers commit or rollback — handlers never forget to close a transaction.",
            ),
        ],
    ),
    "ValueObject": (
        "Represent a descriptive concept whose identity is defined by its attributes and which is immutable once constructed.",
        ["Aggregate", "Specification", "DataMapper", "InputValidator"],
        [
            (
                "Immutable domain state",
                ["Aggregate", "Specification"],
                "Aggregates compose value objects; state changes replace them rather than mutate — invariants are checked at construction, once.",
            ),
            (
                "Validated hydration",
                ["InputValidator", "DataMapper"],
                "Inbound payloads become value objects through the validator; the mapper re-emits them to storage — invalid state is unrepresentable at the type level.",
            ),
            (
                "Pure equality",
                ["Specification", "DomainEvent"],
                "VO equality is structural, so event payloads and specification matches compare cleanly across processes — no hidden identity.",
            ),
        ],
    ),
    # ======================================================== events
    "DeadLetterRoute": (
        "Named destination where undeliverable or repeatedly failed messages are routed after the redelivery budget is exhausted.",
        ["IdempotentConsumer", "RetryPolicy", "TopicBus", "AuditEvent"],
        [
            (
                "Budget-exhausted routing",
                ["RetryPolicy", "IdempotentConsumer"],
                "When the retry budget burns down, the message lands on the DLR with its full failure history — no infinite redelivery storm.",
            ),
            (
                "Poison-pill quarantine",
                ["TopicBus", "AuditEvent"],
                "Malformed messages are quarantined out of the primary topic and audited; operators can replay after fix without crashing the consumer fleet.",
            ),
            (
                "Reprocess with dedupe",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "Replaying from DLR preserves original idempotency keys; already-applied effects stay applied once — replay is safe by construction.",
            ),
        ],
    ),
    "DomainEvent": (
        "Record an immutable fact about something meaningful that happened in the domain and publish it to domain subscribers.",
        ["EventEnvelope", "TransactionalOutbox", "Aggregate", "TopicBus"],
        [
            (
                "Aggregate-emitted facts",
                ["Aggregate", "TransactionalOutbox"],
                "Aggregates raise events on state change; the outbox commits them with the state — no event ships without its corresponding mutation.",
            ),
            (
                "Typed published language",
                ["EventEnvelope", "TopicBus"],
                "Events travel inside a CloudEvents envelope so schema, source, and id are wire-level — consumers in other contexts never speak raw dict.",
            ),
            (
                "Event-driven integration",
                ["TopicBus", "IdempotentConsumer"],
                "Subscribers consume through idempotent consumers; at-least-once from the bus becomes effectively exactly-once at the handler.",
            ),
        ],
    ),
    "EventEnvelope": (
        "Frozen, validated dataclass that captures the CloudEvents 1.0.2 canonical shape and makes routing/version/time first-class.",
        ["DomainEvent", "TopicBus", "StreamSubject", "IdempotentConsumer"],
        [
            (
                "Wire-format contract",
                ["DomainEvent", "TopicBus"],
                "Envelope is the single on-the-wire shape across brokers; producers and consumers never negotiate format per integration.",
            ),
            (
                "Subject-based routing",
                ["StreamSubject", "TopicBus"],
                "The subject field drives hierarchical routing; consumers subscribe by pattern without parsing payloads.",
            ),
            (
                "Dedupe by envelope id",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "The envelope id is the canonical idempotency key; any consumer can dedupe by id without inventing its own hashing.",
            ),
        ],
    ),
    "EventSourcedStore": (
        "Persist aggregate state as an ordered sequence of domain events and reconstruct current state by folding over the log.",
        ["DomainEvent", "EventStream", "Aggregate", "MaterializedView"],
        [
            (
                "State-from-events",
                ["DomainEvent", "Aggregate"],
                "Aggregates are rehydrated by replaying their event stream; there is no mutable state of record — the log is authoritative.",
            ),
            (
                "Snapshotted rebuild",
                ["EventStream", "MaterializedView"],
                "Read models and aggregate snapshots are materialized from the stream; a rebuild from genesis is always a valid recovery path.",
            ),
            (
                "Temporal queries",
                ["EventStream", "Specification"],
                "Because history is the source of truth, 'state as of time T' is a fold truncated at T — audit queries are a library concern, not a schema migration.",
            ),
        ],
    ),
    "EventStream": (
        "Ordered, append-only log of events partitioned by key and replayable from any offset by any number of independent consumers.",
        ["TopicBus", "EventEnvelope", "IdempotentConsumer", "ChangeDataCapture"],
        [
            (
                "Partitioned ordering",
                ["TopicBus", "IdempotentConsumer"],
                "Per-key order is preserved; consumers dedupe by envelope id so a replay never re-applies effects even though it re-reads events.",
            ),
            (
                "Replay as recovery",
                ["MaterializedView", "EventSourcedStore"],
                "Views and aggregates can be rebuilt from any offset; disaster recovery is 'reset the consumer group' — not 'restore a backup'.",
            ),
            (
                "CDC ingress",
                ["ChangeDataCapture", "EventEnvelope"],
                "CDC lands directly on an event stream wrapped in envelopes — downstream consumers do not care whether the source was a DB or a producer.",
            ),
        ],
    ),
    "IdempotentConsumer": (
        "Apply a message's effect at most once per logical key while tolerating at-least-once delivery from the transport.",
        ["InboxDeduplicator", "TransactionalOutbox", "DeadLetterRoute", "SignatureVerifier"],
        [
            (
                "Webhook receiver",
                ["SignatureVerifier", "InboxDeduplicator"],
                "Inbound request is verified for authenticity, then dedup'd by event id — replay attacks and duplicate deliveries are both neutralized.",
            ),
            (
                "Consume-then-publish",
                ["InboxDeduplicator", "TransactionalOutbox"],
                "Inbox dedup gates handle(); handle() writes state + outbox in one tx; downstream consumers dedupe similarly — the whole pipeline is effectively exactly-once.",
            ),
            (
                "Bounded retries",
                ["DeadLetterRoute", "RetryPolicy"],
                "Budget-bounded retries land on the DLR with full context; manual replay reuses the original idempotency key — zero double-apply risk.",
            ),
        ],
    ),
    "InboxDeduplicator": (
        "Record processed message identifiers in the consumer's database so redelivered messages are detected by a local primary-key conflict.",
        ["IdempotentConsumer", "TransactionalOutbox", "UnitOfWork", "EventStream"],
        [
            (
                "Local dedup gate",
                ["IdempotentConsumer", "UnitOfWork"],
                "The inbox row is inserted in the same transaction as the business effect; a duplicate redelivery fails on PK and the handler is skipped.",
            ),
            (
                "Effectively-once downstream",
                ["TransactionalOutbox", "IdempotentConsumer"],
                "Combined with an outbox, the consumer's own emitted events carry stable ids — the next hop in the pipeline dedupes the same way.",
            ),
            (
                "Replay-safe recovery",
                ["EventStream", "DeadLetterRoute"],
                "Replaying from the stream or from the DLR never double-applies; the inbox is the single source of truth for 'have I already done this?'.",
            ),
        ],
    ),
    "SagaOrchestrator": (
        "Coordinate a multi-step business transaction across services by driving each step and triggering compensations on partial failure.",
        ["WorkflowRun", "TransactionalOutbox", "DomainEvent", "IdempotentConsumer"],
        [
            (
                "Compensating transaction",
                ["WorkflowRun", "TransactionalOutbox"],
                "Each step and its compensation are durable workflow activities; partial failure triggers compensations in reverse order without a distributed 2PC.",
            ),
            (
                "Event-driven coordination",
                ["DomainEvent", "IdempotentConsumer"],
                "Saga reacts to domain events and emits commands via idempotent consumers — at-least-once delivery never causes double-compensation.",
            ),
            (
                "Observable long-running state",
                ["Tracer", "HealthProbe"],
                "Workflow spans cover the entire saga; unhealthy sagas surface on the readiness probe before a customer complaint.",
            ),
        ],
    ),
    "StreamSubject": (
        "Shared type for hierarchical subject names and pattern matching so routing, filtering, and authorization share one vocabulary.",
        ["EventEnvelope", "TopicBus", "EventStream", "RequestGuard"],
        [
            (
                "Hierarchical routing",
                ["EventEnvelope", "TopicBus"],
                "Subjects like `orders.v1.created` route to pattern subscribers without payload parsing; one primitive governs producer and consumer filters.",
            ),
            (
                "Subject-scoped authz",
                ["RequestGuard", "TopicBus"],
                "Subscription authorization is an allow-list over subject patterns — not a free-text filter audited line by line.",
            ),
            (
                "Stream partitioning",
                ["EventStream", "EventEnvelope"],
                "Subject + partition key together determine placement; the same subject never spans inconsistent partitions.",
            ),
        ],
    ),
    "TopicBus": (
        "Publish and subscribe facade over a broker topic that delivers CloudEvents at least once to named subscribers.",
        ["EventEnvelope", "StreamSubject", "IdempotentConsumer", "DeadLetterRoute"],
        [
            (
                "Published-language fabric",
                ["EventEnvelope", "StreamSubject"],
                "Bus speaks only envelopes routed by subject; producers and consumers never care which broker implements the topic.",
            ),
            (
                "Safe fan-out",
                ["IdempotentConsumer", "DeadLetterRoute"],
                "Each subscriber dedupes by envelope id and shunts poison messages to the DLR; one bad consumer does not stall the fleet.",
            ),
            (
                "Cross-context integration",
                ["ContextMap", "AntiCorruptionLayer"],
                "Context boundaries publish through the bus; consumers translate via their own ACL — no synchronous coupling across contexts.",
            ),
        ],
    ),
    "TransactionalOutbox": (
        "Store outgoing messages in the same local transaction as the state change so a relay can publish them at-least-once without dual writes.",
        ["UnitOfWork", "IdempotentConsumer", "DomainEvent", "EventStream"],
        [
            (
                "Dual-write elimination",
                ["UnitOfWork", "DomainEvent"],
                "State change + event row commit together; a crash between the two is impossible — the relay republishes what the DB already saw.",
            ),
            (
                "End-to-end idempotency",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "Outbox rows carry stable ids; downstream consumers dedupe — a relay retry never re-applies an effect.",
            ),
            (
                "Stream-bridged integration",
                ["EventStream", "ChangeDataCapture"],
                "The relay is the outbox tailer or CDC; either way, the stream sees exactly the events the database committed.",
            ),
        ],
    ),
    # ======================================================== extras
    "OutboundBinding": (
        "Keep every external integration behind one declarative adapter that exposes a typed-operation surface and hides SDK quirks.",
        ["AntiCorruptionLayer", "CircuitBreaker", "RetryPolicy", "SecretsVault"],
        [
            (
                "Typed SDK facade",
                ["AntiCorruptionLayer", "SecretsVault"],
                "Callers see typed operations; the adapter loads credentials from the vault and translates SDK types — no vendor import leaks into business code.",
            ),
            (
                "Resilient egress",
                ["CircuitBreaker", "RetryPolicy"],
                "Every outbound call is wrapped in a breaker + retry policy; a flaky vendor does not cascade into the primary transaction.",
            ),
            (
                "Swap-in-place",
                ["DiContainer", "FeatureToggle"],
                "Adapters are DI-registered; a toggle switches between vendors at runtime without redeploy — vendor lock-in becomes a configuration decision.",
            ),
        ],
    ),
    "RequestShape": (
        "Capture a request's resiliency context — priority class, deadline, idempotency key, retry-count — so downstream primitives react the same way.",
        ["TimeoutBudget", "LoadShedder", "IdempotentConsumer", "RetryPolicy"],
        [
            (
                "Deadline propagation",
                ["TimeoutBudget", "MiddlewarePipeline"],
                "The shape carries the remaining budget; every downstream call reads the same deadline — no handler extends the budget by accident.",
            ),
            (
                "Priority-aware shedding",
                ["LoadShedder", "Bulkhead"],
                "Shed/admit decisions are driven by the request's priority class — high-priority work survives overload without retries becoming a feedback loop.",
            ),
            (
                "Idempotent retries",
                ["RetryPolicy", "IdempotentConsumer"],
                "Retries reuse the request's idempotency key; the downstream consumer dedupes — at-least-once transport never doubles effects.",
            ),
        ],
    ),
    "RpcInterceptor": (
        "Define the single middleware seam for remote calls, specifying what an interceptor may do and in what order interceptors compose.",
        ["OutboundBinding", "MiddlewarePipeline", "CorrelationContext", "Tracer"],
        [
            (
                "Symmetric middleware",
                ["MiddlewarePipeline", "OutboundBinding"],
                "Inbound pipeline and outbound interceptors share a contract — one mental model governs every hop in and out of the service.",
            ),
            (
                "Correlation propagation",
                ["CorrelationContext", "Tracer"],
                "Interceptors inject correlation id and trace context on every RPC; distributed traces stitch end-to-end without handler code.",
            ),
            (
                "Policy injection",
                ["CircuitBreaker", "RetryPolicy"],
                "Resiliency policies mount as interceptors; swapping policy per call is a registration change, not a rewrite.",
            ),
        ],
    ),
    "VirtualActor": (
        "Serialize writes per entity without hand-rolling locks; give entities a durable reminder surface for time-based behavior.",
        ["WorkflowRun", "DistributedLock", "IdempotentConsumer", "DurableTimer"],
        [
            (
                "Per-entity serialization",
                ["DistributedLock", "IdempotentConsumer"],
                "Writes to one entity run sequentially even across hosts; idempotent framing means a rehomed actor never double-applies an in-flight message.",
            ),
            (
                "Durable reminders",
                ["DurableTimer", "WorkflowRun"],
                "Actor reminders survive restarts; a workflow step scheduled for next week fires once regardless of deploy churn.",
            ),
            (
                "Saga participant",
                ["SagaOrchestrator", "WorkflowRun"],
                "Actors respond to saga commands and emit events; compensations land as messages the actor processes in order.",
            ),
        ],
    ),
    # ======================================================== flags
    "FeatureToggle": (
        "Named boolean or variant predicate, evaluated against the current context, that controls whether a code path runs.",
        ["RequestGuard", "ConfigBinding", "CurrentPrincipal", "AuditEvent"],
        [
            (
                "Gradual rollout",
                ["CurrentPrincipal", "AuditEvent"],
                "Toggle evaluation keys on principal cohort; every activation and deactivation is audited so 'who saw the new path' is always answerable.",
            ),
            (
                "Kill switch",
                ["CircuitBreaker", "RequestGuard"],
                "A toggle flipped off short-circuits the feature before the breaker trips; an ops team can stop the bleed without a redeploy.",
            ),
            (
                "Config-vs-flag boundary",
                ["ConfigBinding", "AuditEvent"],
                "Static shape lives in config; per-cohort variability lives in toggles — two distinct change-management paths, both auditable.",
            ),
        ],
    ),
    # ======================================================== jobs
    "ActivityCall": (
        "Pin the activity contract so every tool uses the same timeouts, retry policy, heartbeat rules, and typed inputs/outputs.",
        ["WorkflowRun", "RetryPolicy", "TimeoutBudget", "IdempotentConsumer"],
        [
            (
                "Typed step contract",
                ["WorkflowRun", "RetryPolicy"],
                "Every workflow step declares its ActivityCall; retry and timeout are part of the contract — not per-step boilerplate.",
            ),
            (
                "Heartbeated long work",
                ["TimeoutBudget", "HealthProbe"],
                "Long activities heartbeat within the budget; a stalled activity is reclaimed and retried without a silent orphan.",
            ),
            (
                "At-least-once activities",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "Activities are retried on worker loss; idempotency keys make repeat execution safe — correctness does not depend on 'exactly once'.",
            ),
        ],
    ),
    "DurableTimer": (
        "Expose a replay-safe sleep API so workflows can wait for minutes, hours, or days without holding a thread or losing state on restart.",
        ["WorkflowRun", "VirtualActor", "SagaOrchestrator", "ActivityCall"],
        [
            (
                "Long-wait workflow",
                ["WorkflowRun", "ActivityCall"],
                "`sleep(7d)` survives deploys; the next activity fires exactly once at the scheduled wall clock — no cron, no shared scheduler.",
            ),
            (
                "Actor reminders",
                ["VirtualActor", "WorkflowRun"],
                "Virtual actors use timers as durable reminders; an entity 'wakes itself up' in the future without a centralized scheduler.",
            ),
            (
                "Saga timeouts",
                ["SagaOrchestrator", "ActivityCall"],
                "Sagas schedule compensating deadlines via durable timers; a lost participant triggers compensation at T+N regardless of process lifetimes.",
            ),
        ],
    ),
    "WorkflowRun": (
        "Give the application a single contract for long-running orchestrations that survive process restart, rebalancing, and deploy.",
        ["ActivityCall", "DurableTimer", "SagaOrchestrator", "VirtualActor"],
        [
            (
                "Durable orchestration",
                ["ActivityCall", "DurableTimer"],
                "Workflow code is deterministic; activities are side-effectful; timers are durable — the workflow history is the single replay source of truth.",
            ),
            (
                "Saga host",
                ["SagaOrchestrator", "ActivityCall"],
                "Sagas run as workflows; compensations are activities; the framework guarantees at-most-once compensation per step.",
            ),
            (
                "Actor substrate",
                ["VirtualActor", "DurableTimer"],
                "Workflows host virtual actor instances; reminders and state survive host loss — 'one actor per entity, always' is mechanical.",
            ),
        ],
    ),
    # ======================================================== llm
    "InputGuardrail": (
        "Intercept user input before it reaches a model and reject, redact, or transform it against deterministic policy.",
        ["PromptInjectionFilter", "PromptTemplate", "OutputGuardrail", "InputValidator"],
        [
            (
                "Sanitize-then-prompt",
                ["PromptInjectionFilter", "PromptTemplate"],
                "Input is scrubbed for injection patterns before it enters the template; the template's policy cannot be overridden by user text.",
            ),
            (
                "Schema + policy",
                ["InputValidator", "PromptInjectionFilter"],
                "Typed schema validation runs first; guardrail runs second — malformed structure never reaches the policy layer.",
            ),
            (
                "Symmetric I/O filtering",
                ["OutputGuardrail", "PromptInjectionFilter"],
                "Input and output guardrails share threat taxonomy; a pattern blocked inbound is also blocked in the response — no one-way leaks.",
            ),
        ],
    ),
    "OutputGuardrail": (
        "Inspect model output after generation and reject, rewrite, or annotate it against schema, policy, and safety predicates.",
        ["InputGuardrail", "PromptInjectionFilter", "PromptTemplate", "LlmTrace"],
        [
            (
                "Schema-shaped answer",
                ["PromptTemplate", "InputValidator"],
                "Template pins the output schema; OutputGuardrail validates the generation — responses that fail validation trigger a bounded retry, not a 500.",
            ),
            (
                "Policy compliance",
                ["InputGuardrail", "PromptInjectionFilter"],
                "Outbound safety checks catch what inbound guardrails missed (e.g., exfil via prompt injection) — defense in depth.",
            ),
            (
                "Observable generations",
                ["LlmTrace", "MetricMeter"],
                "Rejection/rewrite rates are metered; every rejection emits a trace — policy regressions show up as metric jumps, not support tickets.",
            ),
        ],
    ),
    "PromptInjectionFilter": (
        "Make indirect prompt injection a single well-defined failure surface: one primitive evaluates untrusted context and quarantines suspicious input.",
        ["InputGuardrail", "OutputGuardrail", "PromptTemplate", "LlmTrace"],
        [
            (
                "Untrusted-context quarantine",
                ["InputGuardrail", "PromptTemplate"],
                "Fetched documents, tool outputs, and memory are tagged and scanned; the template renders them inside a sandbox region the model cannot treat as instructions.",
            ),
            (
                "End-to-end safety",
                ["OutputGuardrail", "LlmTrace"],
                "Inbound + outbound filter plus trace-level attribution: you can always answer 'which document triggered this refusal?'.",
            ),
            (
                "Tool-call gating",
                ["RequestGuard", "OutputGuardrail"],
                "Tool invocations pass through the filter before RequestGuard runs — injected 'delete my account' never reaches the authorizer.",
            ),
        ],
    ),
    "PromptTemplate": (
        "Declare a named, versioned, parameterized prompt whose text, variables, and target model are pinned and reviewable.",
        ["InputGuardrail", "OutputGuardrail", "LlmTrace", "PromptInjectionFilter"],
        [
            (
                "Versioned prompt contract",
                ["LlmTrace", "OutputGuardrail"],
                "Every generation records the template version, inputs, and schema; A/B comparisons are deterministic and traces are diffable across releases.",
            ),
            (
                "Guarded rendering",
                ["InputGuardrail", "PromptInjectionFilter"],
                "Template variables are rendered through guardrails; untrusted substrings cannot rewrite the instruction region.",
            ),
            (
                "Cost-aware routing",
                ["MetricMeter", "SamplingPolicy"],
                "Per-template token counters drive cost attribution; sampling policy retains a representative share of traces without blowing observability budget.",
            ),
        ],
    ),
    # ======================================================== obs
    "AccessLog": (
        "Record every successful READ of a classified record separately from the security audit log so accounting-of-disclosures stays tractable.",
        ["AuditEvent", "TamperEvidentAuditLog", "PiiClassification", "CurrentPrincipal"],
        [
            (
                "Dual-stream auditing",
                ["AuditEvent", "TamperEvidentAuditLog"],
                "Reads and security events hash-chain into distinct sealed streams; query volume never drowns security signal.",
            ),
            (
                "Classification-driven reads",
                ["PiiClassification", "CurrentPrincipal"],
                "Every read captures actor + data_class + purpose_of_use; HIPAA accounting-of-disclosures is one projection over the stream.",
            ),
            (
                "Tamper-evident forensics",
                ["TamperEvidentAuditLog", "SignatureVerifier"],
                "Access records seal into the chain; auditors verify 'this read log was not edited' with one signature check.",
            ),
        ],
    ),
    "CardinalityGuard": (
        "Bound the unique attribute-value combinations attached to a metric or log stream to prevent label explosion.",
        ["MetricMeter", "HistogramBuckets", "SemanticAttributes", "StructuredLogger"],
        [
            (
                "Safe labeling",
                ["MetricMeter", "SemanticAttributes"],
                "High-cardinality labels (user id, trace id) are rejected at registration; developers cannot accidentally 10x the metrics bill.",
            ),
            (
                "Bounded log dimensions",
                ["StructuredLogger", "SemanticAttributes"],
                "Structured log fields are capped to a declared set; 'just add one more dimension' goes through review, not PR auto-merge.",
            ),
            (
                "Quantile integrity",
                ["HistogramBuckets", "MetricMeter"],
                "Fixed buckets + bounded cardinality keep p99 estimation honest; a hot label does not collapse bucket fidelity.",
            ),
        ],
    ),
    "CorrelationContext": (
        "Propagate a stable request identifier and optional baggage across threads, async tasks, and network boundaries.",
        ["CorrelationId", "StructuredLogger", "Tracer", "MiddlewarePipeline"],
        [
            (
                "End-to-end stitching",
                ["CorrelationId", "StructuredLogger"],
                "Every log line inherits the active correlation id; one grep reconstructs the full causal chain of a request.",
            ),
            (
                "Trace-log correlation",
                ["Tracer", "StructuredLogger"],
                "Trace id and correlation id travel together; jumping from a slow span to its logs is one click, not a timestamp search.",
            ),
            (
                "Async-safe propagation",
                ["MiddlewarePipeline", "RequestContext"],
                "Context survives task spawning and executor handoffs — handler code never re-threads identifiers by hand.",
            ),
        ],
    ),
    "CorrelationId": (
        "Opaque string that travels with a request across services and log lines so a reader can stitch together the full call chain.",
        ["CorrelationContext", "StructuredLogger", "Tracer", "RpcInterceptor"],
        [
            (
                "Cross-service trail",
                ["RpcInterceptor", "CorrelationContext"],
                "Outbound RPCs inject the id; inbound middleware adopts it — the same string threads every hop regardless of transport.",
            ),
            (
                "Log-trace bridge",
                ["StructuredLogger", "Tracer"],
                "Logs and traces share the id; an SRE pivots between the two without re-querying by timestamp.",
            ),
            (
                "Audit correlation",
                ["AuditEvent", "AccessLog"],
                "Audit and access records carry the same id — forensic reconstruction is a join, not a reconstruction.",
            ),
        ],
    ),
    "ErrorSink": (
        "Capture uncaught exceptions with fingerprint grouping, attach current trace and correlation context, and forward to a sink for triage.",
        ["StructuredLogger", "Tracer", "CorrelationContext", "HealthProbe"],
        [
            (
                "Grouped triage",
                ["StructuredLogger", "Tracer"],
                "Exceptions are fingerprinted, deduped, and linked to the active span — one incident produces one issue, not one per request.",
            ),
            (
                "Context-rich capture",
                ["CorrelationContext", "CurrentPrincipal"],
                "Each captured error carries principal, correlation, and request context — reproducing the bug does not require the customer's cooperation.",
            ),
            (
                "Health integration",
                ["HealthProbe", "MetricMeter"],
                "Spike-based probes turn red on sudden exception rates; pages fire before synthetic checks notice.",
            ),
        ],
    ),
    "EventBus": (
        "In-process publish/subscribe point for named framework and application events with structured payloads.",
        ["LifecycleHook", "StructuredLogger", "EventEnvelope", "MetricMeter"],
        [
            (
                "Framework extensibility",
                ["LifecycleHook", "StructuredLogger"],
                "Lifecycle phases publish on the bus; plugins subscribe without patching core — observability hooks compose cleanly.",
            ),
            (
                "Telemetry fan-out",
                ["MetricMeter", "StructuredLogger"],
                "Metrics meters and log handlers subscribe to the same event without coupling; one source of truth drives multiple sinks.",
            ),
            (
                "In-process → bus bridge",
                ["EventEnvelope", "TopicBus"],
                "Internal events convert to envelopes at the edge; cross-process subscribers see the same semantics through the topic bus.",
            ),
        ],
    ),
    "HealthProbe": (
        "Expose a typed liveness / readiness signal that reflects the real state of the process and its dependencies.",
        ["LifecycleHook", "CircuitBreaker", "MetricMeter", "ResourceDescriptor"],
        [
            (
                "Readiness-gated traffic",
                ["LifecycleHook", "CircuitBreaker"],
                "Readiness flips false while dependencies warm up or a breaker stays open — the orchestrator drains traffic before the instance serves errors.",
            ),
            (
                "Real-state liveness",
                ["MetricMeter", "ResourceDescriptor"],
                "Liveness reflects in-process signals (deadlock detectors, GC stalls) rather than a 200 OK — zombie processes are reclaimed.",
            ),
            (
                "Dependency rollup",
                ["CircuitBreaker", "OutboundBinding"],
                "Outbound bindings report into the probe; readiness composes over real dependency health, not synthetic self-checks.",
            ),
        ],
    ),
    "HistogramBuckets": (
        "Define explicit latency and size bucket boundaries for histogram instruments so quantile estimation is stable across versions.",
        ["MetricMeter", "CardinalityGuard", "SemanticAttributes", "SamplingPolicy"],
        [
            (
                "Stable quantiles",
                ["MetricMeter", "SemanticAttributes"],
                "Fixed buckets let alerts on p99 compare like-for-like across deploys; a silent bucket change cannot invalidate the SLO.",
            ),
            (
                "Budgeted cardinality",
                ["CardinalityGuard", "MetricMeter"],
                "Bucket count × label cardinality is bounded at registration — the metrics bill does not drift with the codebase.",
            ),
            (
                "Aligned sampling",
                ["SamplingPolicy", "Tracer"],
                "Tail-based sampling uses the same buckets as histogram boundaries; retained traces line up with the outlier tail of the distribution.",
            ),
        ],
    ),
    "LifecycleHook": (
        "Named callback fired at a defined application phase (starting, ready, stopping) so tools can initialize and drain in order.",
        ["HealthProbe", "EventBus", "DiContainer", "ResourceDescriptor"],
        [
            (
                "Ordered startup",
                ["DiContainer", "HealthProbe"],
                "Hooks fire in dependency order; readiness flips true only after every 'ready' hook returns — no premature traffic.",
            ),
            (
                "Graceful shutdown",
                ["HealthProbe", "EventBus"],
                "Stopping hooks drain queues, flush telemetry, close connections — SIGTERM-to-exit is a predictable sequence, not best effort.",
            ),
            (
                "Self-describing process",
                ["ResourceDescriptor", "StructuredLogger"],
                "Hooks emit phase events with the resource descriptor attached — deploys and rollouts appear as discrete events in the log stream.",
            ),
        ],
    ),
    "LlmTrace": (
        "Emit structured spans for each model call with attributes aligned to OpenTelemetry GenAI semantic conventions.",
        ["Tracer", "SemanticAttributes", "PromptTemplate", "SamplingPolicy"],
        [
            (
                "GenAI-conventional spans",
                ["Tracer", "SemanticAttributes"],
                "Every model call emits a span with gen_ai.* attributes; dashboards across services line up without per-app mapping.",
            ),
            (
                "Template-attributed cost",
                ["PromptTemplate", "MetricMeter"],
                "Spans carry template name + version; cost attribution is per template — A/B prompt changes show as cost deltas.",
            ),
            (
                "Tail-sampled outliers",
                ["SamplingPolicy", "OutputGuardrail"],
                "Slow or rejected generations are always retained; normal traffic is sampled — the debug corpus stays representative.",
            ),
        ],
    ),
    "MetricMeter": (
        "Record numeric measurements through four instrument shapes — counter, up-down counter, histogram, async gauge — with explicit label schemas.",
        ["HistogramBuckets", "CardinalityGuard", "SemanticAttributes", "TelemetryExporter"],
        [
            (
                "Safe instruments",
                ["HistogramBuckets", "CardinalityGuard"],
                "Every instrument declares buckets and bounded labels; stability across deploys is mechanical, not cultural.",
            ),
            (
                "Conventional attribute schema",
                ["SemanticAttributes", "TelemetryExporter"],
                "Labels use OTel semconv keys; exports land in dashboards without a per-service mapping layer.",
            ),
            (
                "SLO-grade signal",
                ["HealthProbe", "SamplingPolicy"],
                "The same histograms drive readiness thresholds and tail sampling; SLO math is one query.",
            ),
        ],
    ),
    "ResourceDescriptor": (
        "Describe the entity producing telemetry — service, version, deployment environment, instance id — and attach it to every emitted signal.",
        ["TelemetryExporter", "SemanticAttributes", "HealthProbe", "LifecycleHook"],
        [
            (
                "Uniform telemetry identity",
                ["TelemetryExporter", "SemanticAttributes"],
                "Every span, metric, and log carries the same resource attributes; dashboards filter by service.version without ad-hoc tagging.",
            ),
            (
                "Deployment correlation",
                ["LifecycleHook", "StructuredLogger"],
                "Startup hooks stamp the descriptor into ready events; regressions line up with deploy boundaries in the log stream.",
            ),
            (
                "Probe-visible identity",
                ["HealthProbe", "Tracer"],
                "Probes report the descriptor alongside health; on-call sees 'which instance of which version' at a glance.",
            ),
        ],
    ),
    "SamplingPolicy": (
        "Decide whether a given trace or span is retained, combining head-based and tail-based rules for a predictable observability bill.",
        ["Tracer", "HistogramBuckets", "TelemetryExporter", "LlmTrace"],
        [
            (
                "Budgeted retention",
                ["Tracer", "TelemetryExporter"],
                "Head-based sampling caps volume at ingress; tail-based rules always retain errors and outliers — the bill is bounded without losing the interesting tail.",
            ),
            (
                "Outlier-biased traces",
                ["HistogramBuckets", "LlmTrace"],
                "Tail samplers bias toward spans in the slow-tail bucket; GenAI anomalies are always inspectable after the fact.",
            ),
            (
                "Per-service policy",
                ["ResourceDescriptor", "Tracer"],
                "Policies are keyed by resource descriptor; a noisy service throttles without dragging neighbors.",
            ),
        ],
    ),
    "SemanticAttributes": (
        "Expose OpenTelemetry semantic-convention attribute keys as typed constants and enforce that primitives emit only conventional keys.",
        ["Tracer", "MetricMeter", "StructuredLogger", "CardinalityGuard"],
        [
            (
                "Convention-over-string",
                ["Tracer", "MetricMeter"],
                "Every span/metric uses typed keys (http.request.method, db.system.name); a typo is a compile error, not a dashboard mystery.",
            ),
            (
                "Portable dashboards",
                ["StructuredLogger", "TelemetryExporter"],
                "Logs, spans, and metrics agree on attribute names across services; dashboards migrate between backends without rewrites.",
            ),
            (
                "Cardinality-safe by construction",
                ["CardinalityGuard", "HistogramBuckets"],
                "Each typed key declares its cardinality budget — review happens at the source, not on the billing page.",
            ),
        ],
    ),
    "StructuredLogger": (
        "Emit machine-parseable key/value log records with a fixed level taxonomy and attached trace/span ids.",
        ["CorrelationContext", "Tracer", "SemanticAttributes", "CardinalityGuard"],
        [
            (
                "Queryable logs",
                ["SemanticAttributes", "CardinalityGuard"],
                "Fields are typed and bounded; log aggregation scales without a cardinality-cliff incident.",
            ),
            (
                "Trace-bound context",
                ["Tracer", "CorrelationContext"],
                "Each record carries trace + correlation ids; a slow span's logs are one join away.",
            ),
            (
                "Error forensics",
                ["ErrorSink", "StructuredLogger"],
                "Errors are captured with their log trail; reproducing a failure is a matter of filtering the stream, not ssh'ing to a pod.",
            ),
        ],
    ),
    "TelemetryExporter": (
        "Serialize batched spans, metrics, or log records into an OTLP-compatible envelope and deliver them to a collector with backoff.",
        ["Tracer", "MetricMeter", "ResourceDescriptor", "CircuitBreaker"],
        [
            (
                "OTLP contract",
                ["Tracer", "MetricMeter"],
                "All signal types share a serializer; swapping backends is a collector-config change, not a code change.",
            ),
            (
                "Backpressure-aware",
                ["CircuitBreaker", "LoadShedder"],
                "Exporter fails fast when the collector is unavailable; telemetry loss is bounded instead of causing request-path slowdowns.",
            ),
            (
                "Self-describing batches",
                ["ResourceDescriptor", "SemanticAttributes"],
                "Every batch carries the resource descriptor; the collector attributes data to the right service without extra metadata.",
            ),
        ],
    ),
    "Tracer": (
        "Create spans that represent a unit of work, attach attributes and events, link related spans, and propagate context across boundaries.",
        ["SemanticAttributes", "SamplingPolicy", "CorrelationContext", "TelemetryExporter"],
        [
            (
                "End-to-end traces",
                ["CorrelationContext", "SemanticAttributes"],
                "Spans inherit context across threads, tasks, and RPCs; attribute keys come from semconv — distributed traces line up without per-service wiring.",
            ),
            (
                "Budgeted observability",
                ["SamplingPolicy", "TelemetryExporter"],
                "Sampling controls volume; exporter handles delivery; the product gets a representative, bounded trace stream.",
            ),
            (
                "Debuggable errors",
                ["ErrorSink", "StructuredLogger"],
                "Uncaught exceptions attach to the active span; the error triage UI links to the full trace and log trail.",
            ),
        ],
    ),
    # ======================================================== policy
    "CorsPolicy": (
        "Deny-by-default evaluator for cross-origin browser requests that only echoes an allowlisted Origin and filters requested headers.",
        ["RouterPipeline", "RequestGuard", "ContentSecurityPolicy", "CsrfGuard"],
        [
            (
                "Browser edge hardening",
                ["RouterPipeline", "ContentSecurityPolicy"],
                "CORS + CSP compose into one edge policy: cross-origin requests are rejected and inline-script injection is blocked at render time.",
            ),
            (
                "No `*` with credentials",
                ["CsrfGuard", "RequestGuard"],
                "Credentialed routes never reflect `*`; CSRF binds the request to the session and Guard authorizes it — three checks, one decision.",
            ),
            (
                "Preflight caching",
                ["MiddlewarePipeline", "CorrelationContext"],
                "Preflight decisions are cacheable and logged with correlation; operators see which origins actually hit the service.",
            ),
        ],
    ),
    "DataResidencyPolicy": (
        "Bind a data_class to a set of allowed storage regions plus a transfer mechanism, rejecting writes to non-allowed regions.",
        ["PiiClassification", "EncryptionPolicy", "ProcessingRecord", "RetentionPolicy"],
        [
            (
                "Classification-driven placement",
                ["PiiClassification", "EncryptionPolicy"],
                "Sensitivity class determines region + cipher; moving a field across tiers is one declaration, not a schema migration.",
            ),
            (
                "Cross-border enforcement",
                ["ProcessingRecord", "AuditEvent"],
                "Every cross-EEA write either matches a bound transfer mechanism or is denied and audited — GDPR Chapter V is executable, not procedural.",
            ),
            (
                "Retention per region",
                ["RetentionPolicy", "LegalHold"],
                "Residency and retention declarations compose: a record stays in-region for its TTL and survives deletion only under a lawful hold.",
            ),
        ],
    ),
    "EncryptionPolicy": (
        "Declare cipher, KMS key provider, and rotation cadence per data_class and reject writes of sensitive data before a policy is bound.",
        ["KeyRotationSchedule", "DataResidencyPolicy", "PiiClassification", "SecretsVault"],
        [
            (
                "Cipher-per-class",
                ["PiiClassification", "DataResidencyPolicy"],
                "Sensitivity class pins cipher and region; unencrypted writes are rejected at the port — 'we forgot to encrypt field X' is a boot-time failure.",
            ),
            (
                "Scheduled rotation",
                ["KeyRotationSchedule", "SecretsVault"],
                "Keys rotate on cadence with overlap; the vault serves the current version and retires the previous without app restart.",
            ),
            (
                "Transit-and-rest symmetry",
                ["ContentSecurityPolicy", "SignatureVerifier"],
                "Transport and payload use matched strengths; a weak cipher anywhere is a structural incident, not a runtime anomaly.",
            ),
        ],
    ),
    "KeyRotationSchedule": (
        "Rotate data-encryption keys on a fixed cadence with an overlap window so prior versions still decrypt existing records.",
        ["EncryptionPolicy", "SecretsVault", "CryptoEnvelope", "SignatureVerifier"],
        [
            (
                "Cadenced rotation",
                ["EncryptionPolicy", "SecretsVault"],
                "Policy declares cadence; the vault ships the next version before the overlap expires — writes use the new key while reads still honor the old.",
            ),
            (
                "Envelope versioning",
                ["CryptoEnvelope", "SignatureVerifier"],
                "Ciphertext carries the key version; readers fetch the right version from the vault — a rotation is not a mass re-encryption event.",
            ),
            (
                "Miss-detection alert",
                ["MetricMeter", "AuditEvent"],
                "Missed rotations flip a metric and write an audit event; compliance lapse is a page, not an audit-year surprise.",
            ),
        ],
    ),
    # ======================================================== resiliency
    "Bulkhead": (
        "Partition concurrency so saturation inside one dependency cannot exhaust resources shared with other dependencies.",
        ["CircuitBreaker", "TimeoutBudget", "LoadShedder", "RequestShape"],
        [
            (
                "Dependency isolation",
                ["CircuitBreaker", "RequestShape"],
                "Each downstream has its own bulkhead; a slow dependency saturates its own pool without starving the rest of the service.",
            ),
            (
                "Priority lanes",
                ["LoadShedder", "RequestShape"],
                "Priority classes get dedicated pools; low-priority work is shed before high-priority work even notices contention.",
            ),
            (
                "Deadline + capacity",
                ["TimeoutBudget", "CircuitBreaker"],
                "Admission combines remaining budget and pool availability; a request is rejected fast rather than queuing past its deadline.",
            ),
        ],
    ),
    "CircuitBreaker": (
        "Short-circuit calls to a failing dependency by transitioning between closed, open, and half-open on rolling failure signals.",
        ["RetryPolicy", "TimeoutBudget", "Bulkhead", "HealthProbe"],
        [
            (
                "Bounded-retry guard",
                ["RetryPolicy", "TimeoutBudget"],
                "Breaker opens before retry storms amplify; budgets ensure retries never outlast the request deadline.",
            ),
            (
                "Dependency isolation",
                ["Bulkhead", "OutboundBinding"],
                "Each adapter has its own breaker and pool; one broken vendor does not take down the primary transaction path.",
            ),
            (
                "Probe-visible health",
                ["HealthProbe", "MetricMeter"],
                "Open breakers flip readiness false for the affected capability; callers drain instead of piling on.",
            ),
        ],
    ),
    "LoadShedder": (
        "Drop or reject low-priority work when the server enters an overload regime so high-priority traffic survives.",
        ["RateLimiter", "Bulkhead", "RequestShape", "TimeoutBudget"],
        [
            (
                "Priority-aware admission",
                ["RequestShape", "Bulkhead"],
                "Priority class + pool utilization drive admission; shed requests return 503 fast instead of queuing past their deadline.",
            ),
            (
                "Protect tail latency",
                ["TimeoutBudget", "RateLimiter"],
                "Under overload, the shedder trims tail work; the rate limiter maintains per-tenant fairness — p99 stays honest.",
            ),
            (
                "Cascade prevention",
                ["CircuitBreaker", "HealthProbe"],
                "Shedding before breakers trip keeps capacity observable; probes see real state, not 'every downstream breaker open'.",
            ),
        ],
    ),
    "RateLimiter": (
        "Enforce a maximum rate of admitted operations over a rolling window with optional waiting and per-tenant fairness.",
        ["LoadShedder", "RequestShape", "Bulkhead", "AuditEvent"],
        [
            (
                "Per-tenant fairness",
                ["RequestShape", "AuditEvent"],
                "Buckets are keyed by tenant / principal; noisy neighbors are throttled and audited — operators never wonder whose traffic spiked.",
            ),
            (
                "Abuse protection",
                ["RequestGuard", "AuditEvent"],
                "Auth failures hit a stricter bucket; brute-force attempts audit with velocity — the guard and limiter act as one admission layer.",
            ),
            (
                "Composed with shedding",
                ["LoadShedder", "Bulkhead"],
                "Rate limits cap steady-state; shedder cuts transient spikes; bulkheads isolate pools — three primitives, one admission SLO.",
            ),
        ],
    ),
    "RetryPolicy": (
        "Describe under which conditions a failed call may be retried, bounded by max attempts, backoff with jitter, and budget.",
        ["CircuitBreaker", "TimeoutBudget", "IdempotentConsumer", "RequestShape"],
        [
            (
                "Safe retries",
                ["IdempotentConsumer", "RequestShape"],
                "Retries reuse the request's idempotency key; the downstream consumer dedupes — at-least-once transport never causes double effects.",
            ),
            (
                "Bounded cost",
                ["TimeoutBudget", "CircuitBreaker"],
                "Backoff respects the remaining budget; the breaker opens before retries become a feedback loop.",
            ),
            (
                "Jittered fan-out",
                ["OutboundBinding", "RpcInterceptor"],
                "Policy mounts as an interceptor with per-vendor jitter; synchronized retries across pods are impossible by construction.",
            ),
        ],
    ),
    "TimeoutBudget": (
        "Attach a monotonic deadline to an inbound request and propagate the remaining budget to every downstream call.",
        ["RequestShape", "CircuitBreaker", "RetryPolicy", "MiddlewarePipeline"],
        [
            (
                "Deadline propagation",
                ["RequestShape", "MiddlewarePipeline"],
                "Pipeline stamps the deadline on entry; every downstream call reads the remaining budget — no handler extends time by accident.",
            ),
            (
                "Bounded retries",
                ["RetryPolicy", "CircuitBreaker"],
                "Retries never outlast the budget; budget-exhausted failures fail fast and surface meaningfully to the caller.",
            ),
            (
                "Priority interaction",
                ["LoadShedder", "Bulkhead"],
                "Admission considers (budget, priority, pool) together; a near-deadline low-priority request is dropped before it wastes capacity.",
            ),
        ],
    ),
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


# ---------------------------------------------------------------------------
# Emerging (non-manifest) primitives — compose-with only (§B1.2 grep coverage).
# These have no .manifest.json yet, so they do NOT appear in §B1.1 registry,
# but the task's grep validation command covers every .md under core/venous.
# ---------------------------------------------------------------------------

EMERGING: dict[str, list[tuple[str, list[str], str]]] = {
    "BatchCore": [
        (
            "Idempotent batch endpoint",
            ["IdempotencyStore", "RequestShape"],
            "Client sends a retry of the same batch with the same idempotency key; the store returns the cached per-item result set and BatchCore never re-invokes any handler.",
        ),
        (
            "Bounded parallelism",
            ["Bulkhead", "TimeoutBudget"],
            "Per-item semaphore + inherited deadline: a slow item cannot expand beyond its share of the pool or survive past the request's budget.",
        ),
        (
            "All-or-nothing transactional batch",
            ["UnitOfWork", "TransactionalOutbox"],
            "Failure stops processing; UoW rolls back; the outbox never emits events for items that didn't commit — downstream consumers see a coherent batch or no batch.",
        ),
    ],
    "CommandBus": [
        (
            "Write-side dispatch",
            ["CommandQuerySeparator", "UnitOfWork"],
            "Bus accepts only typed commands; each handler executes inside one UoW — commands that mutate state always commit atomically or not at all.",
        ),
        (
            "Idempotent commands",
            ["IdempotencyStore", "RequestShape"],
            "Command id is the idempotency key; the store caches the outcome — retried commands return the original result without re-executing side effects.",
        ),
        (
            "Auditable handler registry",
            ["AuditEvent", "RequestGuard"],
            "Every command dispatch audits the principal and authorized action; forbidden commands never reach the handler.",
        ),
    ],
    "DeprecationEntry": [
        (
            "Catalog + emit",
            ["DeprecationRegistry", "DeprecationReporter"],
            "Entry is the frozen value; registry routes requests to it; reporter counts hits — three primitives, one lifecycle for RFC 8594.",
        ),
        (
            "Schema-aware deprecation",
            ["SchemaComparator", "DeprecationRegistry"],
            "Comparator flags breaking changes between OpenAPI releases; the flagged endpoint becomes an Entry, scheduled for Sunset on the next release.",
        ),
        (
            "Sunset observability",
            ["DeprecationReporter", "StructuredLogger"],
            "Reporter emits structured counters per endpoint; operators see real traffic to retiring paths before the Sunset date arrives.",
        ),
    ],
    "DeprecationRegistry": [
        (
            "Middleware-stamped headers",
            ["MiddlewarePipeline", "DeprecationEntry"],
            "Pipeline asks the registry on every request; a hit stamps Sunset/Deprecation/Link headers uniformly — individual handlers never remember to do this.",
        ),
        (
            "Usage-driven retirement",
            ["DeprecationReporter", "MetricMeter"],
            "Registry lookups feed the reporter; hot deprecated endpoints are the signal not to retire on schedule.",
        ),
        (
            "Versioned rollout",
            ["SchemaComparator", "FeatureToggle"],
            "Schema diff populates the registry with sunset entries; a toggle can force 410 Gone once usage falls below threshold.",
        ),
    ],
    "DeprecationReporter": [
        (
            "Sunset-date triage",
            ["DeprecationRegistry", "DeprecationEntry"],
            "Reporter's usage_report joins with the registry's entries; the 'hottest deprecated endpoint' is obvious, and the scheduled Sunset date is one column away.",
        ),
        (
            "Metric-fed alerting",
            ["MetricMeter", "HealthProbe"],
            "Counter values feed dashboards; high usage past a threshold flips a readiness-style warning for API product owners.",
        ),
        (
            "Audit trail of retirement",
            ["AuditEvent", "StructuredLogger"],
            "Resets and Sunset enforcements are audited — there is no 'silent retirement' that support can't reconstruct.",
        ),
    ],
    "IdempotencyStore": [
        (
            "Retried-write dedup",
            ["CommandBus", "BatchCore"],
            "Handlers stash results keyed by the client's idempotency key; a retried request returns the stored result and never re-invokes the side effect.",
        ),
        (
            "Inbox-style dedup at the edge",
            ["InboundVerifier", "IdempotentConsumer"],
            "Inbound webhook verifier produces a stable event id; the store refuses replays with the same id — webhook at-least-once becomes effectively-once.",
        ),
        (
            "Bounded memory budget",
            ["CardinalityGuard", "MetricMeter"],
            "Store size is bounded and metered; an abusive client cannot exhaust memory by flooding unique keys.",
        ),
    ],
    "InboundVerifier": [
        (
            "Vendor-specific webhook trust",
            ["SignatureVerifier", "IdempotencyStore"],
            "Subclass delegates to SignatureVerifier with vendor's pinned key; the verified event id feeds the idempotency store — replay AND forgery are blocked in one pass.",
        ),
        (
            "Dispatcher seam",
            ["MiddlewarePipeline", "AuditEvent"],
            "One middleware selects the verifier by endpoint; every rejection is audited with the vendor name — forensic trails are uniform across vendors.",
        ),
        (
            "Graceful-failure envelope",
            ["CircuitBreaker", "RequestGuard"],
            "When a vendor key rotation is mid-flight, the breaker fails fast and the guard returns 401 — no ambiguous 500s during key overlap.",
        ),
    ],
    "MemoryPubSubBackend": [
        (
            "In-process event bus",
            ["EventBus", "LifecycleHook"],
            "Single-worker fan-out for intra-process events; shutdown hooks drain queues before SIGKILL — no dropped events on graceful exit.",
        ),
        (
            "Test-friendly TopicBus",
            ["TopicBus", "EventEnvelope"],
            "Conforms to the TopicBus contract with CloudEvents envelopes; tests run the pubsub layer without a broker.",
        ),
        (
            "FIFO per subscriber",
            ["StreamSubject", "CardinalityGuard"],
            "Subjects drive routing; per-topic cardinality is bounded — a typo cannot spawn unlimited queues.",
        ),
    ],
    "QueryBus": [
        (
            "Read-side dispatch",
            ["CommandQuerySeparator", "Specification"],
            "Query handlers take Specifications and return read models; the bus is the single seam where read-only semantics are enforced — no handler issues a write.",
        ),
        (
            "Cached query results",
            ["KeyValueBucket", "MaterializedView"],
            "Hot queries hit the bucket or view; cache miss falls through to the handler — response times stay bounded under spike.",
        ),
        (
            "Principal-scoped queries",
            ["CurrentPrincipal", "RequestGuard"],
            "Every query is scoped by principal + tenant; cross-tenant reads are a policy decision at the bus, not a developer oversight.",
        ),
    ],
    "FeatureFlagCache": [
        (
            "Low-latency toggle evaluation",
            ["FeatureToggle", "KeyValueBucket"],
            "Cache keeps per-cohort flag values hot; toggle evaluation is O(1) on the request path; misses refill via the bucket with bounded TTL.",
        ),
        (
            "Invalidation on change",
            ["EventBus", "AuditEvent"],
            "Flag-change events invalidate cache entries and audit the change — stale reads are bounded and the change is attributable.",
        ),
        (
            "Safe fallback",
            ["CircuitBreaker", "ConfigBinding"],
            "If the upstream provider is unreachable, the cache serves last-known-good; ConfigBinding supplies the default — a feature-flag outage never 500s a route.",
        ),
    ],
    "SchemaComparator": [
        (
            "Compat gate for CI",
            ["DeprecationEntry", "DeprecationRegistry"],
            "Breaking changes turn into DeprecationEntries in the registry automatically; CI fails if a breaking change ships without a sunset plan.",
        ),
        (
            "Canary rollout",
            ["FeatureToggle", "RequestGuard"],
            "Behavioral changes are gated behind a toggle; the guard reads toggle state per request — old and new shapes coexist until the toggle is retired.",
        ),
        (
            "Audit of schema evolution",
            ["AuditEvent", "TamperEvidentAuditLog"],
            "Every OpenAPI release seals a diff hash into the audit log; auditors verify 'what shape was public on date X' cryptographically.",
        ),
    ],
    "CostTracker": [
        (
            "Per-request cost attribution",
            ["RequestShape", "MetricMeter"],
            "Tracker composes estimators keyed by component; results ride on the request shape, flushed to metrics — cost per endpoint/tenant is observable, not inferred.",
        ),
        (
            "Budget-enforced shedding",
            ["LoadShedder", "TimeoutBudget"],
            "When a request exceeds its cost budget, the shedder can drop it before downstream calls fire — budget is a first-class admission signal.",
        ),
        (
            "LLM cost governance",
            ["LlmTrace", "PromptTemplate"],
            "LLM spans carry template + token cost; tracker sums per template — A/B prompt costs are comparable across releases.",
        ),
    ],
    "ExcelExporter": [
        (
            "Bounded-memory export",
            ["LoadShedder", "TimeoutBudget"],
            "Chunked streaming + max_rows cap + shedder admission means an export request cannot starve general traffic.",
        ),
        (
            "Observable long work",
            ["MetricMeter", "StructuredLogger"],
            "Chunk counters + duration histograms make export SLOs measurable; a slow export is visible, not anecdotal.",
        ),
        (
            "Secured output",
            ["PiiClassification", "OutputEncoder"],
            "Rows pass through classification-driven masking before sheet writes — audience-aware exports are mechanical, not a review checklist.",
        ),
    ],
    "GracefulShutdown": [
        (
            "Drain-then-stop",
            ["LifecycleHook", "HealthProbe"],
            "Shutdown flips readiness false first; hooks drain queues; in-flight requests complete within the phase budget — no 502 during deploys.",
        ),
        (
            "Coordinated with workflows",
            ["WorkflowRun", "ActivityCall"],
            "Activities heartbeat through the drain phase; workflows survive the restart and resume on the next pod — no orphaned long-running work.",
        ),
        (
            "Bounded cleanup",
            ["TimeoutBudget", "ErrorSink"],
            "Cleanup has a hard cap; lingering errors flush to the error sink before exit — nothing is silently lost on SIGTERM.",
        ),
    ],
    "ModelRegistry": [
        (
            "Lazy versioned loading",
            ["KeyValueBucket", "LifecycleHook"],
            "Registry caches loaded models keyed by name:version; lifecycle hooks warm the hot set at boot — the first request isn't a cold-start cliff.",
        ),
        (
            "Safe A/B rollout",
            ["FeatureToggle", "LlmTrace"],
            "Toggle routes a cohort to a new model version; traces carry the version attribute — quality diffs are per-version, not per-deploy.",
        ),
        (
            "Bounded memory",
            ["MetricMeter", "CardinalityGuard"],
            "Loaded-model count is metered and bounded; one stray version cannot OOM the server.",
        ),
    ],
    "Redactor": [
        (
            "Log-path PII hygiene",
            ["StructuredLogger", "PiiClassification"],
            "Structlog processor consumes classification tags; every emitted record is masked before any sink sees it — PII cannot escape via the log stream.",
        ),
        (
            "Audit-compatible masking",
            ["AuditEvent", "AccessLog"],
            "Audit and access records share the same redactor; the tamper-evident chain records masked values, never raw PII.",
        ),
        (
            "Error-path safety",
            ["ErrorSink", "StructuredLogger"],
            "Exception captures route through the redactor; stack traces containing request bodies are sanitized before Sentry or the local sink.",
        ),
    ],
    "TracingBuffer": [
        (
            "Dev-time trace inspector",
            ["Tracer", "StructuredLogger"],
            "Ring buffer of the last N traces drives a local UI; developers reproduce issues without spinning up the full OTel stack.",
        ),
        (
            "Bounded memory",
            ["CardinalityGuard", "MetricMeter"],
            "Fixed-size ring + bounded per-record size prevents a buggy loop from OOMing the process through trace capture.",
        ),
        (
            "Error-triage bridge",
            ["ErrorSink", "CorrelationContext"],
            "Exception capture attaches the latest traces for the same correlation id — 'what was happening just before this error' is one click.",
        ),
    ],
    "RetryBudget": [
        (
            "Retry-storm prevention",
            ["RetryPolicy", "CircuitBreaker"],
            "Sliding-window ratio gate ensures retries cannot exceed a fraction of the window; a partial outage does not amplify into a full outage.",
        ),
        (
            "Budget-aware policy",
            ["TimeoutBudget", "RequestShape"],
            "Retry admission considers remaining request budget and priority class — low-priority retries yield first under pressure.",
        ),
        (
            "Observable retry health",
            ["MetricMeter", "HealthProbe"],
            "Retry ratio is a first-class metric; a breaker-style readiness flip fires before customer impact.",
        ),
    ],
}

# ---------------------------------------------------------------------------
# Remove placeholder key
# ---------------------------------------------------------------------------
E.pop("TokenIntrospectorX", None)


# ---------------------------------------------------------------------------
# Build YAML + append Compose-with
# ---------------------------------------------------------------------------


def concern_for(namespace: str, name: str) -> str:
    if namespace == "data":
        return DATA_CONCERN[name]
    return CONCERN_BY_NS[namespace]


def build() -> None:
    # Collect manifests
    manifests = sorted([m for m in VENOUS.rglob("*.manifest.json") if "_staging" not in m.parts])

    primitives = []
    known_names: set[str] = set()
    for m in manifests:
        data = json.loads(m.read_text())
        known_names.add(data["name"])

    missing_data = [name for name in known_names if name not in E]
    if missing_data:
        raise SystemExit(f"Missing curated entries for: {sorted(missing_data)}")

    for m in manifests:
        data = json.loads(m.read_text())
        ns = data["namespace"]
        name = data["name"]
        purpose, compose_with, _patterns = E[name]
        # Validate compose_with: 2-5 siblings, all known
        if not (2 <= len(compose_with) <= 5):
            raise SystemExit(f"{name}: compose_with has {len(compose_with)} entries (need 2-5)")
        bad = [c for c in compose_with if c not in known_names]
        if bad:
            raise SystemExit(f"{name}: dangling compose_with refs: {bad}")
        primitives.append(
            {
                "name": name,
                "namespace": ns,
                "concern": concern_for(ns, name),
                "purpose": purpose,
                "compose_with": compose_with,
            }
        )

    # Sort by (namespace, name)
    primitives.sort(key=lambda p: (p["namespace"], p["name"]))

    # Emit YAML by hand (no dep)
    def yaml_str(s: str) -> str:
        # Always quote to be safe for YAML 1.2; escape embedded quotes.
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = ["version: 1", "primitives:"]
    for p in primitives:
        lines.append(f"  - name: {p['name']}")
        lines.append(f"    namespace: {p['namespace']}")
        lines.append(f"    concern: {p['concern']}")
        lines.append(f"    purpose: {yaml_str(p['purpose'])}")
        lines.append("    compose_with:")
        for c in p["compose_with"]:
            lines.append(f"      - {c}")
    REGISTRY.write_text("\n".join(lines) + "\n")
    print(f"[§B1.1] wrote {REGISTRY.relative_to(SKILL_ROOT)} with {len(primitives)} entries")

    # Include emerging primitives in the universe so cross-refs validate.
    known_all = set(known_names) | set(EMERGING.keys())

    # §B1.2 — append Compose with: section (production + emerging)
    appended = 0
    already = 0
    # Build an iterable of (md_path, name, patterns) covering both.
    targets: list[tuple[Path, str, list]] = []
    for m in manifests:
        data = json.loads(m.read_text())
        name = data["name"]
        md_path = m.parent / f"{name}.md"
        _purpose, _cw, patterns = E[name]
        targets.append((md_path, name, patterns))
    for name, patterns in EMERGING.items():
        # discover md path by searching
        hits = list(VENOUS.rglob(f"{name}/{name}.md"))
        hits = [h for h in hits if "_staging" not in h.parts]
        if not hits:
            raise SystemExit(f"emerging {name}: md not found under core/venous/*/{name}/")
        targets.append((hits[0], name, patterns))

    for md_path, name, patterns in targets:
        if not md_path.exists():
            raise SystemExit(f"Missing .md: {md_path}")
        body = md_path.read_text()
        if "## Compose with:" in body:
            already += 1
            continue
        if len(patterns) < 3:
            raise SystemExit(f"{name}: need ≥3 compose patterns, got {len(patterns)}")
        for pname, siblings, _inv in patterns:
            if len(siblings) < 2:
                raise SystemExit(f"{name}/{pname}: need ≥2 siblings")
            bad = [s for s in siblings if s not in known_all]
            if bad:
                raise SystemExit(f"{name}/{pname}: dangling refs {bad}")
        _ = patterns  # keep below
        # Build section text
        out = []
        out.append("## Compose with:")
        out.append("")
        for pname, siblings, inv in patterns:
            bullets = " + ".join(f"`{s}`" for s in siblings)
            out.append(f"- **{pname}** → {bullets}")
            out.append(f"  {inv}")
            out.append("")
        section = "\n".join(out).rstrip() + "\n"
        # Ensure trailing newline before append
        if not body.endswith("\n"):
            body += "\n"
        if not body.endswith("\n\n"):
            body += "\n"
        md_path.write_text(body + section)
        appended += 1
    print(f"[§B1.2] appended {appended} sections; {already} already present")


if __name__ == "__main__":
    build()
