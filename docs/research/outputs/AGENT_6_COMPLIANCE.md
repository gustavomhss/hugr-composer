# AGENT 6 — COMPLIANCE

> Primitives extracted from SOC 2, HIPAA, GDPR, PCI-DSS, and NIST SP 800-53 so
> every Arsenal target ships compliance surface by default.

## Scope recap

- **IN:** tamper-evident audit, retention, consent, DSAR/RTBF, PII tagging, access logging, encryption policy.
- **OUT:** security mechanics (Agent 5), legal interpretation, certification/audit processes.
- **Namespaces owned:** `compliance`, `obs`, `data`, `policy`.

## Sources consulted

| Source | Citations |
|---|---|
| EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32 | 6 |
| HIPAA Security Rule 45 CFR §§ 164.308-164.312 | 5 |
| NIST SP 800-53 revision 5 | 5 |
| AICPA SOC 2 Trust Services Criteria (2017, 2022 revision) | 4 |
| PCI-DSS v4.0 | 4 |

No source exceeds 25% of citations — breadth across the five standards.

---

## Primitives

### 1. `TamperEvidentAuditLog` — `compliance`

Append-only, hash-chained, externally signed record of security-relevant events.
Each entry references the SHA-256 of the prior entry; signatures are produced by
a KMS whose private key is never held by the writer. Anchored in **SOC 2 CC7.2**
(detection of anomalies), **NIST AU-9 / AU-10** (audit protection and
non-repudiation), and **HIPAA § 164.312(b)** (audit controls).

Why a primitive: a per-service audit stream cannot be cross-verified, and
per-table shadow columns are trivially mutable by a DBA. One chain per tenant
collapses the attack surface.

### 2. `RetentionPolicy` — `compliance`

Declarative binding of a `data_class` to `max_age`, `legal_basis`, and
`deletion_mode` (`hard` / `crypto_shred` / `anonymize`). Writes of untagged data
are rejected at the repository boundary. Anchored in **GDPR Art 5(1)(e)**
(storage limitation), **PCI-DSS Req 3.2** (no unnecessary cardholder data),
**NIST SI-12**.

Why a primitive: TTL indexes and cron jobs cannot carry `legal_basis` or honor
`LegalHold`; retention without the binding degrades to per-table folklore.

### 3. `ConsentLedger` — `compliance`

Records grants and revocations keyed by `(subject_id, purpose)`, always with
`notice_version`. History is append-only; state at an arbitrary past timestamp
is reconstructible. Anchored in **GDPR Art 6(1)(a) / Art 7** and **SOC 2
Privacy P3.1**.

Why a primitive: a boolean on `users` loses history; the CRM is racy against
transactional processing. A central ledger is the only way to prove lawful
basis at a point in time.

### 4. `DataSubjectRequest` — `compliance`

Coordinates access, portability, rectification, and erasure requests across all
registered stores. Enforces a statutory `due_at` that never pauses, requires an
artifact from every store before close, and invokes the erasure cascade on
kind=`erasure`. Anchored in **GDPR Art 15 / Art 17** and **HIPAA § 164.308(a)(4)**.

Why a primitive: ad-hoc tickets miss stores silently; a primitive makes the
manifest mandatory for closure.

### 5. `PiiClassification` — `data`

Schema-level annotation tagging every field as `PUBLIC`, `INTERNAL`, `PII`,
`PHI`, or `PCI`. Serializers and log formatters must route through `mask()`
before emission. Down-grading sensitivity requires an approver id in the audit
log. Anchored in **HIPAA § 164.514(b)** (safe-harbor de-identification),
**PCI-DSS Req 3.4** (PAN masking), **NIST MP-3 / MP-4**.

Why a primitive: regex scrubbers are lossy; hand-mapped DTOs drift with the
schema. Making leakage a type error is the only scalable stance.

### 6. `AccessLog` — `obs`

Records every successful read of classified data with `actor`, `record_id`,
`data_class`, and `purpose_of_use` from a closed set. Deliberately separate
from `TamperEvidentAuditLog` so read volume does not mask security events.
Anchored in **HIPAA § 164.312(b)** and **SOC 2 CC6.1**. Retention bound by
registered `RetentionPolicy`.

Why a primitive: HIPAA's accounting-of-disclosures obligation (§ 164.528) is
unworkable if reads and security events share one stream.

### 7. `EncryptionPolicy` — `policy`

Per-`data_class` declaration of at-rest cipher (AES-256-GCM /
ChaCha20-Poly1305), in-transit minimum (TLS 1.2+), KMS provider, and rotation
cadence. Unapproved ciphers and raw key material in config are rejected at
bind. Anchored in **PCI-DSS Req 3.5 / 4.2**, **HIPAA § 164.312(a)(2)(iv) /
(e)(2)(ii)**, **NIST SC-13 / SC-8**.

Why a primitive: cloud-default disk encryption ignores field-level cipher and
key ownership; per-service choices drift.

### 8. `KeyRotationSchedule` — `policy`

Schedules rotation on a cadence with an overlap window. Old versions become
decrypt-only past `cadence + overlap`; new writes with them are rejected.
Rotation events are audit-logged with old and new key versions. Anchored in
**PCI-DSS Req 3.7.4** and **NIST SC-12**.

Why a primitive: manual rotation playbooks lapse; cloud auto-rotation covers
CMKs but not application DEKs or HMAC keys.

### 9. `ProcessingRecord` — `compliance`

Machine-readable Record of Processing Activities (ROPA) generated from
decorator annotations on handlers — not a spreadsheet. Each record references a
bound `RetentionPolicy` and declares `legal_basis` from the GDPR Art 6
enumeration. `export_ropa()` is byte-reproducible for audit hashing. Anchored
in **GDPR Art 30**.

Why a primitive: externally-maintained ROPA drifts from the code within one
sprint.

### 10. `LegalHold` — `data`

Suspends retention-driven deletion and DSAR erasure for records covered by a
scope query. `RetentionPolicy.sweep` and `DataSubjectRequest` erasure MUST
consult `covers()` before deletion. Release requires an actor distinct from the
opener. Anchored in **SOC 2 CC2.3** and **NIST AU-11**.

Why a primitive: without an explicit hold, the sweeper destroys evidence and an
RTBF endpoint fulfills a request that should have been paused.

### 11. `BreachNotificationQueue` — `compliance`

Tracks suspected and confirmed personal-data incidents with a 72-hour statutory
clock. At T-24h the queue emits a breach-of-SLA alert. Closure without
`notify_authority` or an explicit `no_notification_required + legal_basis` is
rejected. Anchored in **GDPR Art 33** and **HIPAA § 164.308(a)(6)**.

Why a primitive: generic ticket trackers have no statutory clock.

### 12. `DataResidencyPolicy` — `policy`

Binds a data class to ISO-3166 `allowed_regions` and a `transfer_mechanism`
(e.g. `SCC_2021/914`, `adequacy_decision`). Writes outside the allow-list fail;
cross-border transfers without a valid mechanism are blocked at the replication
/ backup seam too. Anchored in **GDPR Chapter V (Arts 44-50)** and **PCI-DSS
Req 12.8**.

Why a primitive: single-region deployments miss replicas, backups, and
analytics copies; network geo-fencing breaks on VPN.

---

## Cross-cutting insights

1. **Audit spine.** Every other compliance primitive emits to
   `TamperEvidentAuditLog` on state change — retention purges, DSAR closures,
   hold open/release, breach notifications, key rotations, residency changes.
2. **Classification is upstream.** `PiiClassification` seeds behavior for
   `AccessLog`, `EncryptionPolicy`, `RetentionPolicy`, `ProcessingRecord`, and
   `DataResidencyPolicy` — mis-tagging one field multiplies through.
3. **Retention vs. preservation.** `LegalHold` is the explicit reconciliation
   between GDPR Art 17 erasure and NIST AU-11 preservation — these primitives
   only coexist with a hold mechanism.
4. **Two sides of lawful basis.** `ConsentLedger` carries subject-level state
   per purpose (Art 7); `ProcessingRecord` carries controller-level state per
   activity (Art 30). Neither alone proves compliance.
5. **Time as first-class.** DSAR `due_at`, breach 72h clock, key rotation
   cadence, retention max-age — statutory / cryptographic deadlines must fire
   in code, not runbooks.
6. **Volume separation.** Splitting `AccessLog` from the audit log is enforced
   by regulatory volume realities — HIPAA § 164.528 is unworkable in a combined
   stream.
7. **Policy-namespace pattern.** `EncryptionPolicy`, `KeyRotationSchedule`, and
   `DataResidencyPolicy` are registry-bound fail-closed gates: bind at startup,
   enforce at every write, no runtime escape hatch.

## Gaps observed against SKILL-001

1. No hash-chained audit primitive; writes land in structured logs without
   per-entry signature or chain verification.
2. No declarative retention binding — retention is per-table via ad-hoc scripts.
3. Consent modeled as boolean flags; no notice-version history.
4. DSAR requires cross-store cascade; no primitive enforces per-store artifact
   manifest before closure.
5. PII classification is not schema-level; masking is left to serializer code.
6. AccessLog separate from security audit is missing, blocking HIPAA § 164.528
   reports.
7. EncryptionPolicy per data_class not enforced at write; at-rest encryption
   trusted to cloud defaults.
8. LegalHold absent — retention sweepers can destroy evidence.
9. Breach notification has no statutory clock.
10. DataResidencyPolicy not modeled — replicas and backups ignored.
