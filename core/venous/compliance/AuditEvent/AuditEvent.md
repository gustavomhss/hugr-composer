# AuditEvent

## What it does (plain language)

AuditEvent is the tamper-evident record for every security-relevant action.
Actor + action + resource + outcome, chained by cryptographic hash. Regulated
environments (SOC2, HIPAA, PCI-DSS) require a trail that cannot be quietly
rewritten; this is that trail. Product impact: compliance audits pass without
last-minute forensics, and "who did what when" is answerable in one query.

## Glossary

- **Actor**: the identity performing the action (a user email, a service
  name, or the reserved literal `system` for scheduled jobs).
- **Action**: the verb describing what happened (`CREATE`, `READ`, `UPDATE`,
  `DELETE`, `GRANT`, `REVOKE`, `EXPORT`, or a namespaced extension like
  `payment.refund`).
- **Resource**: the object acted upon (`resource_type` + `resource_id`).
- **Outcome**: whether the action succeeded, failed (system error), or was
  denied (authorization refused).
- **Hash chain**: each event carries the hash of the previous event so any
  later tampering is detectable. Mathematically equivalent to a single-writer
  Merkle chain.
- **WORM**: Write-Once-Read-Many storage (e.g. S3 Object Lock); the physical
  substrate that complements the hash chain.
- **SIEM**: Security Information & Event Management system — the real-time
  alerting consumer of the audit stream.

## Purpose

Emit a tamper-evident, append-only record of a security-relevant action with
actor, subject, action verb, outcome, and a cryptographic chain link.

## When to use and when NOT to use

- USE: grants, revokes, data exports, destructive updates, admin actions,
  denied access attempts. Anything a compliance auditor would ask about.
- DO NOT USE: high-volume operational logging — that is `StructuredLogger`.
- DO NOT USE: metrics aggregation — that is `MetricMeter`.
- DO NOT USE: span events — that is `Tracer.add_event`.

## API surface (catalog fidelity)

`AuditEvent` is a frozen dataclass with fields in the order declared by the
catalog `api_signature`. `AuditEventSink` is the Protocol with
`emit(event)` and `verify_chain(from_event_id=None) -> bool`. The catalog
entry is reproduced verbatim in `AuditEvent.contract.json`.

## Invariants

| ID | Rule |
|---|---|
| AUD_INV_01 | event_hash MUST be SHA-256 over canonical fields + prev_hash. |
| AUD_INV_02 | AuditEvent is append-only; CANNOT be updated, deleted, or superseded. |
| AUD_INV_03 | outcome MUST be one of {success, failure, denied}. |
| AUD_INV_04 | actor_id MUST be set; 'system' is reserved for system-initiated actions. |
| AUD_INV_05 | occurred_at MUST be absolute UTC with ≥ millisecond precision. |
| AUD_INV_06 | action verbs MUST come from controlled vocabulary or be namespaced. |

## Hash chain

Each event's `event_hash` is SHA-256 over the canonical serialization of all
non-hash fields concatenated with the previous event's hash. Canonical
serialization sorts attribute keys so order-equivalent events hash identically
(metamorphic property proven in tests). Tampering with any field invalidates
every subsequent link; `verify_chain()` walks the chain and returns False on
the first inconsistency. Partial verification from a known-good event is
supported via `from_event_id=...`.

## Thread safety

All writes to the in-memory sink are protected by a `threading.Lock`; events
are atomically appended. Pre-emit hooks registered via `register_before_emit`
run inside the lock so fan-out to downstream sinks observes identical
ordering. `verify_chain` takes the same lock and is safe during concurrent
emission.

## Operational characteristics

- Hash computation: SHA-256 over canonical serialization; ~1 µs per event
  on commodity hardware.
- Verification: linear in chain length. Call periodically (nightly job) to
  catch WORM storage drift; call on-demand before regulatory reports.
- WORM storage: the in-memory sink is a buffer. Production deployments fan
  out to WORM-capable stores via `register_before_emit` hooks (S3 Object
  Lock, Glacier Vault Lock, vendor SIEM).
- Self-observability: `audit.events.emitted{action, outcome}`,
  `audit.chain.verify.failures{reason}`. Any non-zero verify-failure rate is
  an incident.

## Error model

- Direct tampering (constructing an `AuditEvent` with a wrong `event_hash`)
  is rejected by the sink's `emit()`, which recomputes the hash and raises
  `AuditEventInvariantError`.
- Re-emitting an `event_id` that already exists is rejected (AUD-INV-02).
- Out-of-vocabulary actions, non-UTC timestamps, unknown outcomes, and empty
  `actor_id` all raise at construction with messages naming the invariant ID.

## Security considerations

- The hash chain is the tamper-evidence primitive. Storage-layer integrity
  (WORM) complements but does not replace it.
- Secrets MUST NOT appear in `attributes`. Producers redact PII before
  calling `build_event`; the sink does NOT scrub attributes (that would
  change the hash and invalidate the chain).
- Clock skew across emitters can re-order events in wall time but does NOT
  break the chain — causality is proven by `prev_hash`, not by timestamp.
- Denied actions are first-class — the `denied` outcome is always recorded,
  which is how regulators detect failed privilege-escalation attempts.

## Provenance

- Source agent: Agent #7 OBSERVABILITY (catalog places `AuditEvent` in the
  `compliance` namespace because its mutability contract diverges from
  best-effort telemetry).
- NIST SP 800-92 — Guide to Computer Security Log Management.
- *Observability Engineering* (2022), chapter 14 on audit records.
- OpenTelemetry Semantic Conventions 1.27 — General actor identity keys.

## Alternatives considered and rejected

- Reusing `StructuredLogger` for audit — rejected: logs are mutable at the
  pipeline level and lack a tamper-evident chain.
- Database row CRUD history — rejected: captures state deltas, not actor
  intent or denied actions.
- External SIEM-only ingestion — rejected: SIEM becomes the source of truth
  and proof-of-intent is delegated offsite.

## Extension contract

Domains extend the vocabulary by registering a namespaced action prefix
(e.g. `payment.refund`) through an `AuditVocabulary` provider. Sinks are added
by implementing `AuditEventSink` and composing them into a `FanOutSink` so
WORM storage, SIEM, and warm-query stores each receive the same stream. The
`register_before_emit` hook lets extensions run under the append lock so
ordering is preserved across destinations.

## Usage

```python
def record_user_export(sink, actor: str, user_id: str, prev_hash: str) -> AuditEvent:
    from hashlib import sha256
    from datetime import datetime, timezone
    event_id = "evt_01J9ZX"
    canonical = f"{event_id}|{actor}|user|EXPORT|{user_id}|success|{prev_hash}"
    evt = AuditEvent(
        event_id=event_id,
        occurred_at=datetime.now(timezone.utc),
        actor_id=actor,
        actor_type="human",
        action="EXPORT",
        resource_type="user",
        resource_id=user_id,
        outcome="success",
        attributes={"reason": "dsar"},
        prev_hash=prev_hash,
        event_hash=sha256(canonical.encode()).hexdigest(),
    )
    sink.emit(evt)
    return evt
```

## Compose with:

- **Non-repudiable action trail** → `TamperEvidentAuditLog` + `CurrentPrincipal`
  Every write is sealed into a hash-chained log keyed by the principal — auditors can verify 'this sequence of actions was not edited after the fact'.

- **Correlated incident forensics** → `CorrelationContext` + `StructuredLogger`
  Audit events carry the same correlation id as ops logs so 'show me everything this request touched' is one query across two streams.

- **Read vs write separation** → `AccessLog` + `TamperEvidentAuditLog`
  Audit records security events; AccessLog records reads of classified data — HIPAA accounting-of-disclosures stays readable when audit volume is low.

- **Tamper-evident allow-list** → `PersistedQueryRegistry` + `InputValidator`
  Every `PersistedQueryRegistry` tamper-error or unknown-id event is appended to the audit log, so attackers brute-forcing ids are visible to SRE within one dashboard tick. Invariant gained: persisted-query anomalies are visible signals not silent noise.
