"""WP-17 — curated compose-data entries for the `compliance` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === compliance`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
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
}
